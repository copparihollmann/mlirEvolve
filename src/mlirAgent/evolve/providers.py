"""LLM provider configuration loader.

Reads YAML agent configs from configs/agents/ and returns dicts
consumable by framework adapters (OpenEvolve, ShinkaEvolve).
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional

import yaml

from ..config import Config


def load_agent_config(agent_name: str, configs_dir: Optional[str] = None) -> Dict[str, Any]:
    """Load an agent YAML config by name.

    Args:
        agent_name: Name without extension, e.g. "claude_opus".
        configs_dir: Override for configs directory.

    Returns:
        Dict with keys: api_base, model, api_key_env, temperature, max_tokens.
        The api_key is resolved from the environment variable named in api_key_env.
    """
    base = Path(configs_dir or Config.EVOLVE_CONFIGS_DIR) / "agents"
    path = base / f"{agent_name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Agent config not found: {path}")

    with open(path) as f:
        cfg = yaml.safe_load(f)

    # Resolve API key from environment
    key_env = cfg.get("api_key_env", "")
    cfg["api_key"] = os.environ.get(key_env, "")
    return cfg


def list_agents(configs_dir: Optional[str] = None) -> list:
    """List available agent config names."""
    base = Path(configs_dir or Config.EVOLVE_CONFIGS_DIR) / "agents"
    if not base.exists():
        return []
    return sorted(p.stem for p in base.glob("*.yaml"))
