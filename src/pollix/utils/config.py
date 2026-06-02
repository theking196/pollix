"""Configuration management for pollix.

Supports a hierarchical configuration system:
CLI args > environment variables > local config > global config > defaults
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# Default configuration values
DEFAULT_CONFIG = {
    "api_key": "",
    "default_model": "gemma-4",
    "default_context_mode": "auto",
    "max_tokens": 4096,
    "temperature": 0.7,
    "theme": "dark",
    "auto_backup": True,
    "ignore_patterns": [
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        "*.pyc", ".pytest_cache", "dist", "build", "*.egg-info",
        ".tox", ".mypy_cache", ".coverage", "htmlcov",
    ],
    "max_file_size": 100_000,
    "history_limit": 100,
    "stream_output": True,
    "verbose": False,
    "debug": False,
}

# Environment variable mapping
ENV_MAPPINGS = {
    "api_key": "POLLINATION_API_KEY",
    "default_model": "POLLIX_DEFAULT_MODEL",
    "default_context_mode": "POLLIX_CONTEXT_MODE",
    "temperature": "POLLIX_TEMPERATURE",
    "max_tokens": "POLLIX_MAX_TOKENS",
    "theme": "POLLIX_THEME",
    "auto_backup": "POLLIX_AUTO_BACKUP",
    "max_file_size": "POLLIX_MAX_FILE_SIZE",
    "history_limit": "POLLIX_HISTORY_LIMIT",
    "verbose": "POLLIX_VERBOSE",
    "debug": "POLLIX_DEBUG",
}


@dataclass
class Config:
    """Pollix configuration settings.

    Attributes:
        api_key: Pollination API key.
        default_model: Default model to use for requests.
        default_context_mode: Default context gathering mode.
        max_tokens: Maximum tokens per response.
        temperature: Sampling temperature (0.0 - 1.0).
        theme: UI theme (dark or light).
        auto_backup: Create backups before file edits.
        ignore_patterns: Patterns for files to ignore.
        max_file_size: Maximum file size to read in bytes.
        history_limit: Maximum conversation history entries.
        stream_output: Enable streaming responses by default.
        verbose: Enable verbose output.
        debug: Enable debug mode.
    """

    api_key: str = ""
    default_model: str = "gemma-4"
    default_context_mode: str = "auto"
    max_tokens: int = 4096
    temperature: float = 0.7
    theme: str = "dark"
    auto_backup: bool = True
    ignore_patterns: List[str] = field(default_factory=lambda: list(DEFAULT_CONFIG["ignore_patterns"]))
    max_file_size: int = 100_000
    history_limit: int = 100
    stream_output: bool = True
    verbose: bool = False
    debug: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return asdict(self)

    def merge(self, other: Dict[str, Any]) -> "Config":
        """Merge dictionary values into this config.

        Args:
            other: Dictionary of values to merge.

        Returns:
            New Config with merged values.
        """
        data = self.to_dict()
        for key, value in other.items():
            if key in data and value is not None:
                data[key] = value
        return Config(**data)

    def validate(self) -> List[str]:
        """Validate configuration and return list of issues.

        Returns:
            List of validation error messages.
        """
        issues: List[str] = []

        if not self.api_key:
            issues.append("API key is not configured. Set POLLINATION_API_KEY or run 'pollix init --global'")

        if self.temperature < 0.0 or self.temperature > 1.0:
            issues.append(f"Temperature must be between 0.0 and 1.0, got {self.temperature}")

        if self.max_tokens < 1:
            issues.append(f"max_tokens must be positive, got {self.max_tokens}")

        if self.max_file_size < 1024:
            issues.append(f"max_file_size must be at least 1024, got {self.max_file_size}")

        valid_modes = ["minimal", "auto", "full", "files"]
        if self.default_context_mode not in valid_modes:
            issues.append(f"Invalid context mode '{self.default_context_mode}'. Must be one of: {', '.join(valid_modes)}")

        valid_themes = ["dark", "light"]
        if self.theme not in valid_themes:
            issues.append(f"Invalid theme '{self.theme}'. Must be one of: {', '.join(valid_themes)}")

        return issues


class ConfigManager:
    """Manages pollix configuration files.

    Handles reading and writing global (~/.pollix/) and local (.pollix/)
    configuration with proper precedence.

    Example:
        >>> manager = ConfigManager()
        >>> config = manager.load_config()
        >>> print(config.default_model)
        'gemma-4'
    """

    GLOBAL_CONFIG_DIR = Path.home() / ".pollix"
    GLOBAL_CONFIG_FILE = GLOBAL_CONFIG_DIR / "config.yaml"
    LOCAL_CONFIG_DIR = Path.cwd() / ".pollix"
    LOCAL_CONFIG_FILE = LOCAL_CONFIG_DIR / "config.yaml"

    def __init__(self) -> None:
        """Initialize the config manager."""
        self._cached_config: Optional[Config] = None

    @property
    def global_dir(self) -> Path:
        """Path to global config directory."""
        return self.GLOBAL_CONFIG_DIR

    @property
    def global_file(self) -> Path:
        """Path to global config file."""
        return self.GLOBAL_CONFIG_FILE

    @property
    def local_dir(self) -> Path:
        """Path to local config directory."""
        return self.LOCAL_CONFIG_DIR

    @property
    def local_file(self) -> Path:
        """Path to local config file."""
        return self.LOCAL_CONFIG_FILE

    def _ensure_dir(self, path: Path) -> None:
        """Ensure a directory exists.

        Args:
            path: Directory path to create.
        """
        path.mkdir(parents=True, exist_ok=True)

    def _read_yaml(self, path: Path) -> Dict[str, Any]:
        """Read YAML file.

        Args:
            path: Path to YAML file.

        Returns:
            Dictionary of config values.
        """
        if not path.exists():
            return {}

        if not HAS_YAML:
            # Fallback: try to parse simple key-value pairs
            return self._read_simple_config(path)

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f)
                return content if isinstance(content, dict) else {}
        except (yaml.YAMLError, OSError, PermissionError):
            return {}

    def _write_yaml(self, path: Path, data: Dict[str, Any]) -> None:
        """Write YAML file.

        Args:
            path: Path to write to.
            data: Dictionary to serialize.
        """
        self._ensure_dir(path.parent)

        if HAS_YAML:
            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        else:
            # Fallback: write as simple key-value pairs
            self._write_simple_config(path, data)

    def _read_simple_config(self, path: Path) -> Dict[str, Any]:
        """Read a simple key-value config file (fallback when YAML is not available).

        Args:
            path: Path to config file.

        Returns:
            Dictionary of config values.
        """
        result: Dict[str, Any] = {}
        if not path.exists():
            return result

        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")

                        # Try to parse as int, float, bool
                        if value.lower() == "true":
                            value = True
                        elif value.lower() == "false":
                            value = False
                        else:
                            try:
                                if "." in value:
                                    value = float(value)
                                else:
                                    value = int(value)
                            except ValueError:
                                pass

                        result[key] = value
        except (OSError, PermissionError):
            pass

        return result

    def _write_simple_config(self, path: Path, data: Dict[str, Any]) -> None:
        """Write a simple key-value config file.

        Args:
            path: Path to write to.
            data: Dictionary to serialize.
        """
        with open(path, "w", encoding="utf-8") as f:
            f.write("# Pollix configuration file\n")
            f.write(f"# Generated on {__import__('datetime').datetime.now().isoformat()}\n\n")
            for key, value in data.items():
                if isinstance(value, list):
                    f.write(f"{key} = {', '.join(str(v) for v in value)}\n")
                elif isinstance(value, str):
                    f.write(f'{key} = "{value}"\n')
                else:
                    f.write(f"{key} = {value}\n")

    def load_from_env(self) -> Dict[str, Any]:
        """Load configuration from environment variables.

        Returns:
            Dictionary of config values from environment.
        """
        result: Dict[str, Any] = {}
        for config_key, env_var in ENV_MAPPINGS.items():
            value = os.environ.get(env_var)
            if value is not None:
                # Try to parse value
                if value.lower() == "true":
                    result[config_key] = True
                elif value.lower() == "false":
                    result[config_key] = False
                else:
                    try:
                        if "." in value:
                            result[config_key] = float(value)
                        else:
                            result[config_key] = int(value)
                    except ValueError:
                        result[config_key] = value
        return result

    def load_config(self, cli_overrides: Optional[Dict[str, Any]] = None) -> Config:
        """Load configuration with proper precedence.

        Priority order (highest to lowest):
        1. CLI arguments
        2. Environment variables
        3. Local config (.pollix/config.yaml)
        4. Global config (~/.pollix/config.yaml)
        5. Default values

        Args:
            cli_overrides: Optional dictionary of CLI-provided values.

        Returns:
            Merged Config object.
        """
        if self._cached_config is not None and not cli_overrides:
            return self._cached_config

        # Start with defaults
        config = Config()

        # Layer 1: Global config
        global_data = self._read_yaml(self.GLOBAL_CONFIG_FILE)
        if global_data:
            config = config.merge(global_data)

        # Layer 2: Local config
        local_data = self._read_yaml(self.LOCAL_CONFIG_FILE)
        if local_data:
            config = config.merge(local_data)

        # Layer 3: Environment variables
        env_data = self.load_from_env()
        if env_data:
            config = config.merge(env_data)

        # Layer 4: CLI overrides (highest priority)
        if cli_overrides:
            config = config.merge({k: v for k, v in cli_overrides.items() if v is not None})

        self._cached_config = config
        return config

    def save_global_config(self, config: Config) -> None:
        """Save configuration to global config file.

        Args:
            config: Configuration to save.
        """
        data = config.to_dict()
        # Don't save empty API key
        if not data.get("api_key"):
            data.pop("api_key", None)
        self._write_yaml(self.GLOBAL_CONFIG_FILE, data)

    def save_local_config(self, config: Config) -> None:
        """Save configuration to local config file.

        Args:
            config: Configuration to save.
        """
        self._write_yaml(self.LOCAL_CONFIG_FILE, config.to_dict())

    def init_global_config(self, interactive: bool = True) -> Config:
        """Initialize global configuration.

        Args:
            interactive: If True, prompt user for values.

        Returns:
            The created Config.
        """
        self._ensure_dir(self.GLOBAL_CONFIG_DIR)

        if interactive:
            print("Welcome to Pollix! Let's set up your configuration.\n")

            api_key = input("Enter your Pollination API key (or press Enter to skip): ").strip()

            model = input(f"Default model [{DEFAULT_CONFIG['default_model']}]: ").strip()
            if not model:
                model = DEFAULT_CONFIG["default_model"]

            temp_input = input(f"Default temperature (0.0-1.0) [{DEFAULT_CONFIG['temperature']}]: ").strip()
            temperature = float(temp_input) if temp_input else DEFAULT_CONFIG["temperature"]

            config = Config(
                api_key=api_key,
                default_model=model,
                temperature=temperature,
            )
        else:
            config = Config()

        self.save_global_config(config)
        return config

    def init_local_config(self, interactive: bool = True) -> Config:
        """Initialize local configuration.

        Args:
            interactive: If True, prompt user for values.

        Returns:
            The created Config.
        """
        self._ensure_dir(self.LOCAL_CONFIG_DIR)

        # Create .gitignore for .pollix directory
        gitignore = self.LOCAL_CONFIG_DIR / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("*\n", encoding="utf-8")

        if interactive:
            print(f"Setting up local config in {self.LOCAL_CONFIG_DIR}\n")

            model = input("Project-specific model (or press Enter to use global default): ").strip()
            context_mode = input("Default context mode [auto]: ").strip()

            data: Dict[str, Any] = {}
            if model:
                data["default_model"] = model
            if context_mode:
                data["default_context_mode"] = context_mode

            config = Config(**data) if data else Config()
        else:
            config = Config()

        self.save_local_config(config)
        return config

    def invalidate_cache(self) -> None:
        """Clear the cached configuration."""
        self._cached_config = None
