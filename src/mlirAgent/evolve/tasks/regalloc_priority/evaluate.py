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
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    from ..llvm_bench import (
        EvalConfig, build_llvm, eval_benchmarks, extract_hyperparams,
        find_benchmarks, load_baseline, optuna_tune, patch_source,
        restore_source,
    )
except ImportError:
    # Standalone loading by OpenEvolve's importlib (no parent package)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from llvm_bench import (
        EvalConfig, build_llvm, eval_benchmarks, extract_hyperparams,
        find_benchmarks, load_baseline, optuna_tune, patch_source,
        restore_source,
    )

_EVAL_DIR = Path(__file__).resolve().parent


def _score(total_binary, baseline_total_binary, speedups):
    """RegAlloc score: performance-weighted (5x speedup + 1x binary reduction)."""
    binary_pct = (
        100.0 * (baseline_total_binary - total_binary) / baseline_total_binary
        if baseline_total_binary > 0 else 0.0
    )
    avg_speedup = sum(speedups) / len(speedups) if speedups else 0.0
    speedup_pct = (avg_speedup - 1.0) * 100 if avg_speedup > 0 else 0.0
    return round(5.0 * speedup_pct + binary_pct, 4)


def evaluate(program_path: str, config: EvalConfig = None) -> dict:
    """Evaluate an evolved LLVM register allocation priority function.

    Score = weighted combination of runtime speedup and binary size reduction.
    Register allocation primarily affects runtime (spilling, register pressure)
    but can also affect code size.
    """
    if config is None:
        config = EvalConfig.from_env(
            "llvm/lib/CodeGen/EvolvedRegAllocPriority.cpp",
            baseline_file=str(_EVAL_DIR / "baseline_regalloc.json"),
        )

    if not config.llvm_src or not config.build_dir:
        return {
            "combined_score": 0.0,
            "error": "LLVM_SRC_PATH and EVOLVE_BUILD_DIR must be set",
        }

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

    try:
        dest, backup = patch_source(program_path, config)
    except OSError as e:
        result["error"] = f"Patch failed: {e}"
        return result

    try:
        ok, build_time, err = build_llvm(config)
        result["build_time"] = build_time
        result["build_success"] = ok
        if not ok:
            result["error"] = err
            return result

        baseline = load_baseline(config)
        opt_path = os.path.join(config.build_dir, "bin", "opt")
        llc_path = os.path.join(config.build_dir, "bin", "llc")
        benchmarks = find_benchmarks(Path(config.testsuite_dir))

        if not benchmarks:
            result["error"] = "No benchmark .bc files found in testsuite/"
            return result

        # Extract hyperparams and optionally run Optuna
        with open(program_path) as f:
            hyperparams = extract_hyperparams(f.read())

        evolved_llc_flags = ["-use-evolved-regalloc-priority"]

        if hyperparams and config.optuna_trials > 0:
            print(f"  Optuna: tuning {len(hyperparams)} hyperparams "
                  f"({config.optuna_trials} trials)...")
            tune_start = time.time()
            best_sub, best_params, extra_flags = optuna_tune(
                opt_path, llc_path, benchmarks, baseline,
                n_trials=config.optuna_trials, hyperparams=hyperparams,
                data_dir=config.data_dir, score_fn=_score,
                opt_timeout=config.opt_timeout,
                optuna_subset=config.optuna_subset,
                base_llc_flags=evolved_llc_flags, flag_target="llc",
            )
            result["optuna_trials"] = config.optuna_trials
            result["optuna_subset_score"] = best_sub
            result["tuned_params"] = best_params
            result["tune_time"] = round(time.time() - tune_start, 2)
            evolved_llc_flags.extend(extra_flags)
        elif hyperparams:
            result["optuna_trials"] = 0
            result["tuned_params"] = {}

        # Final evaluation on all benchmarks
        with tempfile.TemporaryDirectory(prefix="regalloc_eval_") as tmp_dir:
            score, ev = eval_benchmarks(
                benchmarks, opt_path, llc_path, baseline, tmp_dir,
                config.data_dir, _score,
                evolved_llc_flags=evolved_llc_flags,
                opt_timeout=config.opt_timeout,
            )

        result["combined_score"] = score
        result["benchmark_details"] = ev["details"]
        result["total_binary_size"] = ev["total_binary"]

        if ev["baseline_total_binary"] > 0:
            result["binary_reduction_pct"] = round(
                100.0 * (ev["baseline_total_binary"] - ev["total_binary"])
                / ev["baseline_total_binary"], 4
            )
        if ev["speedups"]:
            result["avg_speedup"] = round(
                sum(ev["speedups"]) / len(ev["speedups"]), 4
            )
        if ev["errors"]:
            result["error"] = "; ".join(ev["errors"])

    except subprocess.TimeoutExpired:
        result["error"] = "Build timed out (600s)"
    finally:
        restore_source(dest, backup)

    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Evaluate LLVM regalloc priority")
    parser.add_argument("program_path", help="Path to evolved C++ source")
    EvalConfig.add_arguments(parser)
    args = parser.parse_args()
    config = EvalConfig.from_args(
        args, "llvm/lib/CodeGen/EvolvedRegAllocPriority.cpp",
        baseline_file=str(_EVAL_DIR / "baseline_regalloc.json"),
    )
    metrics = evaluate(args.program_path, config=config)
    print(json.dumps(metrics, indent=2))
