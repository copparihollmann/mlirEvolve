"""LLVM inlining heuristic optimization task (Magellan replication).

Evolves the inline cost heuristic in LLVM's InlineAdvisor using
EVOLVE-BLOCK markers. The evaluator rebuilds LLVM and measures
binary size of compiled benchmarks.
"""

from pathlib import Path
from typing import Dict, Any, List

from ..base import Task
from .evaluate import evaluate as evaluate_evolved


class LLVMInliningTask(Task):
    """Evolutionary optimization of LLVM's inlining cost heuristic."""

    def __init__(self, task_config: Dict[str, Any] = None):
        self._config = task_config or {}
        self._task_dir = Path(__file__).parent

    def get_initial_program(self) -> Path:
        return self._task_dir / "initial.cpp"

    def get_evolve_blocks(self) -> List[str]:
        return ["inline_cost_heuristic"]

    def get_evaluator(self) -> Path:
        return self._task_dir / "evaluate.py"

    def evaluate(self, program_path: Path) -> Dict[str, Any]:
        return evaluate_evolved(str(program_path))
