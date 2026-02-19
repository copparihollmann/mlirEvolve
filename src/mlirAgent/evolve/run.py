"""CLI entry point for the evolve harness.

Usage:
    python -m mlirAgent.evolve.run --task llvm_inlining --framework openevolve --agent claude_opus
    python -m mlirAgent.evolve.run --list
    python -m mlirAgent.evolve.run --task llvm_inlining --framework openevolve --agent claude_opus --dry-run
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional

import yaml

from ..config import Config
from .adapters import ADAPTERS
from .providers import load_agent_config, list_agents


# Registry of available tasks
TASKS = {
    "llvm_inlining": "mlirAgent.evolve.tasks.llvm_inlining.task.LLVMInliningTask",
}


def _load_task(task_name: str, configs_dir: str) -> Any:
    """Instantiate a task by name, loading its YAML config if present."""
    if task_name not in TASKS:
        raise ValueError(f"Unknown task: {task_name}. Available: {list(TASKS.keys())}")

    # Import task class
    module_path, class_name = TASKS[task_name].rsplit(".", 1)
    import importlib
    mod = importlib.import_module(module_path)
    task_cls = getattr(mod, class_name)

    # Load task YAML config
    task_yaml = Path(configs_dir) / "tasks" / f"{task_name}.yaml"
    task_config = {}
    if task_yaml.exists():
        with open(task_yaml) as f:
            task_config = yaml.safe_load(f) or {}

    return task_cls(task_config)


def _load_framework_config(framework_name: str, configs_dir: str) -> Dict[str, Any]:
    """Load framework YAML config."""
    fw_yaml = Path(configs_dir) / "frameworks" / f"{framework_name}.yaml"
    if not fw_yaml.exists():
        raise FileNotFoundError(f"Framework config not found: {fw_yaml}")
    with open(fw_yaml) as f:
        return yaml.safe_load(f) or {}


def _list_available(configs_dir: str):
    """Print available agents, frameworks, and tasks."""
    print("Available configurations:\n")

    print("  Agents:")
    agents_dir = Path(configs_dir) / "agents"
    if agents_dir.exists():
        for p in sorted(agents_dir.glob("*.yaml")):
            print(f"    - {p.stem}")
    else:
        print("    (none)")

    print("\n  Frameworks:")
    fw_dir = Path(configs_dir) / "frameworks"
    if fw_dir.exists():
        for p in sorted(fw_dir.glob("*.yaml")):
            print(f"    - {p.stem}")
    else:
        print("    (none)")

    print("\n  Tasks:")
    for name in sorted(TASKS.keys()):
        print(f"    - {name}")


def main():
    parser = argparse.ArgumentParser(
        description="Evolve harness: evolutionary compiler optimization"
    )
    parser.add_argument("--task", "-t", help="Task name (e.g. llvm_inlining)")
    parser.add_argument("--framework", "-f", help="Framework name (e.g. openevolve)")
    parser.add_argument("--agent", "-a", help="Agent config name (e.g. claude_opus)")
    parser.add_argument("--list", action="store_true", help="List available configs")
    parser.add_argument("--dry-run", action="store_true", help="Print config without running")
    parser.add_argument("--max-iterations", type=int, help="Override max iterations")
    parser.add_argument("--configs-dir", default=Config.EVOLVE_CONFIGS_DIR,
                        help="Path to configs directory")

    args = parser.parse_args()
    configs_dir = args.configs_dir

    if args.list:
        _list_available(configs_dir)
        return 0

    if not all([args.task, args.framework, args.agent]):
        parser.error("--task, --framework, and --agent are required (or use --list)")

    # Load everything
    task = _load_task(args.task, configs_dir)
    agent_config = load_agent_config(args.agent, configs_dir)
    framework_config = _load_framework_config(args.framework, configs_dir)

    # Get adapter
    if args.framework not in ADAPTERS:
        print(f"Error: Unknown framework '{args.framework}'. Available: {list(ADAPTERS.keys())}")
        return 1

    adapter = ADAPTERS[args.framework]()
    adapter.configure(task, agent_config, framework_config)

    # Run
    result = adapter.launch(dry_run=args.dry_run, max_iterations=args.max_iterations)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
