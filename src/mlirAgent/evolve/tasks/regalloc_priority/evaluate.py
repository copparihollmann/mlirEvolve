"""Evaluator for LLVM register allocation priority evolution.

Called by OpenEvolve as: python evaluate.py <program_path>

Pipeline:
1. Patch evolved C++ priority function into LLVM source tree
2. Rebuild opt + llc incrementally (ninja)
3. For each CTMark benchmark .bc file:
   a. opt -O2 bench.bc -o bench_opt.bc
   b. llc -O2 -use-evolved-regalloc-priority bench_opt.bc -o bench.o
   c. gcc bench.o -o bench -lm -lpthread -ldl [-lstdc++ for C++]
   d. Measure linked binary size
   e. Run benchmark with reference inputs and measure wall-clock time
4. Score = weighted combination of runtime speedup and binary size reduction
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import optuna


# ---------------------------------------------------------------------------
# Optuna inner-loop configuration
# ---------------------------------------------------------------------------

_OPTUNA_TRIALS = int(os.environ.get("EVOLVE_OPTUNA_TRIALS", "20"))
_OPTUNA_SUBSET = ["sqlite3", "spass", "tramp3d-v4"]
_HYPERPARAM_RE = re.compile(
    r"//\s*\[hyperparam\]:\s*([\w-]+),\s*(\w+),\s*(-?\d+),\s*(-?\d+)"
)


def _extract_hyperparams(code: str):
    """Parse [hyperparam] comments from C++ source."""
    return [
        (m.group(1), m.group(2), int(m.group(3)), int(m.group(4)))
        for m in _HYPERPARAM_RE.finditer(code)
    ]


# ---------------------------------------------------------------------------
# Benchmark configuration (shared with llvm_inlining task)
# ---------------------------------------------------------------------------

_EVAL_DIR = Path(__file__).resolve().parent
_INLINING_DIR = _EVAL_DIR.parent / "llvm_inlining"
_BENCH_DIR = _INLINING_DIR / "benchmarks"
_TESTSUITE_DIR = _BENCH_DIR / "testsuite"
_DATA_DIR = _TESTSUITE_DIR / "data"
_BASELINE_FILE = _EVAL_DIR / "baseline_regalloc.json"

_OPT_TIMEOUT = int(os.environ.get("EVOLVE_OPT_TIMEOUT", "120"))

_EXCLUDED = {"clamav", "7zip"}

_EXTRA_LINK_FLAGS = {
    "7zip": ["-lstdc++", "-pthread"],
    "bullet": ["-lstdc++"],
    "kimwitu": ["-lstdc++"],
    "tramp3d-v4": ["-lstdc++"],
}

_BENCH_RUN_CONFIGS = {
    "7zip": {"args": ["b"], "timeout": 60},
    "bullet": {"data_files": ["landscape.mdl", "Taru.mdl"], "timeout": 30},
    "consumer-typeset": {
        "args": ["-x", "-I", "data/include", "-D", "data/data",
                 "-F", "data/font", "-C", "data/maps", "-H", "data/hyph",
                 "large.lout"],
        "data_subdir": True, "timeout": 60,
    },
    "kimwitu": {
        "args": ["-f", "test", "-o", "-v", "-s", "kcc",
                 "inputs/f3.k", "inputs/f2.k", "inputs/f1.k"],
        "data_subdir": True, "timeout": 30,
    },
    "lencod": {
        "args": ["-d", "data/encoder_small.cfg",
                 "-p", "InputFile=data/foreman_part_qcif_444.yuv",
                 "-p", "LeakyBucketRateFile=data/leakybucketrate.cfg",
                 "-p", "QmatrixFile=data/q_matrix.cfg"],
        "data_subdir": True, "timeout": 120,
    },
    "mafft": {
        "args": ["-b", "62", "-g", "0.100", "-f", "2.00", "-h", "0.100", "-L"],
        "stdin_file": "pyruvate_decarboxylase.fasta", "timeout": 60,
    },
    "spass": {
        "args": ["problem.dfg"],
        "data_files": ["problem.dfg"], "timeout": 60,
    },
    "sqlite3": {
        "args": ["-init", "sqlite3rc", ":memory:"],
        "stdin_file": "commands",
        "data_files": ["sqlite3rc"], "timeout": 60,
    },
    "tramp3d-v4": {
        "args": ["--cartvis", "1.0", "0.0", "--rhomin", "1e-8",
                 "-n", "4", "--domain", "32", "32", "32"],
        "timeout": 120,
    },
}


def _find_benchmarks():
    """Find CTMark .bc files, excluding problematic ones."""
    if not _TESTSUITE_DIR.exists():
        return []
    return sorted(
        bc for bc in _TESTSUITE_DIR.glob("*.bc")
        if bc.stem not in _EXCLUDED
    )


def _run_benchmark(name, binary_path, tmp_dir):
    """Run a benchmark with reference inputs and return wall-clock time."""
    config = _BENCH_RUN_CONFIGS.get(name)
    if not config:
        return None

    run_dir = os.path.join(tmp_dir, f"{name}_run")
    os.makedirs(run_dir, exist_ok=True)
    run_binary = os.path.join(run_dir, name)
    shutil.copy2(binary_path, run_binary)
    os.chmod(run_binary, 0o755)

    bench_data = _DATA_DIR / name

    if config.get("data_subdir") and bench_data.exists():
        for item in bench_data.iterdir():
            dst = os.path.join(run_dir, item.name)
            if item.is_dir():
                shutil.copytree(str(item), dst, dirs_exist_ok=True)
            else:
                shutil.copy2(str(item), dst)
    elif config.get("data_files") and bench_data.exists():
        for f in config["data_files"]:
            src = bench_data / f
            if src.exists():
                shutil.copy2(str(src), os.path.join(run_dir, f))

    stdin_fh = None
    if config.get("stdin_file") and bench_data.exists():
        stdin_src = bench_data / config["stdin_file"]
        if stdin_src.exists():
            stdin_fh = open(str(stdin_src), "r")

    cmd = [run_binary] + config.get("args", [])
    timeout = config.get("timeout", 30)

    try:
        start = time.time()
        proc = subprocess.run(
            cmd, capture_output=True, timeout=timeout,
            cwd=run_dir, stdin=stdin_fh
        )
        elapsed = time.time() - start
        if proc.returncode == 0:
            return elapsed
    except subprocess.TimeoutExpired:
        pass
    finally:
        if stdin_fh:
            stdin_fh.close()
    return None


def _compile_benchmark(bc_path, opt_path, llc_path, use_evolved, tmp_dir,
                       extra_llc_flags=None):
    """Compile a .bc file through opt -> llc -> gcc.

    For regalloc priority, the evolved flag is on llc (not opt), since
    register allocation happens during code generation.

    Returns (binary_size, runtime, error_string).
    """
    name = bc_path.stem
    opt_bc = os.path.join(tmp_dir, f"{name}_opt.bc")
    obj_file = os.path.join(tmp_dir, f"{name}.o")
    binary = os.path.join(tmp_dir, name)

    # opt pass (standard O2, no evolved flag — regalloc is in llc)
    opt_cmd = [str(opt_path), "-O2", str(bc_path), "-o", opt_bc]
    try:
        proc = subprocess.run(opt_cmd, capture_output=True, text=True,
                              timeout=_OPT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, None, f"opt timed out ({_OPT_TIMEOUT}s)"
    if proc.returncode != 0:
        return None, None, proc.stderr[:500]

    # llc: bitcode -> object (evolved regalloc priority flag here)
    llc_cmd = [str(llc_path), "-O2", "-filetype=obj", "-relocation-model=pic"]
    if use_evolved:
        llc_cmd.append("-use-evolved-regalloc-priority")
    if extra_llc_flags:
        llc_cmd.extend(extra_llc_flags)
    llc_cmd += [opt_bc, "-o", obj_file]

    try:
        proc = subprocess.run(llc_cmd, capture_output=True, text=True,
                              timeout=_OPT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, None, f"llc timed out ({_OPT_TIMEOUT}s)"
    if proc.returncode != 0:
        return None, None, proc.stderr[:500]

    # Link
    extra_flags = _EXTRA_LINK_FLAGS.get(name, [])
    gcc_cmd = ["gcc", obj_file, "-o", binary, "-lm", "-lpthread",
               "-ldl"] + extra_flags
    try:
        proc = subprocess.run(gcc_cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None, None, "link timed out"
    if proc.returncode != 0:
        return None, None, f"link failed: {proc.stderr[:200]}"

    binary_size = os.path.getsize(binary)
    runtime = _run_benchmark(name, binary, tmp_dir)
    return binary_size, runtime, None


def _load_baseline(build_dir):
    """Load or compute baseline (default LLVM) measurements."""
    if _BASELINE_FILE.exists():
        with open(_BASELINE_FILE) as f:
            return json.load(f)

    opt_path = os.path.join(build_dir, "bin", "opt")
    llc_path = os.path.join(build_dir, "bin", "llc")
    benchmarks = _find_benchmarks()

    if not benchmarks:
        return {}

    baseline = {}
    with tempfile.TemporaryDirectory(prefix="regalloc_baseline_") as tmp_dir:
        for bc in benchmarks:
            print(f"  Baseline: {bc.stem}...", end=" ", flush=True)
            binary_size, runtime, err = _compile_benchmark(
                bc, opt_path, llc_path, use_evolved=False, tmp_dir=tmp_dir
            )
            if err:
                print(f"ERROR: {err}")
            elif binary_size is not None:
                baseline[bc.name] = {
                    "binary_size": binary_size,
                    "runtime": runtime,
                }
                print(f"binary={binary_size}, runtime={runtime}")
            else:
                print("SKIP")

    try:
        os.makedirs(_EVAL_DIR, exist_ok=True)
        with open(_BASELINE_FILE, "w") as f:
            json.dump(baseline, f, indent=2)
        print(f"  Baseline saved to {_BASELINE_FILE}")
    except OSError:
        pass

    return baseline


def _eval_benchmarks(benchmarks, opt_path, llc_path, baseline, tmp_dir,
                     extra_llc_flags=None):
    """Compile and score a set of benchmarks.

    Returns (score, details_dict).
    Score = weighted: 5 * speedup_pct + 1 * binary_reduction_pct
    """
    total_binary = 0
    baseline_total_binary = 0
    speedups = []
    details = {}

    for bc in benchmarks:
        binary_size, runtime, err = _compile_benchmark(
            bc, opt_path, llc_path, use_evolved=True, tmp_dir=tmp_dir,
            extra_llc_flags=extra_llc_flags,
        )
        bl = baseline.get(bc.name, {})
        info = {"binary_size": binary_size, "runtime": runtime}
        if err:
            info["error"] = err

        if binary_size is not None:
            total_binary += binary_size
            bl_binary = bl.get("binary_size", binary_size)
            baseline_total_binary += bl_binary

        bl_rt = bl.get("runtime")
        if runtime is not None and bl_rt and bl_rt > 0:
            speedups.append(bl_rt / runtime)

        details[bc.name] = info

    binary_pct = 0.0
    if baseline_total_binary > 0:
        binary_pct = round(
            100.0 * (baseline_total_binary - total_binary) / baseline_total_binary, 4
        )

    avg_speedup = 0.0
    if speedups:
        avg_speedup = sum(speedups) / len(speedups)

    # Score: performance-weighted (regalloc affects runtime more than size)
    speedup_pct = (avg_speedup - 1.0) * 100 if avg_speedup > 0 else 0
    score = round(5.0 * speedup_pct + 1.0 * binary_pct, 4)

    return score, details


def _optuna_tune(opt_path, llc_path, benchmarks, baseline, n_trials,
                 hyperparams):
    """Run Optuna trials on a subset of benchmarks to tune hyperparams."""
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    subset_names = set(_OPTUNA_SUBSET)
    subset_bcs = [bc for bc in benchmarks if bc.stem in subset_names]
    if not subset_bcs:
        subset_bcs = benchmarks[:3]

    def objective(trial):
        flags = []
        for flag_name, type_str, lo, hi in hyperparams:
            if type_str == "int":
                val = trial.suggest_int(flag_name, lo, hi)
            else:
                val = trial.suggest_float(flag_name, float(lo), float(hi))
            flags.append(f"-{flag_name}={val}")

        with tempfile.TemporaryDirectory(prefix="optuna_trial_") as tmp_dir:
            score, _ = _eval_benchmarks(
                subset_bcs, opt_path, llc_path, baseline, tmp_dir,
                extra_llc_flags=flags,
            )
        return score

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials)

    best_params = study.best_params
    best_flags = [f"-{k}={v}" for k, v in best_params.items()]
    return study.best_value, best_params, best_flags


def evaluate(program_path: str) -> dict:
    """Evaluate an evolved LLVM register allocation priority function.

    Score = weighted combination of runtime speedup and binary size reduction.
    Register allocation primarily affects runtime (spilling, register pressure)
    but can also affect code size.
    """
    llvm_src = os.environ.get("LLVM_SRC_PATH", "")
    build_dir = os.environ.get("EVOLVE_BUILD_DIR",
                               os.environ.get("BUILD_LLVM_DIR", ""))

    if not llvm_src or not build_dir:
        return {
            "combined_score": 0.0,
            "error": "LLVM_SRC_PATH and EVOLVE_BUILD_DIR must be set",
        }

    target_file = os.environ.get(
        "EVOLVE_TARGET_FILE", "llvm/lib/CodeGen/EvolvedRegAllocPriority.cpp"
    )
    dest = os.path.join(llvm_src, target_file)
    backup = dest + ".evolve.bak"

    result = {
        "combined_score": 0.0,
        "build_success": False,
        "build_time": 0.0,
        "total_binary_size": 0,
        "binary_reduction_pct": 0.0,
        "avg_speedup": 0.0,
        "benchmark_details": {},
        "error": None,
    }

    # 1. Patch evolved priority function into LLVM source
    try:
        if os.path.exists(dest):
            shutil.copy2(dest, backup)
        shutil.copy2(program_path, dest)
    except OSError as e:
        result["error"] = f"Patch failed: {e}"
        return result

    try:
        # 2. Rebuild opt + llc incrementally
        ninja = os.environ.get("NINJA", shutil.which("ninja") or "ninja")
        build_targets = os.environ.get(
            "EVOLVE_BUILD_TARGETS", "bin/opt bin/llc"
        ).split()
        cmd = [ninja, "-C", build_dir] + build_targets

        start = time.time()
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        result["build_time"] = round(time.time() - start, 2)
        result["build_success"] = proc.returncode == 0

        if proc.returncode != 0:
            lines = proc.stderr.strip().split("\n")
            err_lines = [l for l in lines if "error:" in l.lower()]
            result["error"] = ("\n".join(err_lines[:10]) if err_lines
                               else "\n".join(lines[-10:]))
            return result

        # 3. Load baseline measurements
        baseline = _load_baseline(build_dir)

        # 4. Set up evaluation
        opt_path = os.path.join(build_dir, "bin", "opt")
        llc_path = os.path.join(build_dir, "bin", "llc")
        benchmarks = _find_benchmarks()

        if not benchmarks:
            result["error"] = "No benchmark .bc files found in testsuite/"
            return result

        # 4a. Optuna inner-loop
        with open(program_path) as f:
            source_code = f.read()
        hyperparams = _extract_hyperparams(source_code)

        extra_flags = None
        if hyperparams and _OPTUNA_TRIALS > 0:
            print(f"  Optuna: tuning {len(hyperparams)} hyperparams "
                  f"({_OPTUNA_TRIALS} trials)...")
            tune_start = time.time()
            best_sub, best_params, extra_flags = _optuna_tune(
                opt_path, llc_path, benchmarks, baseline,
                n_trials=_OPTUNA_TRIALS, hyperparams=hyperparams,
            )
            result["optuna_trials"] = _OPTUNA_TRIALS
            result["optuna_subset_score"] = best_sub
            result["tuned_params"] = best_params
            result["tune_time"] = round(time.time() - tune_start, 2)
        elif hyperparams:
            result["optuna_trials"] = 0
            result["tuned_params"] = {}

        # 4b. Final evaluation on all benchmarks
        total_binary = 0
        baseline_total_binary = 0
        speedups = []
        bench_errors = []

        with tempfile.TemporaryDirectory(prefix="regalloc_eval_") as tmp_dir:
            for bc in benchmarks:
                binary_size, runtime, err = _compile_benchmark(
                    bc, opt_path, llc_path, use_evolved=True, tmp_dir=tmp_dir,
                    extra_llc_flags=extra_flags,
                )
                bench_info = {"binary_size": binary_size, "runtime": runtime}

                if err:
                    bench_info["error"] = err
                    bench_errors.append(f"{bc.name}: {err}")

                bl = baseline.get(bc.name, {})

                if binary_size is not None:
                    total_binary += binary_size
                    bl_binary = bl.get("binary_size", binary_size)
                    baseline_total_binary += bl_binary
                    if bl_binary > 0:
                        bench_info["binary_reduction_pct"] = round(
                            100.0 * (bl_binary - binary_size) / bl_binary, 4
                        )

                bl_rt = bl.get("runtime")
                if runtime is not None and bl_rt and bl_rt > 0:
                    bench_info["speedup"] = round(bl_rt / runtime, 4)
                    speedups.append(bl_rt / runtime)

                result["benchmark_details"][bc.name] = bench_info

        result["total_binary_size"] = total_binary

        if baseline_total_binary > 0:
            result["binary_reduction_pct"] = round(
                100.0 * (baseline_total_binary - total_binary)
                / baseline_total_binary, 4
            )

        if speedups:
            result["avg_speedup"] = round(sum(speedups) / len(speedups), 4)

        # Score: performance-weighted (regalloc affects runtime more)
        binary_score = result["binary_reduction_pct"]
        speedup_pct = ((result["avg_speedup"] - 1.0) * 100
                       if result["avg_speedup"] > 0 else 0)
        result["combined_score"] = round(5.0 * speedup_pct + binary_score, 4)

        if bench_errors:
            result["error"] = "; ".join(bench_errors)

    except subprocess.TimeoutExpired:
        result["error"] = "Build timed out (600s)"
    finally:
        if os.path.exists(backup):
            shutil.move(backup, dest)

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <program_path>", file=sys.stderr)
        sys.exit(1)
    metrics = evaluate(sys.argv[1])
    print(json.dumps(metrics, indent=2))
