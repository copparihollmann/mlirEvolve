"""
Evaluator tool for evolutionary compiler optimization.

Patches an evolved C++ heuristic into the LLVM source tree, rebuilds
incrementally, compiles benchmarks, and measures binary size / perf.
"""

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, Optional

from ..config import Config


def evaluate_heuristic(
    heuristic_path: str,
    target_file: str = "llvm/lib/Analysis/InlineAdvisor.cpp",
    build_targets: Optional[list] = None,
    benchmark_binary: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Evaluate an evolved heuristic by patching it into LLVM and rebuilding.

    Args:
        heuristic_path: Path to the evolved C++ source file.
        target_file: Relative path within llvm-project to replace.
        build_targets: Ninja targets to rebuild (default: incremental).
        benchmark_binary: Path to binary to measure with llvm-size.

    Returns:
        Dict with score, binary_size, build_success, build_time, etc.
    """
    llvm_src = Config.LLVM_SRC_PATH
    build_dir = os.getenv("EVOLVE_BUILD_DIR", os.path.join(Config.BUILD_DIR, "llvm-project"))

    result = {
        "score": 0.0,
        "build_success": False,
        "build_time": 0.0,
        "binary_size": 0,
        "error": None,
    }

    # 1. Patch: copy evolved heuristic into LLVM source tree
    dest = os.path.join(llvm_src, target_file)
    backup = dest + ".bak"
    try:
        if os.path.exists(dest):
            shutil.copy2(dest, backup)
        shutil.copy2(heuristic_path, dest)
    except OSError as e:
        result["error"] = f"Patch failed: {e}"
        return result

    # 2. Rebuild LLVM incrementally
    if build_targets is None:
        build_targets = ["lib/Analysis/CMakeFiles/LLVMAnalysis.dir/InlineAdvisor.cpp.o", "bin/opt"]

    try:
        start = time.time()
        cmd = ["ninja", "-C", build_dir] + build_targets
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        result["build_time"] = time.time() - start
        result["build_success"] = proc.returncode == 0

        if proc.returncode != 0:
            result["error"] = _extract_errors(proc.stderr)
            return result
    except subprocess.TimeoutExpired:
        result["error"] = "Build timed out (600s)"
        return result
    finally:
        # Restore original file
        if os.path.exists(backup):
            shutil.move(backup, dest)

    # 3. Measure binary size
    opt_binary = os.path.join(build_dir, "bin", "opt")
    if benchmark_binary:
        opt_binary = benchmark_binary

    if os.path.exists(opt_binary):
        result["binary_size"] = os.path.getsize(opt_binary)

    # 4. Compute score (lower binary size = higher score, normalized)
    # Baseline: if binary_size > 0, score = 1.0 / (binary_size / 1e6)
    # This gives higher scores to smaller binaries
    if result["binary_size"] > 0:
        result["score"] = 1e6 / result["binary_size"]
    else:
        result["score"] = 0.0

    return result


def _extract_errors(stderr: str, max_lines: int = 20) -> str:
    """Extract the most relevant error lines from build stderr."""
    lines = stderr.strip().split("\n")
    error_lines = [l for l in lines if "error:" in l.lower() or "FAILED:" in l]
    if error_lines:
        return "\n".join(error_lines[:max_lines])
    return "\n".join(lines[-max_lines:])
