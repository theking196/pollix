"""Main CLI entry point for pollix.

Uses Typer to define the command structure and dispatches to individual
command modules. Provides global options like --verbose and --version.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich import print as rich_print

from pollix import __version__
from pollix.commands.chat import chat_command
from pollix.commands.edit import edit_command
from pollix.commands.init import init_command
from pollix.commands.review import review_command
from pollix.utils.config import ConfigManager
from pollix.utils.render import Render

# Create the main Typer app
app = typer.Typer(
    name="pollix",
    help="Unofficial CLI for Pollination AI with file system access and project context awareness.",
    no_args_is_help=True,
    invoke_without_command=True,
    add_completion=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)


# ── Callback for global options ──────────────────────────────────────────

@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V",
        help="Show version and exit.",
        is_eager=True,
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="Enable verbose output.",
    ),
    debug: bool = typer.Option(
        False, "--debug",
        help="Enable debug mode with detailed output.",
    ),
    config_file: Optional[str] = typer.Option(
        None, "--config",
        help="Path to configuration file.",
    ),
) -> None:
    """Pollix - Unofficial CLI for Pollination AI.

    A powerful command-line interface for Pollination AI that provides
    file system access, project context awareness, and advanced developer
    workflows for code review, editing, and chat.
    """
    if version:
        rich_print(f"[bold cyan]pollix[/bold cyan] version [bold]{__version__}[/bold]")
        rich_print("Unofficial CLI for Pollination AI")
        raise typer.Exit()


# ── Register commands ────────────────────────────────────────────────────

@app.command("chat")
def chat(
    message: Optional[str] = typer.Argument(
        None,
        help="Message to send. Use '-' for stdin. Omit for interactive mode.",
    ),
    model: Optional[str] = typer.Option(
        None, "--model", "-m",
        help="Model name (default: from config).",
    ),
    file: Optional[list[str]] = typer.Option(
        None, "--file", "-f",
        help="Include specific file(s). Repeatable.",
    ),
    context_mode: Optional[str] = typer.Option(
        None, "--context-mode",
        help="Context mode: minimal, auto, full, files.",
    ),
    stream: Optional[bool] = typer.Option(
        None, "--stream/--no-stream",
        help="Enable streaming output.",
    ),
    system: Optional[str] = typer.Option(
        None, "--system", "-s",
        help="Custom system prompt.",
    ),
    history: int = typer.Option(
        10, "--history", "-h",
        help="Previous messages to include.",
    ),
    save: Optional[str] = typer.Option(
        None, "--save",
        help="Save conversation thread name.",
    ),
    load: Optional[str] = typer.Option(
        None, "--load",
        help="Load previous conversation.",
    ),
    temperature: Optional[float] = typer.Option(
        None, "--temperature",
        help="Sampling temperature (0.0 - 1.0).",
    ),
    max_tokens: Optional[int] = typer.Option(
        None, "--max-tokens",
        help="Maximum response tokens.",
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key",
        help="Pollination API key.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
    ),
    debug: bool = typer.Option(
        False, "--debug",
    ),
) -> None:
    """Chat with Pollination AI.

    Send messages and receive AI-generated responses. Supports streaming,
    file attachments, conversation history, and multiple context modes.

    [bold]Examples:[/bold]
        pollix chat "Hello!"
        pollix chat "Explain this code" -f src/main.py
        echo "Hello" | pollix chat -
        pollix chat  # Interactive mode
    """
    chat_command(
        message=message,
        model=model,
        file=file,
        context_mode=context_mode,
        stream=stream,
        system=system,
        history_count=history,
        save=save,
        load=load,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key,
        verbose=verbose,
        debug=debug,
    )


@app.command("review")
def review(
    path: str = typer.Argument(
        ".",
        help="Path to review (file or directory).",
    ),
    review_type: str = typer.Option(
        "all", "--type", "-t",
        help="Review type: code, security, performance, docs, all.",
    ),
    file: Optional[list[str]] = typer.Option(
        None, "--file", "-f",
        help="Specific files to review.",
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o",
        help="Save review to file.",
    ),
    diff: bool = typer.Option(
        False, "--diff",
        help="Review only unstaged git changes.",
    ),
    inline: bool = typer.Option(
        False, "--inline",
        help="Show inline suggestions.",
    ),
    model: Optional[str] = typer.Option(
        None, "--model", "-m",
    ),
    temperature: float = typer.Option(
        0.3, "--temperature",
    ),
    max_tokens: int = typer.Option(
        4096, "--max-tokens",
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
    ),
    debug: bool = typer.Option(
        False, "--debug",
    ),
) -> None:
    """Review code with AI-powered analysis.

    Performs automated code review for quality, security, performance,
    or documentation. Can review files, directories, or git diffs.

    [bold]Examples:[/bold]
        pollix review src/
        pollix review src/ --type security
        pollix review --diff
        pollix review main.py -o review.md
    """
    review_command(
        path=path,
        review_type=review_type,
        file=file,
        output=output,
        diff=diff,
        inline=inline,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key,
        verbose=verbose,
        debug=debug,
    )


@app.command("edit")
def edit(
    file: str = typer.Argument(
        ...,
        help="File to edit.",
    ),
    instruction: Optional[str] = typer.Argument(
        None,
        help="What to do. Use --instruction/-i if not provided.",
    ),
    instruction_flag: Optional[str] = typer.Option(
        None, "--instruction", "-i",
        help="Edit instruction.",
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o",
        help="Output file (default: overwrite).",
    ),
    show_diff: bool = typer.Option(
        True, "--diff/--no-diff",
        help="Show diff preview.",
    ),
    context_lines: int = typer.Option(
        3, "--context-lines",
        help="Context lines around edits.",
    ),
    backup: bool = typer.Option(
        True, "--backup/--no-backup",
        help="Create backup before editing.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Show changes without applying.",
    ),
    model: Optional[str] = typer.Option(
        None, "--model", "-m",
    ),
    temperature: float = typer.Option(
        0.3, "--temperature",
    ),
    max_tokens: int = typer.Option(
        4096, "--max-tokens",
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
    ),
    debug: bool = typer.Option(
        False, "--debug",
    ),
) -> None:
    """Edit files with AI assistance.

    Sends file content and instructions to the AI, then applies the
    suggested changes with optional diff preview and automatic backup.

    [bold]Examples:[/bold]
        pollix edit config.yaml -i "add redis section with port 6379"
        pollix edit main.py "refactor to use async" --diff
        pollix edit app.py "add error handling" --dry-run
    """
    edit_command(
        file=file,
        instruction=instruction,
        instruction_flag=instruction_flag,
        output=output,
        show_diff=show_diff,
        context_lines=context_lines,
        backup=backup,
        dry_run=dry_run,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key,
        verbose=verbose,
        debug=debug,
    )


@app.command("init")
def init(
    global_config: bool = typer.Option(
        False, "--global", "-g",
        help="Create global configuration.",
    ),
    local_config: bool = typer.Option(
        False, "--local", "-l",
        help="Create local project configuration.",
    ),
    interactive: bool = typer.Option(
        True, "--interactive/--no-interactive",
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key",
    ),
    model: Optional[str] = typer.Option(
        None, "--model", "-m",
    ),
    temperature: Optional[float] = typer.Option(
        None, "--temperature",
    ),
    force: bool = typer.Option(
        False, "--force",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
    ),
    debug: bool = typer.Option(
        False, "--debug",
    ),
) -> None:
    """Initialize pollix configuration.

    Sets up global (~/.pollix/) or local (.pollix/) configuration with
    your API credentials and preferences.

    [bold]Examples:[/bold]
        pollix init --global
        pollix init --global --no-interactive --api-key=xxx
        pollix init --local
    """
    init_command(
        global_config=global_config,
        local_config=local_config,
        interactive=interactive,
        api_key=api_key,
        model=model,
        temperature=temperature,
        force=force,
        verbose=verbose,
        debug=debug,
    )


# ── Error handling ───────────────────────────────────────────────────────

def _handle_error(error: Exception) -> None:
    """Handle uncaught exceptions gracefully.

    Args:
        error: The exception that was raised.
    """
    render = Render()

    if isinstance(error, typer.Exit):
        raise error

    render.print_error(f"Unexpected error: {error}")

    import traceback
    traceback_str = traceback.format_exc()
    render.print_debug(traceback_str)


def cli_entry() -> None:
    """Entry point for the CLI application."""
    try:
        app()
    except KeyboardInterrupt:
        rich_print("\n[yellow]Interrupted by user.[/yellow]")
        sys.exit(130)
    except Exception as e:
        _handle_error(e)
        sys.exit(1)


# ── Module entry point ───────────────────────────────────────────────────

if __name__ == "__main__":
    cli_entry()
