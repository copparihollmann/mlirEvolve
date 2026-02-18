"""Evaluator for LLVM inlining heuristic evolution.

Called by OpenEvolve as: python evaluate.py <program_path>

Pipeline:
1. Patch evolved C++ heuristic into LLVM source tree
2. Rebuild opt incrementally (ninja)
3. For each benchmark .bc file:
   a. opt -O2 -use-evolved-inline-cost bench.bc -o bench_opt.bc
   b. llc -O2 -filetype=obj -relocation-model=pic bench_opt.bc -o bench.o
   c. gcc bench.o -o bench -lm -lpthread -ldl
   d. Measure .text section size (llvm-size or size)
   e. Run benchmark and measure wall-clock time
4. Score = weighted combination of size reduction + speedup vs baseline
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


# Discover benchmark .bc files relative to this evaluator
_EVAL_DIR = Path(__file__).resolve().parent
_BENCH_DIR = _EVAL_DIR / "benchmarks"

# Baseline cache file (stores default LLVM text sizes and runtimes)
_BASELINE_FILE = _BENCH_DIR / "baseline.json"

# Per-benchmark timeout for opt/llc (seconds). Aggressive heuristics can
# cause exponential inlining on large TUs, so we cap per-benchmark.
_OPT_TIMEOUT = int(os.environ.get("EVOLVE_OPT_TIMEOUT", "120"))


def _find_benchmarks():
    """Find all .bc files in the benchmarks directory."""
    if not _BENCH_DIR.exists():
        return []
    return sorted(_BENCH_DIR.glob("*.bc"))


def _get_text_size(obj_path):
    """Get .text section size from an object file using size(1)."""
    try:
        proc = subprocess.run(
            ["size", str(obj_path)],
            capture_output=True, text=True, timeout=10
        )
        if proc.returncode == 0:
            # size output: text  data  bss  dec  hex  filename
            lines = proc.stdout.strip().split("\n")
            if len(lines) >= 2:
                return int(lines[1].split()[0])
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        pass
    # Fallback: file size
    return os.path.getsize(obj_path) if os.path.exists(obj_path) else 0


def _run_benchmark(binary_path, timeout_sec=30):
    """Run a benchmark binary and return wall-clock time in seconds."""
    try:
        start = time.time()
        proc = subprocess.run(
            [str(binary_path)],
            capture_output=True, text=True, timeout=timeout_sec
        )
        elapsed = time.time() - start
        if proc.returncode == 0:
            return elapsed
    except subprocess.TimeoutExpired:
        pass
    return None


def _compile_benchmark(bc_path, opt_path, llc_path, use_evolved, tmp_dir):
    """Compile a .bc file through opt -> llc -> gcc.

    Returns (text_size, runtime, error_string).
    Handles per-benchmark timeouts gracefully.
    """
    name = bc_path.stem
    opt_bc = os.path.join(tmp_dir, f"{name}_opt.bc")
    obj_file = os.path.join(tmp_dir, f"{name}.o")
    binary = os.path.join(tmp_dir, name)

    # opt pass
    opt_cmd = [str(opt_path), "-O2"]
    if use_evolved:
        opt_cmd.append("-use-evolved-inline-cost")
    opt_cmd += [str(bc_path), "-o", opt_bc]

    try:
        proc = subprocess.run(opt_cmd, capture_output=True, text=True, timeout=_OPT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, None, f"opt timed out ({_OPT_TIMEOUT}s)"
    if proc.returncode != 0:
        return None, None, proc.stderr[:500]

    # llc: bitcode -> object
    llc_cmd = [str(llc_path), "-O2", "-filetype=obj", "-relocation-model=pic",
               opt_bc, "-o", obj_file]
    try:
        proc = subprocess.run(llc_cmd, capture_output=True, text=True, timeout=_OPT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, None, f"llc timed out ({_OPT_TIMEOUT}s)"
    if proc.returncode != 0:
        return None, None, proc.stderr[:500]

    text_size = _get_text_size(obj_file)

    # Link to binary
    gcc_cmd = ["gcc", obj_file, "-o", binary, "-lm", "-lpthread", "-ldl"]
    try:
        proc = subprocess.run(gcc_cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return text_size, None, None
    if proc.returncode != 0:
        # Still return text_size even if linking fails
        return text_size, None, None

    # Run benchmark
    runtime = _run_benchmark(binary)
    return text_size, runtime, None


def _load_baseline(build_dir):
    """Load or compute baseline (default LLVM) measurements."""
    if _BASELINE_FILE.exists():
        with open(_BASELINE_FILE) as f:
            return json.load(f)

    # Compute baseline with default opt (no evolved flag)
    opt_path = os.path.join(build_dir, "bin", "opt")
    llc_path = os.path.join(build_dir, "bin", "llc")
    benchmarks = _find_benchmarks()

    if not benchmarks:
        return {}

    baseline = {}
    with tempfile.TemporaryDirectory(prefix="evolve_baseline_") as tmp_dir:
        for bc in benchmarks:
            text_size, runtime, _ = _compile_benchmark(
                bc, opt_path, llc_path, use_evolved=False, tmp_dir=tmp_dir
            )
            if text_size is not None:
                baseline[bc.name] = {
                    "text_size": text_size,
                    "runtime": runtime,
                }

    # Cache to disk
    try:
        with open(_BASELINE_FILE, "w") as f:
            json.dump(baseline, f, indent=2)
    except OSError:
        pass

    return baseline


def evaluate(program_path: str) -> dict:
    """Evaluate an evolved LLVM inlining heuristic.

    Pipeline: patch -> rebuild opt -> compile benchmarks -> measure size + perf.
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
        "EVOLVE_TARGET_FILE", "llvm/lib/Analysis/EvolvedInlineCost.cpp"
    )
    dest = os.path.join(llvm_src, target_file)
    backup = dest + ".evolve.bak"

    result = {
        "combined_score": 0.0,
        "build_success": False,
        "build_time": 0.0,
        "total_text_size": 0,
        "size_reduction_pct": 0.0,
        "avg_speedup": 0.0,
        "benchmark_details": {},
        "error": None,
    }

    # 1. Patch evolved heuristic into LLVM source
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
            result["error"] = "\n".join(err_lines[:10]) if err_lines else "\n".join(lines[-10:])
            return result

        # 3. Load baseline measurements
        baseline = _load_baseline(build_dir)

        # 4. Compile and measure each benchmark with evolved heuristic
        opt_path = os.path.join(build_dir, "bin", "opt")
        llc_path = os.path.join(build_dir, "bin", "llc")
        benchmarks = _find_benchmarks()

        if not benchmarks:
            result["error"] = "No benchmark .bc files found"
            result["combined_score"] = 0.0
            return result

        total_text = 0
        baseline_total_text = 0
        speedups = []
        bench_errors = []

        with tempfile.TemporaryDirectory(prefix="evolve_eval_") as tmp_dir:
            for bc in benchmarks:
                text_size, runtime, err = _compile_benchmark(
                    bc, opt_path, llc_path, use_evolved=True, tmp_dir=tmp_dir
                )
                bench_info = {"text_size": text_size, "runtime": runtime}

                if err:
                    bench_info["error"] = err
                    bench_errors.append(f"{bc.name}: {err}")

                if text_size is not None:
                    total_text += text_size
                    bl = baseline.get(bc.name, {})
                    bl_text = bl.get("text_size", text_size)
                    baseline_total_text += bl_text

                    if bl_text > 0:
                        bench_info["size_reduction_pct"] = round(
                            100.0 * (bl_text - text_size) / bl_text, 4
                        )

                    bl_rt = bl.get("runtime")
                    if runtime is not None and bl_rt and bl_rt > 0:
                        bench_info["speedup"] = round(bl_rt / runtime, 4)
                        speedups.append(bl_rt / runtime)

                result["benchmark_details"][bc.name] = bench_info

        result["total_text_size"] = total_text

        # 5. Compute aggregate scores
        if baseline_total_text > 0:
            result["size_reduction_pct"] = round(
                100.0 * (baseline_total_text - total_text) / baseline_total_text, 4
            )

        if speedups:
            result["avg_speedup"] = round(sum(speedups) / len(speedups), 4)

        # Combined score: size reduction (%) + speedup bonus
        # Magellan optimizes size primarily; speedup is secondary
        size_score = result["size_reduction_pct"]  # Can be negative
        perf_score = (result["avg_speedup"] - 1.0) * 10 if result["avg_speedup"] > 0 else 0

        # Combined: higher is better. 0 = same as baseline.
        result["combined_score"] = round(size_score + perf_score, 4)

        if bench_errors:
            result["error"] = "; ".join(bench_errors)

    except subprocess.TimeoutExpired:
        result["error"] = "Build timed out (600s)"
    finally:
        # Restore original file
        if os.path.exists(backup):
            shutil.move(backup, dest)

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <program_path>", file=sys.stderr)
        sys.exit(1)
    metrics = evaluate(sys.argv[1])
    print(json.dumps(metrics, indent=2))
