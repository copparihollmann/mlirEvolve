"""Shared benchmark infrastructure for LLVM evolution tasks.

Provides common utilities for evaluating evolved LLVM heuristics against
CTMark benchmarks: config management, benchmark discovery, compilation
pipeline (opt -> llc -> gcc), baseline caching, scoring, and Optuna tuning.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

try:
    import optuna

    _HAS_OPTUNA = True
except ImportError:
    _HAS_OPTUNA = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Benchmarks to exclude (clamav segfaults with aggressive inlining;
# 7zip fails to link — missing symbols from multi-source build)
EXCLUDED = {"clamav", "7zip"}

# Extra linker flags per benchmark (C++ benchmarks need -lstdc++)
EXTRA_LINK_FLAGS = {
    "7zip": ["-lstdc++", "-pthread"],
    "bullet": ["-lstdc++"],
    "kimwitu": ["-lstdc++"],
    "tramp3d-v4": ["-lstdc++"],
}

# Per-benchmark runtime configs (best-effort measurement).
# data_files: specific files to copy from data/<bench>/ to run dir
# data_subdir: copy entire data/<bench>/ contents to run dir
# stdin_file: file in data/<bench>/ to redirect as stdin
# args: command line arguments
BENCH_RUN_CONFIGS = {
    "7zip": {
        "args": ["b"],
        "timeout": 60,
    },
    "bullet": {
        "data_files": ["landscape.mdl", "Taru.mdl"],
        "timeout": 30,
    },
    "consumer-typeset": {
        "args": ["-x", "-I", "data/include", "-D", "data/data",
                 "-F", "data/font", "-C", "data/maps", "-H", "data/hyph",
                 "large.lout"],
        "data_subdir": True,
        "timeout": 60,
    },
    "kimwitu": {
        "args": ["-f", "test", "-o", "-v", "-s", "kcc",
                 "inputs/f3.k", "inputs/f2.k", "inputs/f1.k"],
        "data_subdir": True,
        "timeout": 30,
    },
    "lencod": {
        "args": ["-d", "data/encoder_small.cfg",
                 "-p", "InputFile=data/foreman_part_qcif_444.yuv",
                 "-p", "LeakyBucketRateFile=data/leakybucketrate.cfg",
                 "-p", "QmatrixFile=data/q_matrix.cfg"],
        "data_subdir": True,
        "timeout": 120,
    },
    "mafft": {
        "args": ["-b", "62", "-g", "0.100", "-f", "2.00", "-h", "0.100", "-L"],
        "stdin_file": "pyruvate_decarboxylase.fasta",
        "timeout": 60,
    },
    "spass": {
        "args": ["problem.dfg"],
        "data_files": ["problem.dfg"],
        "timeout": 60,
    },
    "sqlite3": {
        "args": ["-init", "sqlite3rc", ":memory:"],
        "stdin_file": "commands",
        "data_files": ["sqlite3rc"],
        "timeout": 60,
    },
    "tramp3d-v4": {
        "args": ["--cartvis", "1.0", "0.0", "--rhomin", "1e-8",
                 "-n", "4", "--domain", "32", "32", "32"],
        "timeout": 120,
    },
}

# Regex for [hyperparam] annotations in evolved C++ code
HYPERPARAM_RE = re.compile(
    r"//\s*\[hyperparam\]:\s*([\w-]+),\s*(\w+),\s*(-?\d+),\s*(-?\d+)"
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class EvalConfig:
    """Programmatic config for LLVM benchmark evaluation.

    All paths can be set via constructor args or fall back to environment
    variables via ``from_env()``.
    """

    llvm_src: str = ""          # LLVM source tree root
    build_dir: str = ""         # LLVM build directory
    target_file: str = ""       # e.g. "llvm/lib/Analysis/EvolvedInlineCost.cpp"
    testsuite_dir: str = ""     # Path to *.bc files
    data_dir: str = ""          # Path to runtime data
    baseline_file: str = ""     # Path to baseline cache JSON
    opt_timeout: int = 120      # Per-benchmark timeout for opt/llc (seconds)
    optuna_trials: int = 20     # Optuna trials (0 = disable)
    optuna_subset: list = field(default_factory=lambda: ["sqlite3", "spass", "tramp3d-v4"])
    ninja: str = ""
    build_targets: str = "bin/opt bin/llc"

    def __post_init__(self):
        if not self.testsuite_dir:
            tasks_dir = Path(__file__).resolve().parent
            self.testsuite_dir = str(
                tasks_dir / "llvm_inlining" / "benchmarks" / "testsuite"
            )
        if not self.data_dir:
            self.data_dir = str(Path(self.testsuite_dir) / "data")
        if not self.baseline_file:
            self.baseline_file = str(Path(self.testsuite_dir) / "baseline.json")
        if not self.ninja:
            self.ninja = os.environ.get(
                "NINJA", shutil.which("ninja") or "ninja"
            )

    @classmethod
    def from_env(cls, target_file: str, **overrides) -> "EvalConfig":
        """Build config from environment variables with keyword overrides."""
        defaults = {
            "llvm_src": os.environ.get("LLVM_SRC_PATH", ""),
            "build_dir": os.environ.get(
                "EVOLVE_BUILD_DIR", os.environ.get("BUILD_LLVM_DIR", "")
            ),
            "target_file": os.environ.get("EVOLVE_TARGET_FILE", target_file),
            "opt_timeout": int(os.environ.get("EVOLVE_OPT_TIMEOUT", "120")),
            "optuna_trials": int(os.environ.get("EVOLVE_OPTUNA_TRIALS", "20")),
        }
        defaults.update(overrides)
        return cls(**defaults)

    @staticmethod
    def add_arguments(parser) -> None:
        """Add EvalConfig flags to an argparse parser."""
        parser.add_argument("--llvm-src", default=None,
                            help="LLVM source tree root (env: LLVM_SRC_PATH)")
        parser.add_argument("--build-dir", default=None,
                            help="LLVM build directory (env: EVOLVE_BUILD_DIR)")
        parser.add_argument("--opt-timeout", type=int, default=None,
                            help="Per-benchmark timeout in seconds (default: 120)")
        parser.add_argument("--optuna-trials", type=int, default=None,
                            help="Optuna inner-loop trials, 0=disable (default: 20)")

    @classmethod
    def from_args(cls, args, target_file: str, **overrides) -> "EvalConfig":
        """Build config from parsed CLI args, falling back to env vars.

        Usage::

            parser = argparse.ArgumentParser()
            parser.add_argument("program_path")
            EvalConfig.add_arguments(parser)
            args = parser.parse_args()
            config = EvalConfig.from_args(args, "llvm/lib/Analysis/EvolvedInlineCost.cpp")
        """
        cli = {}
        if getattr(args, "llvm_src", None):
            cli["llvm_src"] = args.llvm_src
        if getattr(args, "build_dir", None):
            cli["build_dir"] = args.build_dir
        if getattr(args, "opt_timeout", None) is not None:
            cli["opt_timeout"] = args.opt_timeout
        if getattr(args, "optuna_trials", None) is not None:
            cli["optuna_trials"] = args.optuna_trials
        cli.update(overrides)
        return cls.from_env(target_file, **cli)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_hyperparams(code: str):
    """Parse ``// [hyperparam]: name, type, min, max`` comments from C++ source.

    Returns list of ``(flag_name, type_str, min_val, max_val)`` tuples.
    """
    return [
        (m.group(1), m.group(2), int(m.group(3)), int(m.group(4)))
        for m in HYPERPARAM_RE.finditer(code)
    ]


def find_benchmarks(testsuite_dir: Path):
    """Find CTMark .bc files in *testsuite_dir*, excluding problematic ones."""
    if not testsuite_dir.exists():
        return []
    return sorted(
        bc for bc in testsuite_dir.glob("*.bc")
        if bc.stem not in EXCLUDED
    )


def get_text_size(obj_path: str) -> int:
    """Get .text section size from an object file using ``size(1)``."""
    try:
        proc = subprocess.run(
            ["size", str(obj_path)],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0:
            lines = proc.stdout.strip().split("\n")
            if len(lines) >= 2:
                return int(lines[1].split()[0])
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        pass
    return os.path.getsize(obj_path) if os.path.exists(obj_path) else 0


# ---------------------------------------------------------------------------
# Benchmark execution
# ---------------------------------------------------------------------------

def run_benchmark(name: str, binary_path: str, tmp_dir: str, data_dir: str,
                  num_runs: int = 5):
    """Run a benchmark with reference inputs; return median wall-clock seconds or None."""
    config = BENCH_RUN_CONFIGS.get(name)
    if not config:
        return None

    run_dir = os.path.join(tmp_dir, f"{name}_run")
    os.makedirs(run_dir, exist_ok=True)
    run_binary = os.path.join(run_dir, name)
    shutil.copy2(binary_path, run_binary)
    os.chmod(run_binary, 0o755)

    bench_data = Path(data_dir) / name

    # Copy data files/dirs
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

    cmd = [run_binary] + config.get("args", [])
    timeout = config.get("timeout", 30)
    stdin_file = None
    if config.get("stdin_file") and bench_data.exists():
        stdin_file = bench_data / config["stdin_file"]

    timings = []
    for _ in range(num_runs):
        stdin_fh = None
        try:
            if stdin_file and stdin_file.exists():
                stdin_fh = open(str(stdin_file), "r")
            start = time.time()
            proc = subprocess.run(
                cmd, capture_output=True, timeout=timeout,
                cwd=run_dir, stdin=stdin_fh,
            )
            elapsed = time.time() - start
            if proc.returncode == 0:
                timings.append(elapsed)
        except subprocess.TimeoutExpired:
            pass
        finally:
            if stdin_fh:
                stdin_fh.close()

    if not timings:
        return None
    timings.sort()
    return timings[len(timings) // 2]


def compile_benchmark(bc_path, opt_path, llc_path, tmp_dir, data_dir,
                      evolved_opt_flags=None, evolved_llc_flags=None,
                      opt_timeout=120):
    """Compile a .bc file through ``opt -> llc -> gcc``.

    Callers pass evolved flags to *opt*, *llc*, or both:

    - Inlining: ``evolved_opt_flags=["-use-evolved-inline-cost", ...]``
    - RegAlloc: ``evolved_llc_flags=["-use-evolved-regalloc-priority", ...]``

    Returns ``(text_size, binary_size, runtime, error)`` 4-tuple.
    """
    name = bc_path.stem
    opt_bc = os.path.join(tmp_dir, f"{name}_opt.bc")
    obj_file = os.path.join(tmp_dir, f"{name}.o")
    binary = os.path.join(tmp_dir, name)

    # opt pass
    opt_cmd = [str(opt_path), "-O2"]
    if evolved_opt_flags:
        opt_cmd.extend(evolved_opt_flags)
    opt_cmd += [str(bc_path), "-o", opt_bc]

    try:
        proc = subprocess.run(
            opt_cmd, capture_output=True, text=True, timeout=opt_timeout,
        )
    except subprocess.TimeoutExpired:
        return None, None, None, f"opt timed out ({opt_timeout}s)"
    if proc.returncode != 0:
        return None, None, None, proc.stderr[:500]

    # llc: bitcode -> object
    llc_cmd = [str(llc_path), "-O2", "-filetype=obj", "-relocation-model=pic"]
    if evolved_llc_flags:
        llc_cmd.extend(evolved_llc_flags)
    llc_cmd += [opt_bc, "-o", obj_file]

    try:
        proc = subprocess.run(
            llc_cmd, capture_output=True, text=True, timeout=opt_timeout,
        )
    except subprocess.TimeoutExpired:
        return None, None, None, f"llc timed out ({opt_timeout}s)"
    if proc.returncode != 0:
        return None, None, None, proc.stderr[:500]

    text_size = get_text_size(obj_file)

    # Link to binary with per-benchmark flags
    extra_flags = EXTRA_LINK_FLAGS.get(name, [])
    gcc_cmd = ["gcc", obj_file, "-o", binary, "-lm", "-lpthread", "-ldl"] + extra_flags
    try:
        proc = subprocess.run(
            gcc_cmd, capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        return text_size, None, None, "link timed out"
    if proc.returncode != 0:
        return text_size, None, None, f"link failed: {proc.stderr[:200]}"

    binary_size = os.path.getsize(binary)
    runtime = run_benchmark(name, binary, tmp_dir, data_dir)
    return text_size, binary_size, runtime, None


# ---------------------------------------------------------------------------
# Source patching
# ---------------------------------------------------------------------------

def patch_source(program_path: str, config: EvalConfig):
    """Copy evolved source into the LLVM tree. Returns ``(dest, backup)``."""
    dest = os.path.join(config.llvm_src, config.target_file)
    backup = dest + ".evolve.bak"
    if os.path.exists(dest):
        shutil.copy2(dest, backup)
    shutil.copy2(program_path, dest)
    return dest, backup


def restore_source(dest: str, backup: str):
    """Restore the original LLVM source from *backup*."""
    if os.path.exists(backup):
        shutil.move(backup, dest)


# ---------------------------------------------------------------------------
# LLVM build
# ---------------------------------------------------------------------------

def build_llvm(config: EvalConfig):
    """Incremental ninja build. Returns ``(success, build_time, error)``."""
    build_targets = config.build_targets.split()
    cmd = [config.ninja, "-C", config.build_dir] + build_targets

    start = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    build_time = round(time.time() - start, 2)

    if proc.returncode != 0:
        lines = proc.stderr.strip().split("\n")
        err_lines = [l for l in lines if "error:" in l.lower()]
        error = "\n".join(err_lines[:10]) if err_lines else "\n".join(lines[-10:])
        return False, build_time, error
    return True, build_time, None


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------

def load_baseline(config: EvalConfig):
    """Load or compute baseline (default LLVM, no evolved flags) measurements."""
    baseline_path = Path(config.baseline_file)
    if baseline_path.exists():
        with open(baseline_path) as f:
            return json.load(f)

    opt_path = os.path.join(config.build_dir, "bin", "opt")
    llc_path = os.path.join(config.build_dir, "bin", "llc")
    benchmarks = find_benchmarks(Path(config.testsuite_dir))

    if not benchmarks:
        return {}

    baseline = {}
    with tempfile.TemporaryDirectory(prefix="evolve_baseline_") as tmp_dir:
        for bc in benchmarks:
            print(f"  Baseline: {bc.stem}...", end=" ", flush=True)
            text_size, binary_size, runtime, err = compile_benchmark(
                bc, opt_path, llc_path, tmp_dir, config.data_dir,
                opt_timeout=config.opt_timeout,
            )
            if err:
                print(f"ERROR: {err}")
            elif text_size is not None:
                entry = {"text_size": text_size, "runtime": runtime}
                if binary_size is not None:
                    entry["binary_size"] = binary_size
                baseline[bc.name] = entry
                print(f"text={text_size}, binary={binary_size}, runtime={runtime}")
            else:
                print("SKIP (no text size)")

    try:
        os.makedirs(baseline_path.parent, exist_ok=True)
        with open(baseline_path, "w") as f:
            json.dump(baseline, f, indent=2)
        print(f"  Baseline saved to {baseline_path}")
    except OSError:
        pass

    return baseline


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def eval_benchmarks(benchmarks, opt_path, llc_path, baseline, tmp_dir,
                    data_dir, score_fn, evolved_opt_flags=None,
                    evolved_llc_flags=None, opt_timeout=120):
    """Compile and score benchmarks.

    *score_fn(total_binary, baseline_total_binary, speedups)* computes the
    task-specific score from aggregate measurements.

    Returns ``(score, result_dict)`` where *result_dict* contains per-benchmark
    details plus aggregate totals.
    """
    total_binary = 0
    baseline_total_binary = 0
    total_text = 0
    baseline_total_text = 0
    speedups = []
    details = {}
    errors = []

    for bc in benchmarks:
        text_size, binary_size, runtime, err = compile_benchmark(
            bc, opt_path, llc_path, tmp_dir, data_dir,
            evolved_opt_flags=evolved_opt_flags,
            evolved_llc_flags=evolved_llc_flags,
            opt_timeout=opt_timeout,
        )
        bl = baseline.get(bc.name, {})
        info = {
            "text_size": text_size,
            "binary_size": binary_size,
            "runtime": runtime,
        }

        if err:
            info["error"] = err
            errors.append(f"{bc.name}: {err}")

        if text_size is not None:
            total_text += text_size
            bl_text = bl.get("text_size", text_size)
            baseline_total_text += bl_text
            if bl_text > 0:
                info["text_reduction_pct"] = round(
                    100.0 * (bl_text - text_size) / bl_text, 4
                )

        if binary_size is not None:
            total_binary += binary_size
            bl_binary = bl.get("binary_size", binary_size)
            baseline_total_binary += bl_binary
            if bl_binary > 0:
                info["binary_reduction_pct"] = round(
                    100.0 * (bl_binary - binary_size) / bl_binary, 4
                )

        bl_rt = bl.get("runtime")
        if runtime is not None and bl_rt and bl_rt > 0:
            info["speedup"] = round(bl_rt / runtime, 4)
            speedups.append(bl_rt / runtime)

        details[bc.name] = info

    score = score_fn(total_binary, baseline_total_binary, speedups)

    result = {
        "total_binary": total_binary,
        "baseline_total_binary": baseline_total_binary,
        "total_text": total_text,
        "baseline_total_text": baseline_total_text,
        "speedups": speedups,
        "details": details,
        "errors": errors,
    }
    return score, result


# ---------------------------------------------------------------------------
# Optuna tuning
# ---------------------------------------------------------------------------

def optuna_tune(opt_path, llc_path, benchmarks, baseline, n_trials,
                hyperparams, data_dir, score_fn, opt_timeout=120,
                optuna_subset=None, base_opt_flags=None,
                base_llc_flags=None, flag_target="opt"):
    """Run Optuna trials on a benchmark subset to tune ``[hyperparam]`` knobs.

    *flag_target*: ``"opt"`` or ``"llc"`` — where hyperparam flags are injected.
    *base_opt_flags* / *base_llc_flags*: fixed evolved flags always applied.

    Returns ``(best_score, best_params_dict, best_flags_list)``.
    """
    if not _HAS_OPTUNA:
        print("  Optuna not installed — skipping hyperparameter tuning")
        return 0.0, {}, []

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    subset_names = set(optuna_subset or ["sqlite3", "spass", "tramp3d-v4"])
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

        opt_flags = list(base_opt_flags or [])
        llc_flags = list(base_llc_flags or [])
        if flag_target == "opt":
            opt_flags.extend(flags)
        else:
            llc_flags.extend(flags)

        with tempfile.TemporaryDirectory(prefix="optuna_trial_") as trial_dir:
            score, _ = eval_benchmarks(
                subset_bcs, opt_path, llc_path, baseline, trial_dir,
                data_dir, score_fn,
                evolved_opt_flags=opt_flags or None,
                evolved_llc_flags=llc_flags or None,
                opt_timeout=opt_timeout,
            )
        return score

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials)

    best_params = study.best_params
    best_flags = [f"-{k}={v}" for k, v in best_params.items()]
    return study.best_value, best_params, best_flags
