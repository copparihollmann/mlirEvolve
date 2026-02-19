"""Abstract base class for evolutionary optimization tasks."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, List


class Task(ABC):
    """A task defines what to evolve and how to evaluate it."""

    @abstractmethod
    def get_initial_program(self) -> Path:
        """Return path to the initial program with EVOLVE-BLOCK markers."""
        ...

    @abstractmethod
    def get_evolve_blocks(self) -> List[str]:
        """Return list of block names that can be evolved."""
        ...

    @abstractmethod
    def get_evaluator(self) -> Path:
        """Return path to the standalone evaluator script."""
        ...

    @abstractmethod
    def evaluate(self, program_path: Path) -> Dict[str, Any]:
        """Run evaluation and return metrics dict with at least 'score'."""
        ...
