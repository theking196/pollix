"""Rich output formatting for pollix.

Provides utilities for console output, markdown rendering, syntax highlighting,
diff display, panels, spinners, and progress indicators.
"""

from __future__ import annotations

import sys
from typing import Iterator, List, Optional

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.status import Status
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# Custom theme for pollix
POLLIX_THEME = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "red bold",
    "success": "green bold",
    "debug": "dim cyan",
    "prompt": "bold blue",
    "token": "bright_white",
    "spinner": "cyan",
})


class Render:
    """Rich console rendering utilities.

    Provides methods for formatted console output including markdown rendering,
    syntax highlighting, diff display, and progress indicators.

    Example:
        >>> render = Render()
        >>> render.print_markdown("# Hello\nThis is **bold**.")
        >>> render.print_error("Something went wrong!")
    """

    def __init__(self, theme: str = "dark", verbose: bool = False, debug: bool = False) -> None:
        """Initialize the renderer.

        Args:
            theme: Color theme ("dark" or "light").
            verbose: Enable verbose output.
            debug: Enable debug output.
        """
        self.verbose = verbose
        self.debug = debug
        self._theme_name = theme

        # Create console with appropriate theme
        self.console = Console(
            theme=POLLIX_THEME,
            color_system="auto",
            force_terminal=True,
        )

        # Create error console
        self.error_console = Console(
            theme=POLLIX_THEME,
            stderr=True,
            color_system="auto",
            force_terminal=True,
        )

    # ── Basic Output ──────────────────────────────────────────────────────

    def print(self, *args, **kwargs) -> None:
        """Print to console."""
        self.console.print(*args, **kwargs)

    def print_error(self, message: str, exit_code: int = 1) -> None:
        """Print an error message and optionally exit.

        Args:
            message: Error message to display.
            exit_code: Exit code (0 = don't exit).
        """
        panel = Panel(
            Text(message, style="error"),
            title="[error]Error[/error]",
            border_style="error",
        )
        self.error_console.print(panel)

    def print_warning(self, message: str) -> None:
        """Print a warning message.

        Args:
            message: Warning message to display.
        """
        panel = Panel(
            Text(message, style="warning"),
            title="[warning]Warning[/warning]",
            border_style="warning",
        )
        self.console.print(panel)

    def print_success(self, message: str) -> None:
        """Print a success message.

        Args:
            message: Success message to display.
        """
        self.console.print(f"[success]✓[/success] {message}")

    def print_info(self, message: str) -> None:
        """Print an info message.

        Args:
            message: Info message to display.
        """
        self.console.print(f"[info]ℹ[/info] {message}")

    def print_debug(self, message: str) -> None:
        """Print a debug message (only if debug mode is enabled).

        Args:
            message: Debug message to display.
        """
        if self.debug:
            self.console.print(f"[debug][DEBUG] {message}[/debug]")

    def print_verbose(self, message: str) -> None:
        """Print a verbose message (only if verbose mode is enabled).

        Args:
            message: Verbose message to display.
        """
        if self.verbose:
            self.console.print(f"[dim]{message}[/dim]")

    # ── Markdown & Syntax ─────────────────────────────────────────────────

    def print_markdown(self, text: str, soft_wrap: bool = True) -> None:
        """Print markdown-formatted text.

        Args:
            text: Markdown text to render.
            soft_wrap: Enable soft wrapping.
        """
        md = Markdown(text)
        self.console.print(md, soft_wrap=soft_wrap)

    def print_code(self, code: str, language: str = "python", title: Optional[str] = None) -> None:
        """Print syntax-highlighted code.

        Args:
            code: Code to display.
            language: Programming language for highlighting.
            title: Optional title for the code block.
        """
        syntax = Syntax(
            code,
            language,
            theme="monokai" if self._theme_name == "dark" else "default",
            line_numbers=True,
            word_wrap=True,
        )

        if title:
            panel = Panel(syntax, title=title, border_style="dim")
            self.console.print(panel)
        else:
            self.console.print(syntax)

    def print_json(self, data: dict, title: Optional[str] = None) -> None:
        """Print formatted JSON.

        Args:
            data: Dictionary to format as JSON.
            title: Optional panel title.
        """
        import json

        code = json.dumps(data, indent=2, default=str)
        self.print_code(code, language="json", title=title)

    # ── Diff Display ──────────────────────────────────────────────────────

    def print_diff(self, original: str, modified: str, title: Optional[str] = None) -> None:
        """Print a colored diff between two texts.

        Args:
            original: Original text.
            modified: Modified text.
            title: Optional title for the diff.
        """
        import difflib

        original_lines = original.splitlines(keepends=True)
        modified_lines = modified.splitlines(keepends=True)

        diff = difflib.unified_diff(
            original_lines,
            modified_lines,
            fromfile="original",
            tofile="modified",
            lineterm="",
        )

        diff_text = "".join(diff)

        if diff_text:
            self.print_code(diff_text, language="diff", title=title or "Changes")
        else:
            self.print_info("No changes detected.")

    def print_file_diff(self, file_path: str, original: str, modified: str) -> None:
        """Print a diff for a specific file.

        Args:
            file_path: Path to the file.
            original: Original content.
            modified: Modified content.
        """
        self.print_diff(original, modified, title=file_path)

    # ── Panels & Tables ───────────────────────────────────────────────────

    def print_panel(self, content: str, title: Optional[str] = None, border_style: str = "blue") -> None:
        """Print content in a panel.

        Args:
            content: Content to display.
            title: Panel title.
            border_style: Border color.
        """
        panel = Panel(content, title=title, border_style=border_style)
        self.console.print(panel)

    def print_table(self, data: List[dict], title: Optional[str] = None) -> None:
        """Print data as a formatted table.

        Args:
            data: List of dictionaries (keys become columns).
            title: Optional table title.
        """
        if not data:
            self.print_info("No data to display.")
            return

        table = Table(title=title, show_header=True, header_style="bold magenta")

        # Add columns from first row
        for key in data[0].keys():
            table.add_column(str(key), overflow="fold")

        # Add rows
        for row in data:
            table.add_row(*[str(v) for v in row.values()])

        self.console.print(table)

    # ── Streaming Output ──────────────────────────────────────────────────

    def stream_response(self, token_iterator: Iterator[str], use_markdown: bool = True) -> str:
        """Stream tokens to the console in real-time.

        Args:
            token_iterator: Iterator yielding text tokens.
            use_markdown: Whether to render as markdown when complete.

        Returns:
            Complete response text.
        """
        full_text = ""

        with Live(
            console=self.console,
            refresh_per_second=15,
            transient=False,
        ) as live:
            for token in token_iterator:
                full_text += token

                if use_markdown:
                    # Update live display with markdown
                    md = Markdown(full_text)
                    live.update(md)
                else:
                    # Plain text streaming
                    live.update(Text(full_text))

        return full_text

    def stream_with_spinner(self, token_iterator: Iterator[str]) -> str:
        """Stream tokens with a spinner indicator.

        Args:
            token_iterator: Iterator yielding text tokens.

        Returns:
            Complete response text.
        """
        full_text = ""
        spinner = Spinner("dots", text="[spinner]Thinking...[/spinner]")

        with Live(spinner, console=self.console, refresh_per_second=15) as live:
            for token in token_iterator:
                full_text += token
                md = Markdown(full_text)
                live.update(md)

        return full_text

    # ── Progress & Status ─────────────────────────────────────────────────

    def status(self, message: str, spinner: str = "dots") -> Status:
        """Create a status/spinner context.

        Args:
            message: Status message.
            spinner: Spinner style.

        Returns:
            Status context manager.
        """
        return self.console.status(f"[spinner]{message}[/spinner]", spinner=spinner)

    def print_progress(self, current: int, total: int, description: str = "Progress") -> None:
        """Print a progress bar.

        Args:
            current: Current progress.
            total: Total items.
            description: Progress description.
        """
        if total == 0:
            return

        percentage = (current / total) * 100
        filled = int(percentage / 5)  # 20 chars wide
        bar = "█" * filled + "░" * (20 - filled)

        self.console.print(f"\r{description}: [{bar}] {percentage:.1f}% ({current}/{total})", end="")

        if current >= total:
            self.console.print()  # New line when complete

    # ── Prompts ───────────────────────────────────────────────────────────

    def prompt(self, message: str, default: Optional[str] = None) -> str:
        """Prompt user for input.

        Args:
            message: Prompt message.
            default: Default value.

        Returns:
            User input.
        """
        prompt_text = f"[prompt]{message}[/prompt]"
        if default:
            prompt_text += f" [dim]({default})[/dim]"
        prompt_text += ": "

        return self.console.input(prompt_text) or default or ""

    def confirm(self, message: str, default: bool = False) -> bool:
        """Ask user for confirmation.

        Args:
            message: Confirmation message.
            default: Default answer.

        Returns:
            True if confirmed, False otherwise.
        """
        suffix = " [Y/n]" if default else " [y/N]"
        response = self.console.input(f"[prompt]{message}[/prompt]{suffix}: ").strip().lower()

        if not response:
            return default

        return response in ("y", "yes")

    # ── Review Output ─────────────────────────────────────────────────────

    def print_review_result(self, result: dict) -> None:
        """Print a code review result.

        Args:
            result: Review result dictionary.
        """
        severity_styles = {
            "critical": "bold red",
            "warning": "yellow",
            "suggestion": "blue",
            "praise": "green",
        }

        severity = result.get("severity", "suggestion")
        style = severity_styles.get(severity, "white")

        title = f"[{style}]{severity.upper()}[/{style}]"
        message = result.get("message", "")
        file_path = result.get("file", "")
        line = result.get("line", "")

        content = message
        if file_path:
            location = f"{file_path}"
            if line:
                location += f":{line}"
            content = f"[dim]{location}[/dim]\n{message}"

        if "suggestion" in result and result["suggestion"]:
            content += f"\n\n[bold]Suggestion:[/bold]\n{result['suggestion']}"

        panel = Panel(content, title=title, border_style=style)
        self.console.print(panel)

    def print_edit_preview(self, file_path: str, original: str, modified: str, context_lines: int = 3) -> None:
        """Print a preview of an edit.

        Args:
            file_path: Path to the edited file.
            original: Original content.
            modified: Modified content.
            context_lines: Number of context lines to show.
        """
        self.print_diff(original, modified, title=f"Edit Preview: {file_path}")

    # ── Utility ───────────────────────────────────────────────────────────

    def clear(self) -> None:
        """Clear the console."""
        self.console.clear()

    def rule(self, title: Optional[str] = None) -> None:
        """Print a horizontal rule.

        Args:
            title: Optional title for the rule.
        """
        self.console.rule(title=title)

    @property
    def width(self) -> int:
        """Get console width."""
        return self.console.width

    def print_banner(self) -> None:
        """Print the pollix banner."""
        banner = r"""
[bold cyan]  ____      _ _            [/bold cyan]
[bold cyan] |  _ \ ___| (_) _____   __[/bold cyan]
[bold cyan] | |_) / _ \ | |/ _ \ \ / /[/bold cyan]
[bold cyan] |  __/  __/ | | (_) \ V / [/bold cyan]
[bold cyan] |_|   \___|_|_|\___/ \_/  [/bold cyan]
[bold cyan]                           [/bold cyan]
[dim]Unofficial CLI for Pollination AI[/dim]
        """
        self.console.print(banner)
