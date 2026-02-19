# Evolve: Evolutionary LLVM Heuristic Optimization

Automated framework for evolving LLVM compiler heuristics using
[OpenEvolve](../../third_party/openevolve/) with LLM-guided search.

## System Overview

```
  OpenEvolve controller
        |
        v
  ManualLLM (file-based prompt/response)
        |
        v
  Orchestrator (manual_run.py)       <-- --auto / --wait / --resume
        |
        v
  Task evaluator (evaluate.py)       <-- patches LLVM, builds, benchmarks
        |
        v
  Score -> OpenEvolve population
```

OpenEvolve manages a population of evolved C++ heuristic programs. Each
iteration, it produces prompts asking an LLM to improve the code. The
ManualLLM bridge decouples the LLM from OpenEvolve's process model,
enabling Claude Code (or any external agent) to respond.

## ManualLLM

**File:** `third_party/openevolve/openevolve/llm/manual.py`

File-based polling interface between OpenEvolve and external responders:

1. OpenEvolve writes `prompt_NNN.md` to a shared directory
2. ManualLLM polls for a corresponding `prompt_NNN.response.md`
3. When found, the response is returned to OpenEvolve as the LLM output

The prompts directory is passed via `MANUAL_LLM_PROMPTS_DIR` env var,
which crosses the process-pool boundary (OpenEvolve uses multiprocessing).
`create_manual_llm` is a module-level factory (not a lambda) to support
pickling across worker processes.

## Orchestrator

**File:** `manual_run.py`

```
python -m mlirAgent.evolve.manual_run --example llvm_inlining -n 10 --auto
```

Modes:
- `--auto` Built-in heuristic strategies (simulated annealing, gradient
  estimate, etc.) auto-respond to prompts. Fast but limited.
- `--wait` External agent (Claude Code, human) writes response files.
- `--resume <checkpoint>` Continue from a saved checkpoint.

Logs scores to `experiments/run_TIMESTAMP/scores.jsonl` and saves
OpenEvolve checkpoints every iteration.

## Evaluator Pipeline

Each task defines an `evaluate.py` that follows this pipeline:

```
1. patch_source()    Copy evolved .cpp into LLVM source tree
2. build_llvm()      ninja -C $BUILD_DIR bin/opt bin/llc
3. load_baseline()   Cache default-LLVM measurements (first run only)
4. [optuna_tune()]   Optional inner-loop for [hyperparam] knobs
5. eval_benchmarks() For each CTMark .bc file:
     opt -O2 [-use-evolved-*] bench.bc -> bench_opt.bc
     llc -O2 [-use-evolved-*] bench_opt.bc -> bench.o
     gcc bench.o -> bench
     measure .text size, binary size, runtime
6. score_fn()        Task-specific scoring
7. restore_source()  Restore original .cpp from backup
```

Shared infrastructure lives in `tasks/llvm_bench.py`. Task-specific
evaluators are thin wrappers (~100 lines) that define a scoring function
and pass the right evolved flags.

## LLVM Hooks

### Inlining (`-use-evolved-inline-cost`)
- **Source:** `llvm/lib/Analysis/EvolvedInlineCost.cpp`
- **Flag on:** `opt` (inlining happens during middle-end optimization)
- Evolves `getEvolvedInlineCost()` which returns a cost adjustment

### RegAlloc Priority (`-use-evolved-regalloc-priority`)
- **Source:** `llvm/lib/CodeGen/EvolvedRegAllocPriority.cpp`
- **Flag on:** `llc` (register allocation happens during code generation)
- Evolves `computeEvolvedRegAllocPriority()` which returns a priority value

## Hyperparameter Convention

Evolved C++ code can declare tunable numeric knobs:

```cpp
const int base_threshold = 100;  // [hyperparam]: ae-inline-base-threshold, int, 50, 300
```

Format: `// [hyperparam]: flag-name, type, min, max`

When present and `optuna_trials > 0`, the evaluator runs an Optuna
inner-loop on a benchmark subset to find optimal values before the final
full-suite evaluation. Tuned values are passed as LLVM command-line flags
(e.g. `-ae-inline-base-threshold=173`).

## Configuration

`EvalConfig` dataclass supports both programmatic and env-var configuration:

```python
from mlirAgent.evolve.tasks.llvm_bench import EvalConfig

# From environment variables (backward compatible)
config = EvalConfig.from_env("llvm/lib/Analysis/EvolvedInlineCost.cpp")

# Programmatic with overrides
config = EvalConfig.from_env(
    "llvm/lib/Analysis/EvolvedInlineCost.cpp",
    optuna_trials=5,
    opt_timeout=60,
)
```

Key env vars: `LLVM_SRC_PATH`, `EVOLVE_BUILD_DIR`, `EVOLVE_OPT_TIMEOUT`,
`EVOLVE_OPTUNA_TRIALS`.

## Task Structure

```
tasks/
  llvm_bench.py              # Shared: EvalConfig, compile, baseline, Optuna
  llvm_inlining/
    evaluate.py              # Thin wrapper: _score(), evaluate()
    initial.cpp              # Seed heuristic
    task.py                  # OpenEvolve Task class
    benchmarks/testsuite/    # CTMark .bc files + data/
  regalloc_priority/
    evaluate.py              # Thin wrapper: _score(), evaluate()
    initial.cpp              # Seed priority function
    baseline_regalloc.json   # Separate baseline cache
```

### Adding a New Task

1. Create `tasks/my_task/` with `initial.cpp` and `evaluate.py`
2. In `evaluate.py`, define `_score(total_binary, baseline_binary, speedups)`
3. Call shared functions from `llvm_bench.py` with the right evolved flags
4. Add entry to `EXAMPLES` dict in `manual_run.py`

## Scoring Formulas

**Inlining:** `binary_reduction_pct + (avg_speedup - 1.0) * 10`
- Primary: linked binary size reduction vs baseline (Magellan-comparable)
- Secondary: small bonus for runtime improvement

**RegAlloc:** `5.0 * speedup_pct + 1.0 * binary_reduction_pct`
- Primary: runtime improvement (regalloc most affects execution speed)
- Secondary: binary size reduction

## Experiment Results (CTMark, Feb 2026)

### LLVM Inlining
| Experiment | Optuna | Iters | Best Score | Binary Reduction | Time |
|-----------|--------|-------|------------|-----------------|------|
| Exp A     | No     | 10    | 8.65       | 8.78%           | ~50 min |
| Exp C     | 5 trials | 10  | 8.66       | 8.41%           | ~90 min |

Both match Magellan's reported range (4.27-8.79%) with only 10 iterations.
Optuna eliminates failures (100% positive scores vs 80%) but doesn't
improve peak performance significantly. Code structure matters more than
hyperparameter values for peak score.

### Key Insight
Os-level inlining hurts tramp3d-v4 (C++ templates need inlining for
devirtualization). Best heuristics learn to selectively increase inlining
for template-heavy code.
