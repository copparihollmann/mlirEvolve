"""Orchestrator for running OpenEvolve with ManualLLM + Claude Code as the responder.

Usage:
    # Auto mode: Claude Code sub-agent responds to each prompt
    python -m mlirAgent.evolve.manual_run --example function_minimization --iterations 10 --auto

    # Wait mode: user manually creates response files
    python -m mlirAgent.evolve.manual_run --example function_minimization --iterations 10 --wait

    # Resume from checkpoint
    python -m mlirAgent.evolve.manual_run --example function_minimization --iterations 10 --auto \
        --resume experiments/run_YYYYMMDD_HHMMSS/openevolve_output/checkpoints/checkpoint_5
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure openevolve is importable
_MLIREVOLVE_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_OE_PATH = str(_MLIREVOLVE_ROOT / "third_party" / "openevolve")
if _OE_PATH not in sys.path:
    sys.path.insert(0, _OE_PATH)

from openevolve.config import Config as OEConfig, LLMModelConfig, load_config
from openevolve.controller import OpenEvolve
from openevolve.llm.manual import create_manual_llm


EXAMPLES = {
    "function_minimization": {
        "initial_program": _OE_PATH + "/examples/function_minimization/initial_program.py",
        "evaluator": _OE_PATH + "/examples/function_minimization/evaluator.py",
        "file_suffix": ".py",
        "language": "python",
    },
    "llvm_inlining": {
        "initial_program": str(Path(__file__).parent / "tasks/llvm_inlining/initial.cpp"),
        "evaluator": str(Path(__file__).parent / "tasks/llvm_inlining/evaluate.py"),
        "file_suffix": ".cpp",
        "language": "cpp",
    },
    "regalloc_priority": {
        "initial_program": str(Path(__file__).parent / "tasks/regalloc_priority/initial.cpp"),
        "evaluator": str(Path(__file__).parent / "tasks/regalloc_priority/evaluate.py"),
        "file_suffix": ".cpp",
        "language": "cpp",
    },
}


def _build_config(args, prompts_dir: str) -> OEConfig:
    """Build OpenEvolve config with ManualLLM injected."""
    # Set env var so ManualLLM instances (including in worker processes) find the prompts dir
    os.environ["MANUAL_LLM_PROMPTS_DIR"] = prompts_dir

    # Load framework YAML as base
    configs_dir = str(_MLIREVOLVE_ROOT / "configs")
    fw_yaml = os.path.join(configs_dir, "frameworks", "manual.yaml")
    if os.path.exists(fw_yaml):
        cfg = OEConfig.from_yaml(fw_yaml)
    else:
        cfg = OEConfig()

    # Override iterations
    if args.iterations:
        cfg.max_iterations = args.iterations

    # Set file suffix / language from example
    if args.example and args.example in EXAMPLES:
        ex = EXAMPLES[args.example]
        cfg.file_suffix = ex["file_suffix"]
        cfg.language = ex["language"]

    # Inject ManualLLM via init_client (module-level function, picklable)
    manual_model = LLMModelConfig(
        name="manual",
        init_client=create_manual_llm,
        weight=1.0,
    )

    cfg.llm.models = [manual_model]
    cfg.llm.evaluator_models = [manual_model]

    # Small population for manual speed
    cfg.database.population_size = 10
    cfg.database.archive_size = 10
    cfg.database.num_islands = 1
    cfg.database.migration_interval = 999
    cfg.checkpoint_interval = 1
    cfg.diff_based_evolution = False

    return cfg


def _auto_respond(prompts_dir: str, stop_event: asyncio.Event):
    """Watch prompts_dir for new prompt files and auto-respond using a simple heuristic improver."""
    import glob
    import re

    responded = set()
    # Match only prompt_NNN.md (not .response.md files)
    pattern = re.compile(r"prompt_\d+\.md$")
    while not stop_event.is_set():
        prompt_files = sorted(
            f for f in glob.glob(os.path.join(prompts_dir, "prompt_*.md"))
            if pattern.search(f)
        )
        for pf in prompt_files:
            if pf in responded:
                continue
            resp_path = pf.replace(".md", ".response.md")
            if os.path.exists(resp_path):
                responded.add(pf)
                continue

            # Read the prompt
            with open(pf) as f:
                prompt_text = f.read()

            # Generate a response: extract parent code and propose improvement
            response = _generate_improvement(prompt_text)
            with open(resp_path, "w") as f:
                f.write(response)
            responded.add(pf)
            print(f"  [auto] Responded to {os.path.basename(pf)}")

        time.sleep(1)


def _generate_improvement(prompt_text: str) -> str:
    """Generate an improved version of the code from the prompt.

    Produces a diff-style response with a concrete improvement to the search algorithm.
    """
    import random

    # Choose a random improvement strategy
    strategies = [
        _strategy_simulated_annealing,
        _strategy_adaptive_step,
        _strategy_multi_restart,
        _strategy_gradient_estimate,
    ]
    strategy = random.choice(strategies)
    return strategy()


def _strategy_simulated_annealing() -> str:
    return '''Here's an improved search algorithm using simulated annealing:

<<<<<<< SEARCH
    for _ in range(iterations):
        # Simple random search
        x = np.random.uniform(bounds[0], bounds[1])
        y = np.random.uniform(bounds[0], bounds[1])
        value = evaluate_function(x, y)

        if value < best_value:
            best_value = value
            best_x, best_y = x, y
=======
    temperature = 2.0
    cooling_rate = 0.995
    step_size = 1.0
    for i in range(iterations):
        # Simulated annealing with adaptive step size
        x = best_x + np.random.normal(0, step_size)
        y = best_y + np.random.normal(0, step_size)
        x = np.clip(x, bounds[0], bounds[1])
        y = np.clip(y, bounds[0], bounds[1])
        value = evaluate_function(x, y)

        delta = value - best_value
        if delta < 0 or np.random.random() < np.exp(-delta / max(temperature, 1e-10)):
            best_value = value
            best_x, best_y = x, y

        temperature *= cooling_rate
        step_size = max(0.01, step_size * 0.999)
>>>>>>> REPLACE
'''


def _strategy_adaptive_step() -> str:
    return '''Here's an improved search algorithm with adaptive step sizes and local refinement:

<<<<<<< SEARCH
    for _ in range(iterations):
        # Simple random search
        x = np.random.uniform(bounds[0], bounds[1])
        y = np.random.uniform(bounds[0], bounds[1])
        value = evaluate_function(x, y)

        if value < best_value:
            best_value = value
            best_x, best_y = x, y
=======
    step = (bounds[1] - bounds[0]) / 4.0
    no_improve = 0
    for i in range(iterations):
        if no_improve > 50:
            # Random restart
            best_x = np.random.uniform(bounds[0], bounds[1])
            best_y = np.random.uniform(bounds[0], bounds[1])
            best_value = evaluate_function(best_x, best_y)
            step = (bounds[1] - bounds[0]) / 4.0
            no_improve = 0

        x = best_x + np.random.uniform(-step, step)
        y = best_y + np.random.uniform(-step, step)
        x = np.clip(x, bounds[0], bounds[1])
        y = np.clip(y, bounds[0], bounds[1])
        value = evaluate_function(x, y)

        if value < best_value:
            best_value = value
            best_x, best_y = x, y
            no_improve = 0
        else:
            no_improve += 1
            if no_improve % 20 == 0:
                step *= 0.8
>>>>>>> REPLACE
'''


def _strategy_multi_restart() -> str:
    return '''Here's an improved search algorithm with multiple restarts and basin hopping:

<<<<<<< SEARCH
    for _ in range(iterations):
        # Simple random search
        x = np.random.uniform(bounds[0], bounds[1])
        y = np.random.uniform(bounds[0], bounds[1])
        value = evaluate_function(x, y)

        if value < best_value:
            best_value = value
            best_x, best_y = x, y
=======
    num_restarts = 5
    iters_per_restart = iterations // num_restarts
    for restart in range(num_restarts):
        # Random restart point
        cx = np.random.uniform(bounds[0], bounds[1])
        cy = np.random.uniform(bounds[0], bounds[1])
        cv = evaluate_function(cx, cy)
        step = 1.0

        for i in range(iters_per_restart):
            x = cx + np.random.normal(0, step)
            y = cy + np.random.normal(0, step)
            x = np.clip(x, bounds[0], bounds[1])
            y = np.clip(y, bounds[0], bounds[1])
            value = evaluate_function(x, y)

            if value < cv:
                cv = value
                cx, cy = x, y
            step = max(0.01, step * 0.998)

        if cv < best_value:
            best_value = cv
            best_x, best_y = cx, cy
>>>>>>> REPLACE
'''


def _strategy_gradient_estimate() -> str:
    return '''Here's an improved search algorithm using numerical gradient estimation:

<<<<<<< SEARCH
    for _ in range(iterations):
        # Simple random search
        x = np.random.uniform(bounds[0], bounds[1])
        y = np.random.uniform(bounds[0], bounds[1])
        value = evaluate_function(x, y)

        if value < best_value:
            best_value = value
            best_x, best_y = x, y
=======
    lr = 0.1
    eps = 1e-4
    for i in range(iterations):
        # Estimate gradient via finite differences
        fx = evaluate_function(best_x + eps, best_y)
        fy = evaluate_function(best_x, best_y + eps)
        f0 = evaluate_function(best_x, best_y)
        gx = (fx - f0) / eps
        gy = (fy - f0) / eps

        # Gradient descent step with noise for exploration
        noise_scale = max(0.01, 0.5 * (1 - i / iterations))
        nx = best_x - lr * gx + np.random.normal(0, noise_scale)
        ny = best_y - lr * gy + np.random.normal(0, noise_scale)
        nx = np.clip(nx, bounds[0], bounds[1])
        ny = np.clip(ny, bounds[0], bounds[1])
        nv = evaluate_function(nx, ny)

        if nv < best_value:
            best_value = nv
            best_x, best_y = nx, ny

        lr = max(0.001, lr * 0.999)
>>>>>>> REPLACE
'''


async def _run(args):
    """Main async entry point."""
    # Set up experiment directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    exp_dir = os.path.join(_MLIREVOLVE_ROOT, "experiments", f"run_{timestamp}")
    prompts_dir = os.path.join(exp_dir, "prompts")
    oe_output_dir = os.path.join(exp_dir, "openevolve_output")
    scores_path = os.path.join(exp_dir, "scores.jsonl")
    os.makedirs(prompts_dir, exist_ok=True)
    os.makedirs(oe_output_dir, exist_ok=True)

    print(f"Experiment directory: {exp_dir}")
    print(f"Prompts directory:    {prompts_dir}")
    print(f"Scores log:           {scores_path}")

    # Build config
    cfg = _build_config(args, prompts_dir)

    # Resolve example paths
    if args.example:
        if args.example not in EXAMPLES:
            print(f"Unknown example: {args.example}. Available: {list(EXAMPLES.keys())}")
            return 1
        ex = EXAMPLES[args.example]
        initial_program = ex["initial_program"]
        evaluator = ex["evaluator"]
    else:
        print("Error: --example is required for now")
        return 1

    # Initialize OpenEvolve
    openevolve = OpenEvolve(
        initial_program_path=initial_program,
        evaluation_file=evaluator,
        config=cfg,
        output_dir=oe_output_dir,
    )

    # Load checkpoint if resuming
    if args.resume:
        if not os.path.exists(args.resume):
            print(f"Error: Checkpoint not found: {args.resume}")
            return 1
        print(f"Resuming from checkpoint: {args.resume}")
        openevolve.database.load(args.resume)

    # Start auto-responder if --auto
    stop_event = asyncio.Event()
    responder_task = None
    if args.auto:
        print("Auto mode: built-in heuristic strategies will respond to prompts")
        loop = asyncio.get_event_loop()
        responder_task = loop.run_in_executor(None, _auto_respond, prompts_dir, stop_event)

    # Hook into the database to log scores
    _original_add = openevolve.database.add

    def _logging_add(program, *a, **kw):
        result = _original_add(program, *a, **kw)
        score_entry = {
            "timestamp": time.time(),
            "iteration": program.iteration_found,
            "program_id": program.id,
            "metrics": program.metrics,
            "generation": program.generation,
        }
        best = openevolve.database.get_best_program()
        if best:
            score_entry["best_score"] = best.metrics.get("combined_score", 0)
            score_entry["best_id"] = best.id
        with open(scores_path, "a") as f:
            f.write(json.dumps(score_entry, default=str) + "\n")
        return result

    openevolve.database.add = _logging_add

    # Run evolution
    try:
        print(f"\nStarting OpenEvolve with ManualLLM ({cfg.max_iterations} iterations)...")
        best = await openevolve.run(
            iterations=cfg.max_iterations,
            checkpoint_path=args.resume,
        )
        if best:
            print(f"\nEvolution complete! Best metrics:")
            for k, v in best.metrics.items():
                if isinstance(v, float):
                    print(f"  {k}: {v:.4f}")
                else:
                    print(f"  {k}: {v}")
        else:
            print("\nNo valid programs found.")
    finally:
        stop_event.set()
        if responder_task:
            # Give responder time to notice the stop event
            await asyncio.sleep(2)

    return 0


def main():
    parser = argparse.ArgumentParser(description="Run OpenEvolve with ManualLLM")
    parser.add_argument("--example", "-e", choices=list(EXAMPLES.keys()),
                        help="Built-in example to run")
    parser.add_argument("--iterations", "-n", type=int, default=10,
                        help="Number of iterations (default: 10)")
    parser.add_argument("--auto", action="store_true",
                        help="Auto-respond with built-in heuristic strategies")
    parser.add_argument("--wait", action="store_true",
                        help="Wait for manual response files (human or external tool)")
    parser.add_argument("--resume", help="Path to checkpoint directory to resume from")

    args = parser.parse_args()

    if not args.auto and not args.wait:
        args.auto = True  # Default to auto mode

    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
