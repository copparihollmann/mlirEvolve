"""Framework adapters for evolutionary optimization.

Translates our unified config (task + agent + framework YAML) into the
specific format each evolution framework expects, then launches it.
"""

import os
import sys
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional

import yaml

from ..config import Config
from .providers import load_agent_config


class FrameworkAdapter(ABC):
    """Abstract adapter that bridges our config to a specific evo framework."""

    def __init__(self):
        self.task = None
        self.agent_config = None
        self.framework_config = None

    def configure(self, task, agent_config: Dict[str, Any], framework_config: Dict[str, Any]):
        """Store task, agent, and framework configs."""
        self.task = task
        self.agent_config = agent_config
        self.framework_config = framework_config

    @abstractmethod
    def launch(self, dry_run: bool = False, max_iterations: Optional[int] = None) -> Dict[str, Any]:
        """Start the evolution run. Returns result dict."""
        ...

    @abstractmethod
    def get_results(self) -> Dict[str, Any]:
        """Return results from the most recent run."""
        ...


class OpenEvolveAdapter(FrameworkAdapter):
    """Adapter for the OpenEvolve framework (third_party/openevolve)."""

    def __init__(self):
        super().__init__()
        self._result = None

    def launch(self, dry_run: bool = False, max_iterations: Optional[int] = None) -> Dict[str, Any]:
        # Ensure openevolve is importable
        oe_path = Config.OPENEVOLVE_PATH
        if oe_path not in sys.path:
            sys.path.insert(0, oe_path)

        from openevolve.config import Config as OEConfig, LLMModelConfig

        # Build OpenEvolve config from our YAML configs
        oe_cfg = OEConfig()

        # Framework settings
        fw = self.framework_config or {}
        oe_cfg.max_iterations = max_iterations or fw.get("max_iterations", 100)
        oe_cfg.database.num_islands = fw.get("islands", 4)
        oe_cfg.database.population_size = fw.get("population_size", 50)
        oe_cfg.database.migration_interval = fw.get("migration_interval", 10)
        if fw.get("random_seed") is not None:
            oe_cfg.random_seed = fw["random_seed"]

        # File suffix for C++ evolution
        oe_cfg.language = "cpp"
        oe_cfg.file_suffix = ".cpp"

        # LLM settings from agent config
        agent = self.agent_config or {}
        model = LLMModelConfig(
            name=agent.get("model", "claude-opus-4-6"),
            api_base=agent.get("api_base", "https://api.anthropic.com/v1"),
            api_key=agent.get("api_key", ""),
            temperature=agent.get("temperature", 0.7),
            max_tokens=agent.get("max_tokens", 4096),
        )
        oe_cfg.llm.models = [model]
        oe_cfg.llm.evaluator_models = [model]

        # Paths
        initial_program = str(self.task.get_initial_program())
        evaluator = str(self.task.get_evaluator())

        if dry_run:
            return {
                "dry_run": True,
                "initial_program": initial_program,
                "evaluator": evaluator,
                "config": {
                    "max_iterations": oe_cfg.max_iterations,
                    "population_size": oe_cfg.database.population_size,
                    "islands": oe_cfg.database.num_islands,
                    "model": agent.get("model"),
                    "language": oe_cfg.language,
                },
            }

        # Launch via OpenEvolve API
        from openevolve.api import run_evolution

        result = run_evolution(
            initial_program=initial_program,
            evaluator=evaluator,
            config=oe_cfg,
            iterations=oe_cfg.max_iterations,
            cleanup=False,
        )
        self._result = {
            "best_score": result.best_score,
            "best_code": result.best_code,
            "metrics": result.metrics,
            "output_dir": result.output_dir,
        }
        return self._result

    def get_results(self) -> Dict[str, Any]:
        return self._result or {}


class ShinkaAdapter(FrameworkAdapter):
    """Adapter for ShinkaEvolve (stub — not yet implemented)."""

    def launch(self, dry_run: bool = False, max_iterations: Optional[int] = None) -> Dict[str, Any]:
        raise NotImplementedError(
            "ShinkaEvolve adapter is not yet implemented. "
            "Use --framework openevolve for now."
        )

    def get_results(self) -> Dict[str, Any]:
        raise NotImplementedError("ShinkaEvolve adapter is not yet implemented.")


ADAPTERS = {
    "openevolve": OpenEvolveAdapter,
    "shinkaevolve": ShinkaAdapter,
}
