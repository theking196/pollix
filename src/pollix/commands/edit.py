"""AI-assisted file editing command with diff preview and backup support."""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import typer

from pollix.api.client import PollinationClient
from pollix.fs.tools import read_file
from pollix.utils.config import Config, ConfigManager
from pollix.utils.render import Render


# Prompt template for edit requests
EDIT_PROMPT_TEMPLATE = """You are an expert code editor. Your task is to modify the given file according to the user's instruction.

## Guidelines:
- Provide changes using SEARCH/REPLACE blocks
- SEARCH must match the original text exactly (including whitespace)
- If making multiple changes, provide them in order from top to bottom
- If the instruction is ambiguous, make the most reasonable change and explain your reasoning
- Only change what's necessary to fulfill the instruction

## Response Format:
Provide your changes in this exact format:

```
SEARCH:
<exact original text to find>
REPLACE:
<new text to replace with>
```

If no changes are needed, respond with "No changes needed" and explain why.

## File Content:
```{lang}
{content}
```

## Instruction:
{instruction}

## Your Changes:
"""


def _parse_search_replace(text: str) -> List[Tuple[str, str]]:
    """Parse SEARCH/REPLACE blocks from the AI response.

    Args:
        text: AI response text.

    Returns:
        List of (search, replace) tuples.
    """
    changes = []

    # Pattern: SEARCH:\n<content>\nREPLACE:\n<content>
    pattern = re.compile(
        r'SEARCH:\s*\n?(.*?)\n?REPLACE:\s*\n?(.*?)(?=\n?SEARCH:|\Z)',
        re.DOTALL,
    )

    for match in pattern.finditer(text):
        search = match.group(1).strip('\n')
        replace = match.group(2).strip('\n')
        if search:
            changes.append((search, replace))

    # Also try code block format
    if not changes:
        block_pattern = re.compile(
            r'```\s*(?:search/replace)?\s*\n'
            r'(?://\s*)?SEARCH:\s*\n?(.*?)\n'
            r'(?://\s*)?REPLACE:\s*\n?(.*?)\n'
            r'```',
            re.DOTALL,
        )
        for match in block_pattern.finditer(text):
            search = match.group(1).strip('\n')
            replace = match.group(2).strip('\n')
            if search:
                changes.append((search, replace))

    return changes


def _parse_unified_diff(text: str) -> List[Tuple[str, str]]:
    """Try to parse unified diff format.

    Args:
        text: Diff text.

    Returns:
        List of (search, replace) tuples.
    """
    changes = []
    lines = text.split('\n')

    i = 0
    while i < len(lines):
        if lines[i].startswith('@@'):
            # Start of hunk
            i += 1
            original_lines = []
            modified_lines = []

            while i < len(lines) and not lines[i].startswith('@@'):
                if lines[i].startswith('-'):
                    original_lines.append(lines[i][1:])
                elif lines[i].startswith('+'):
                    modified_lines.append(lines[i][1:])
                elif lines[i].startswith('\\'):
                    pass  # No newline marker
                else:
                    # Context line
                    original_lines.append(lines[i])
                    modified_lines.append(lines[i])
                i += 1

            if original_lines or modified_lines:
                search = '\n'.join(original_lines)
                replace = '\n'.join(modified_lines)
                changes.append((search, replace))
        else:
            i += 1

    return changes


def _apply_changes(content: str, changes: List[Tuple[str, str]]) -> str:
    """Apply SEARCH/REPLACE changes to content.

    Args:
        content: Original file content.
        changes: List of (search, replace) tuples.

    Returns:
        Modified content.

    Raises:
        ValueError: If a search pattern is not found.
    """
    result = content
    applied = 0
    failed = []

    for search, replace in changes:
        if search in result:
            result = result.replace(search, replace, 1)
            applied += 1
        else:
            failed.append(search[:100] + "..." if len(search) > 100 else search)

    if failed:
        failed_str = "\n".join(f"  - {f[:80]}" for f in failed)
        raise ValueError(f"Could not find {len(failed)} search pattern(s):\n{failed_str}")

    return result


