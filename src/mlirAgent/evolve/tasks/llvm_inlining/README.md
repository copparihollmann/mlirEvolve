# LLVM Inlining Heuristic Evolution

Evolve LLVM's inline cost function using LLM-guided search (OpenEvolve).
Based on the [Magellan paper](https://arxiv.org/abs/2411.01311) (ICML 2025).

## Overview

The LLVM inliner decides whether to inline a function call by computing an
`InlineCost` from ~25 features (call overhead, callee complexity, SROA
savings, etc.). We evolve `computeEvolvedInlineCost()` — a C++ function that
maps these features to a scalar cost — and measure binary size reduction on
the CTMark benchmark suite.

A two-level optimization loop:

1. **Outer loop (LLM):** proposes code *structure* — which features to use,
   how to combine them, multipliers, conditional logic.
2. **Inner loop (Optuna):** tunes numeric hyperparameters annotated with
   `[hyperparam]` comments in the C++ source.

## Prerequisites

- **LLVM build** with the evolved inline cost hook:
  - `llvm/include/llvm/Analysis/EvolvedInlineCost.h`
  - `llvm/lib/Analysis/EvolvedInlineCost.cpp`
  - Hook in `llvm/lib/Analysis/InlineCost.cpp` (`-use-evolved-inline-cost` flag)
- **CTMark .bc files** in `benchmarks/testsuite/*.bc` (pre-compiled from
  llvm-test-suite CTMark benchmarks)
- **Benchmark data** in `benchmarks/testsuite/data/<bench>/` for runtime measurement
- **Python packages:** `optuna`

## How to Run

```bash
# Set environment
export LLVM_SRC_PATH=/path/to/llvm-project
export EVOLVE_BUILD_DIR=/path/to/llvm-build

# Run 10 iterations in wait mode (you provide responses)
python -m mlirAgent.evolve.manual_run --example llvm_inlining --iterations 10 --wait

# Or auto mode with built-in strategies (for testing)
python -m mlirAgent.evolve.manual_run --example llvm_inlining --iterations 10 --auto
```

### Responding to Prompts

In `--wait` mode, the orchestrator creates prompt files in the experiment's
`prompts/` directory:

1. Read `prompt_NNN.md` — contains the current best program, its score,
   and instructions.
2. Write `prompt_NNN.response.md` — must contain the full evolved C++ file
   in a ````cpp` code block.

Example response:

    Here's my improved version with a stronger constant_args bonus:

    ```cpp
    // ... full EvolvedInlineCost.cpp content ...
    ```

### Using an External LLM (Codex, etc.)

Point your LLM responder at the prompts directory:

```bash
# Watch for new prompts and respond
watch -n 5 ls experiments/run_*/prompts/
# For each prompt_NNN.md without a .response.md, send to your LLM and save response
```

## `[hyperparam]` Annotation Convention

Numeric knobs in the C++ source can be annotated for Optuna tuning:

```cpp
// [hyperparam]: ae-inline-base-threshold, int, 50, 1000
static cl::opt<int> BaseThreshold("ae-inline-base-threshold", cl::init(225), ...);
```

Format: `// [hyperparam]: <flag-name>, <type>, <min>, <max>`

- `flag-name`: LLVM `cl::opt` flag name, passed as `-<flag-name>=<value>` to `opt`
- `type`: `int` or `float`
- `min`, `max`: search range for Optuna

### Controlling Optuna

| Env Var | Default | Description |
|---------|---------|-------------|
| `EVOLVE_OPTUNA_TRIALS` | 20 | Number of Optuna trials per evaluation (0 = disable) |

Optuna trials run on a 3-benchmark subset (sqlite3, spass, tramp3d-v4) for
speed, then the best parameters are used for the full 8-benchmark final
evaluation.

## Evaluator Scoring

**Primary metric:** Linked binary size reduction % vs baseline LLVM (no
evolved heuristic).

```
score = 100 * (baseline_binary_total - evolved_binary_total) / baseline_binary_total
```

Higher is better. The baseline is cached in `benchmarks/testsuite/baseline.json`.

**Secondary:** Runtime speedup bonus (weighted at 10x, added to binary score).

## CTMark Benchmarks

| Benchmark | Language | Notes |
|-----------|----------|-------|
| bullet | C++ | Physics simulation |
| consumer-typeset | C | Document typesetting (Lout) |
| kimwitu | C++ | Tree pattern matcher |
| lencod | C | H.264 video encoder |
| mafft | C | Multiple sequence alignment |
| spass | C | Theorem prover |
| sqlite3 | C | Embedded database |
| tramp3d-v4 | C++ | Template-heavy physics |

Excluded: clamav (segfault), 7zip (link error from multi-source build).

## Experiment Results

### Experiment A: No Optuna, 10 iterations (2026-02-17)

Best score: **8.65** (8.78% binary size reduction), iteration 3.
Avg score: 5.75, median: 8.01. Time: 45 min total (~4.5 min/iter).

| Benchmark | Binary Reduction % |
|-----------|-------------------|
| sqlite3 | 19.7% |
| spass | 18.2% |
| consumer-typeset | 13.2% |
| mafft | 12.2% |
| lencod | 7.9% |
| bullet | 7.2% |
| tramp3d-v4 | 6.7% |
| kimwitu | 0.4% |

### Experiment B: + Optuna (5 trials), 10 iterations (2026-02-18)

Best score: **8.66** (8.41% binary size reduction), iteration 2.
Avg score: 6.00, median: 7.16. Time: 83 min total (~8.3 min/iter).
Optuna-tuned params: threshold=173, sroa_weight=157, simplify_weight=23.

| Benchmark | Binary Reduction % |
|-----------|-------------------|
| sqlite3 | 15.9% |
| spass | 14.6% |
| consumer-typeset | 12.0% |
| mafft | 11.5% |
| tramp3d-v4 | 10.3% |
| bullet | 7.4% |
| lencod | 6.4% |
| kimwitu | 0.3% |

### Comparison

- **Peak score**: Nearly identical (A=8.65 vs B=8.66)
- **Key difference**: Optuna shifts the tradeoff — B gains +3.6% on
  tramp3d-v4 (C++ templates benefit from higher threshold=173) but
  loses on sqlite3/spass (less aggressive inlining overall)
- **Consistency**: B has higher floor (worst=1.18 vs A's worst=-3.26)
  but similar >7.0 hit rate (6/11 vs 6/10)
- **Overhead**: Optuna doubles iteration time (8.3 vs 4.5 min/iter)
- Both match Magellan's reported range of 4.27%–8.79% on CTMark

Key insight: Os-level inlining (very aggressive size reduction) hurts
tramp3d-v4 because C++ templates need inlining for specialization. The
best heuristic uses **selective inlining** — high constant_args bonus,
nested inline penalties, and a moderate threshold.

### Best Heuristic Structure

- Heavy constant_args bonus (30 per arg)
- 2.5x penalty for unsimplified instructions
- 4x penalty for loops
- Doubled switch/jump table penalties
- Nested inline penalties (20 per nested inline + cost/2)
- Multi-block penalty (30)
- Optuna-tuned: BaseThreshold=173, SROAWeight=157, SimplifyWeight=23

## File Structure

```
tasks/llvm_inlining/
├── README.md           # This file
├── initial.cpp         # Seed program (default LLVM-equivalent heuristic)
├── evaluate.py         # Evaluator (patches LLVM, builds, measures)
└── benchmarks/
    └── testsuite/
        ├── *.bc            # Pre-compiled CTMark bitcode files
        ├── baseline.json   # Cached baseline measurements
        └── data/           # Runtime input data per benchmark
```
