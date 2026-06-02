"""Project initialization command for pollix configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from pollix.utils.config import Config, ConfigManager
from pollix.utils.render import Render


def init_command(
    global_config: bool = typer.Option(
        False, "--global", "-g",
        help="Create global configuration in ~/.pollix/",
    ),
    local_config: bool = typer.Option(
        False, "--local", "-l",
        help="Create local configuration in ./.pollix/",
    ),
    interactive: bool = typer.Option(
        True, "--interactive/--no-interactive",
        help="Interactive setup with prompts.",
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key",
        help="Pollination API key (for non-interactive setup).",
    ),
    model: Optional[str] = typer.Option(
        None, "--model", "-m",
        help="Default model.",
    ),
    temperature: Optional[float] = typer.Option(
        None, "--temperature",
        help="Default temperature.",
    ),
    force: bool = typer.Option(
        False, "--force",
        help="Overwrite existing configuration.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="Verbose output.",
    ),
    debug: bool = typer.Option(
        False, "--debug",
        help="Debug mode.",
    ),
) -> None:
    """Initialize pollix configuration.

    Sets up global (~/.pollix/) or local (.pollix/) configuration files
    with your preferences and API credentials.

    Examples:
        pollix init --global              # Interactive global setup
        pollix init --global --no-interactive --api-key=xxx
        pollix init --local               # Local project setup
        pollix init -g -f                 # Force overwrite global config
    """
    config_manager = ConfigManager()
    render = Render(verbose=verbose, debug=debug)

    # Default to global if neither specified
    if not global_config and not local_config:
        global_config = True

    # Global configuration
    if global_config:
        global_dir = config_manager.global_dir
        global_file = config_manager.global_file

        # Check for existing config
        if global_file.exists() and not force:
            if interactive:
                overwrite = render.confirm(
                    f"Global config already exists at {global_file}. Overwrite?",
                    default=False,
                )
                if not overwrite:
                    render.print_info("Keeping existing configuration.")
                    return
            else:
                render.print_warning(f"Global config exists. Use --force to overwrite.")
                return

        if interactive:
            render.rule("Global Configuration Setup")
            render.print_info(f"Configuration will be saved to: {global_file}")
            render.print()

            # API Key
            if api_key:
                key = api_key
            else:
                key = render.prompt(
                    "Enter your Pollination API key (get one at https://pollination.ai)",
                )

            # Model
            models = ["gemma-4", "gemma-4-2b", "gemma-4-4b", "gemma-4-9b", "gemma-4-27b"]
            if model:
                selected_model = model
            else:
                render.print()
                render.print_info("Available models:")
                for i, m in enumerate(models, 1):
                    marker = " (recommended)" if m == "gemma-4" else ""
                    render.print(f"  {i}. {m}{marker}")
                render.print()
                model_choice = render.prompt(
                    "Select default model", default="gemma-4",
                )
                # Allow selection by number or name
                try:
                    idx = int(model_choice) - 1
                    selected_model = models[idx] if 0 <= idx < len(models) else model_choice
                except ValueError:
                    selected_model = model_choice

            # Temperature
            if temperature is not None:
                temp = temperature
            else:
                temp_input = render.prompt(
                    "Default temperature (0.0 = focused, 1.0 = creative)",
                    default="0.7",
                )
                try:
                    temp = float(temp_input)
                except ValueError:
                    temp = 0.7

            # Theme
            theme = render.prompt("Theme (dark/light)", default="dark").lower()

            # Context mode
            modes = ["minimal", "auto", "full", "files"]
            render.print_info("Context modes:")
            render.print("  minimal - Just your query")
            render.print("  auto    - Auto-detect relevant files (default)")
            render.print("  full    - Include entire project")
            render.print("  files   - Only specified files")
            ctx_mode = render.prompt("Default context mode", default="auto")

            # Create config
            new_config = Config(
                api_key=key,
                default_model=selected_model,
                temperature=temp,
                theme=theme if theme in ("dark", "light") else "dark",
                default_context_mode=ctx_mode if ctx_mode in modes else "auto",
            )
        else:
            # Non-interactive
            if not api_key:
                render.print_error("API key required for non-interactive setup. Use --api-key.")
                raise typer.Exit(1)

            new_config = Config(
                api_key=api_key,
                default_model=model or "gemma-4",
                temperature=temperature if temperature is not None else 0.7,
            )

        # Save
        config_manager.save_global_config(new_config)
        render.print_success(f"Global configuration saved to {global_file}")

        # Security notice
        render.print()
        render.print_info("Security note: Your API key is stored in plain text.")
        render.print_info(f"Ensure {global_dir} has proper permissions.")

    # Local configuration
    if local_config:
        local_dir = config_manager.local_dir
        local_file = config_manager.local_file

        if local_file.exists() and not force:
            if interactive:
                overwrite = render.confirm(
                    f"Local config already exists at {local_file}. Overwrite?",
                    default=False,
                )
                if not overwrite:
                    render.print_info("Keeping existing local configuration.")
                    return
            else:
                render.print_warning(f"Local config exists. Use --force to overwrite.")
                return

        if interactive:
            render.rule("Local Project Configuration")
            render.print_info(f"Configuration will be saved to: {local_file}")
            render.print()

            # Project-specific settings
            project_model = render.prompt(
                "Project-specific model (leave empty to use global default)",
            )
            project_ctx = render.prompt(
                "Project context mode (minimal/auto/full/files, leave empty for global default)",
            )

            data = {}
            if project_model:
                data["default_model"] = project_model
            if project_ctx:
                data["default_context_mode"] = project_ctx

            local_config_obj = Config(**data) if data else Config()
        else:
            local_config_obj = Config()

        config_manager.save_local_config(local_config_obj)
        render.print_success(f"Local configuration saved to {local_file}")

        # Set up .gitignore
        gitignore = local_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("*\n", encoding="utf-8")
            render.print_verbose("Created .pollix/.gitignore")

    render.print()
    render.print_success("Setup complete! Try: pollix chat 'Hello!'")
