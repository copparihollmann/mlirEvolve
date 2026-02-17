"""Standalone evaluator for LLVM inlining heuristic evolution.

Called by OpenEvolve (or ShinkaEvolve) as:
    python evaluate.py <program_path>

Must define an `evaluate(program_path)` function that returns a dict
with at least a "score" key.

The evaluator:
1. Patches the evolved C++ heuristic into the LLVM source tree
2. Rebuilds LLVM incrementally (ninja + ccache)
3. Measures binary size of `opt` (or a benchmark binary)
4. Returns score = 1e6 / binary_size (higher is better)
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def evaluate(program_path: str) -> dict:
    """Evaluate an evolved LLVM inlining heuristic.

    Args:
        program_path: Path to the evolved .cpp file with the heuristic.

    Returns:
        Dict with keys: score, binary_size, build_success, build_time, error.
    """
    llvm_src = os.environ.get("LLVM_SRC_PATH", "")
    build_dir = os.environ.get("EVOLVE_BUILD_DIR",
                               os.environ.get("BUILD_LLVM_DIR", ""))

    if not llvm_src or not build_dir:
        return {
            "score": 0.0,
            "error": "LLVM_SRC_PATH and EVOLVE_BUILD_DIR (or BUILD_LLVM_DIR) must be set",
        }

    target_file = os.environ.get(
        "EVOLVE_TARGET_FILE", "llvm/lib/Analysis/InlineAdvisor.cpp"
    )
    dest = os.path.join(llvm_src, target_file)
    backup = dest + ".evolve.bak"

    result = {
        "score": 0.0,
        "build_success": False,
        "build_time": 0.0,
        "binary_size": 0,
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
        # 2. Rebuild LLVM incrementally
        build_targets = os.environ.get("EVOLVE_BUILD_TARGETS", "bin/opt").split()
        cmd = ["ninja", "-C", build_dir] + build_targets

        start = time.time()
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        result["build_time"] = round(time.time() - start, 2)
        result["build_success"] = proc.returncode == 0

        if proc.returncode != 0:
            # Extract error lines
            lines = proc.stderr.strip().split("\n")
            err_lines = [l for l in lines if "error:" in l.lower()]
            result["error"] = "\n".join(err_lines[:10]) if err_lines else "\n".join(lines[-10:])
            return result

        # 3. Measure binary size
        opt_path = os.path.join(build_dir, "bin", "opt")
        benchmark = os.environ.get("EVOLVE_BENCHMARK_BINARY", opt_path)
        if os.path.exists(benchmark):
            result["binary_size"] = os.path.getsize(benchmark)

        # 4. Compute score (higher = better; smaller binary = higher score)
        if result["binary_size"] > 0:
            result["score"] = 1e6 / result["binary_size"]
        else:
            result["score"] = 0.0

    except subprocess.TimeoutExpired:
        result["error"] = "Build timed out (600s)"
    finally:
        # 5. Restore original file
        if os.path.exists(backup):
            shutil.move(backup, dest)

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <program_path>", file=sys.stderr)
        sys.exit(1)
    import json
    metrics = evaluate(sys.argv[1])
    print(json.dumps(metrics, indent=2))
