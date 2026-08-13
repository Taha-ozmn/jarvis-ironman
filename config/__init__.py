"""Config package — thin wrapper over YAML."""

from config.loader import ensure_jarvis2_defaults, load_config, save_config

__all__ = ["load_config", "save_config", "ensure_jarvis2_defaults"]