def _create_backup(file_path: Path) -> Path:
    """Create a backup of the file.

    Args:
        file_path: Path to the file.

    Returns:
        Path to the backup file.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = file_path.parent / f"{file_path.name}.{timestamp}.bak"
    shutil.copy2(file_path, backup_path)
    return backup_path


def _detect_language(file_path: str) -> str:
    """Detect programming language from file extension.

    Args:
        file_path: File path.

    Returns:
        Language name.
    """
    ext_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".jsx": "jsx",
        ".tsx": "tsx",
        ".rs": "rust",
        ".go": "go",
        ".java": "java",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c",
        ".cs": "csharp",
        ".rb": "ruby",
        ".php": "php",
        ".swift": "swift",
        ".kt": "kotlin",
        ".scala": "scala",
        ".sh": "bash",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
        ".xml": "xml",
        ".html": "html",
        ".css": "css",
        ".md": "markdown",
        ".toml": "toml",
        ".ini": "ini",
    }
    return ext_map.get(Path(file_path).suffix.lower(), "text")


def edit_command(
    file: str = typer.Argument(
        ...,
        help="File to edit.",
    ),
    instruction: Optional[str] = typer.Argument(
        None,
        help="What to do with the file. If omitted, use --instruction flag.",
    ),
    instruction_flag: Optional[str] = typer.Option(
        None, "--instruction", "-i",
        help="Edit instruction (required if not provided as argument).",
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o",
        help="Output file (default: overwrite input file).",
    ),
    show_diff: bool = typer.Option(
        True, "--diff/--no-diff",
        help="Show diff preview before applying.",
    ),
    context_lines: int = typer.Option(
        3, "--context-lines",
        help="Lines of context around edits.",
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
        help="Model to use.",
    ),
    temperature: float = typer.Option(
        0.3, "--temperature",
        help="Temperature (lower = more focused edits).",
    ),
    max_tokens: int = typer.Option(
        4096, "--max-tokens",
        help="Maximum tokens for response.",
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key",
        help="Pollination API key.",
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
    """Edit a file with AI assistance.

    Sends the file content and instruction to the AI, then applies
    the suggested changes with optional diff preview and backup.

    Examples:
        pollix edit config.yaml -i "add redis section with port 6379"
        pollix edit main.py "refactor to use async/await" --diff
        pollix edit app.py "add error handling" --dry-run --no-backup
    """
    # Resolve instruction
    edit_instruction = instruction or instruction_flag
    if not edit_instruction:
        render = Render()
        render.print_error("No instruction provided. Use positional argument or --instruction/-i flag.")
        raise typer.Exit(1)

    # Load configuration
    config_manager = ConfigManager()
    cli_overrides = {
        k: v for k, v in {
            "api_key": api_key,
            "default_model": model,
            "verbose": verbose,
            "debug": debug,
        }.items() if v is not None
    }
    config = config_manager.load_config(cli_overrides)

    render = Render(theme=config.theme, verbose=config.verbose, debug=config.debug)

    if not config.api_key:
        render.print_error("No API key configured. Set POLLINATIONS_KEY or run 'pollix init --global'")
        raise typer.Exit(1)

    # Resolve file path
    file_path = Path(file)
    if not file_path.exists():
        render.print_error(f"File not found: {file}")
        raise typer.Exit(1)

    if not file_path.is_file():
        render.print_error(f"Not a file: {file}")
        raise typer.Exit(1)

    # Read original content
    try:
        original_content = read_file(file_path, max_size=500_000)
    except Exception as e:
        render.print_error(f"Could not read file: {e}")
        raise typer.Exit(1)

    lang = _detect_language(str(file_path))

    render.print_info(f"Editing: [bold]{file_path}[/bold]")
    render.print_verbose(f"Language: {lang}")
    render.print_verbose(f"File size: {len(original_content)} characters")

    # Build prompt
    prompt = EDIT_PROMPT_TEMPLATE.format(
        lang=lang,
        content=original_content,
        instruction=edit_instruction,
    )

    # Send request
    try:
        client = PollinationClient(api_key=config.api_key)

        with render.status("Generating edits..."):
            response = client.chat(
                message=prompt,
                model=config.default_model,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        response_text = response.content

        # Parse changes
        changes = _parse_search_replace(response_text)

        if not changes:
            # Try unified diff format
            changes = _parse_unified_diff(response_text)

        if not changes:
            # Check if AI said no changes needed
            if "no changes needed" in response_text.lower():
                render.print_info("No changes suggested by the AI.")
                render.print_markdown(response_text)
                return

            render.print_warning("Could not parse edit instructions from AI response.")
            render.print_markdown(response_text)
            return

        render.print_verbose(f"Found {len(changes)} change(s)")

        # Show changes
        try:
            modified_content = _apply_changes(original_content, changes)
        except ValueError as e:
            render.print_error(f"Could not apply changes: {e}")
            render.print_markdown(response_text)
            return

        # Show diff
        if show_diff:
            render.rule("Preview")
            render.print_file_diff(str(file_path), original_content, modified_content)

        # Apply or dry-run
        if dry_run:
            render.print_info("Dry run - no changes applied.")
            return

        # Confirm if interactive
        if not render.confirm("Apply these changes?", default=True):
            render.print_info("Changes discarded.")
            return

        # Create backup
        if backup:
            backup_path = _create_backup(file_path)
            render.print_verbose(f"Backup created: {backup_path}")

        # Write changes
        output_path = Path(output) if output else file_path
        output_path.write_text(modified_content, encoding="utf-8")

        render.print_success(f"Changes applied to {output_path}")

        if output and output != str(file_path):
            render.print_info(f"Original preserved at {file_path}")

        client.close()

    except Exception as e:
        render.print_error(f"Edit failed: {e}")
        raise typer.Exit(1)
