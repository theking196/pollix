"""Code review command for automated code analysis using Pollination AI."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional

import typer

from pollix.api.client import PollinationClient
from pollix.fs.tools import find_files, get_project_tree, grep_files, is_sensitive_file, is_text_file, read_file
from pollix.utils.config import Config, ConfigManager
from pollix.utils.render import Render


# Review type prompts
REVIEW_PROMPTS = {
    "code": (
        "You are a senior software engineer performing a code review. "
        "Analyze the provided code for:\n"
        "- Code quality and readability\n"
        "- Potential bugs or logic errors\n"
        "- Performance issues\n"
        "- Adherence to language best practices\n"
        "- Error handling completeness\n\n"
        "Format your response as a structured review with severity levels:\n"
        "- **Critical**: Bugs or serious issues that must be fixed\n"
        "- **Warning**: Potential problems or anti-patterns\n"
        "- **Suggestion**: Improvements for better code quality\n"
        "- **Praise**: What the code does well\n\n"
        "For each issue, provide:\n"
        "1. Severity level\n"
        "2. Description of the issue\n"
        "3. Specific location (file and line if possible)\n"
        "4. Suggested fix with code example"
    ),
    "security": (
        "You are a security engineer performing a security audit. "
        "Analyze the provided code for security vulnerabilities:\n"
        "- Injection attacks (SQL, command, XSS)\n"
        "- Authentication and authorization flaws\n"
        "- Sensitive data exposure\n"
        "- Insecure dependencies\n"
        "- Input validation issues\n"
        "- Cryptographic weaknesses\n"
        "- Insecure file operations\n\n"
        "Format your response as a structured security review:\n"
        "- **Critical**: Severe vulnerabilities requiring immediate attention\n"
        "- **Warning**: Moderate security concerns\n"
        "- **Suggestion**: Security best practices and hardening recommendations\n\n"
        "For each finding, provide:\n"
        "1. Severity and CVSS score estimate if applicable\n"
        "2. Vulnerability description\n"
        "3. Affected code location\n"
        "4. Exploitation scenario (how it could be abused)\n"
        "5. Remediation with secure code example"
    ),
    "performance": (
        "You are a performance engineer analyzing code for optimization opportunities. "
        "Review the provided code for:\n"
        "- Algorithmic inefficiencies (time/space complexity)\n"
        "- Unnecessary computations or redundant operations\n"
        "- Memory leaks or excessive memory usage\n"
        "- Database query optimization\n"
        "- I/O bottlenecks\n"
        "- Caching opportunities\n"
        "- Async/concurrency improvements\n\n"
        "Format your response as a performance analysis:\n"
        "- **Critical**: Severe performance issues affecting usability\n"
        "- **Warning**: Noticeable performance impacts\n"
        "- **Suggestion**: Micro-optimizations and best practices\n\n"
        "For each issue, provide:\n"
        "1. Performance impact (e.g., O(n²) vs O(n))\n"
        "2. Current problematic code\n"
        "3. Optimized alternative with expected improvement"
    ),
    "docs": (
        "You are a technical writer reviewing code documentation. "
        "Analyze the provided code for documentation quality:\n"
        "- Missing docstrings or comments\n"
        "- Outdated or incorrect documentation\n"
        "- Unclear variable or function names\n"
        "- Complex logic without explanation\n"
        "- Missing README or setup instructions\n"
        "- API documentation gaps\n\n"
        "Format your response as a documentation review:\n"
        "- **Critical**: Missing critical documentation blocking usage\n"
        "- **Warning**: Important gaps in documentation\n"
        "- **Suggestion**: Improvements for clarity and completeness\n\n"
        "For each finding, provide:\n"
        "1. What's missing or incorrect\n"
        "2. Location in the codebase\n"
        "3. Suggested documentation text"
    ),
    "all": (
        "You are a senior software engineer performing a comprehensive code review. "
        "Analyze the provided code across multiple dimensions:\n\n"
        "**Code Quality**\n"
        "- Readability and maintainability\n"
        "- Potential bugs or logic errors\n"
        "- Error handling completeness\n"
        "- Test coverage indicators\n\n"
        "**Security**\n"
        "- Injection vulnerabilities\n"
        "- Input validation\n"
        "- Sensitive data handling\n"
        "- Authentication/authorization issues\n\n"
        "**Performance**\n"
        "- Algorithmic efficiency\n"
        "- Resource usage\n"
        "- Optimization opportunities\n\n"
        "**Documentation**\n"
        "- Code comments and docstrings\n"
        "- Naming clarity\n\n"
        "Format findings as:\n"
        "- **Critical**: Must fix\n"
        "- **Warning**: Should fix\n"
        "- **Suggestion**: Could improve\n"
        "- **Praise**: Well done\n\n"
        "For each finding, include file path, line number, and specific code suggestions."
    ),
}


def _get_git_diff() -> str:
    """Get unstaged git changes.

    Returns:
        Git diff output as string.
    """
    try:
        result = subprocess.run(
            ["git", "diff"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ""


def _get_file_extension_language(path: str) -> str:
    """Detect programming language from file extension.

    Args:
        path: File path.

    Returns:
        Language name for syntax highlighting.
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
        ".hpp": "cpp",
        ".cs": "csharp",
        ".rb": "ruby",
        ".php": "php",
        ".swift": "swift",
        ".kt": "kotlin",
        ".scala": "scala",
        ".r": "r",
        ".m": "objectivec",
        ".sh": "bash",
        ".bash": "bash",
        ".zsh": "zsh",
        ".ps1": "powershell",
        ".sql": "sql",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
        ".xml": "xml",
        ".html": "html",
        ".css": "css",
        ".scss": "scss",
        ".sass": "sass",
        ".md": "markdown",
        ".dockerfile": "dockerfile",
        ".makefile": "makefile",
        ".toml": "toml",
        ".ini": "ini",
        ".cfg": "ini",
    }

    ext = Path(path).suffix.lower()
    return ext_map.get(ext, "text")


def _collect_files(
    path: str,
    specific_files: Optional[List[str]],
    use_git_diff: bool,
    render: Render,
) -> List[str]:
    """Collect files to review.

    Args:
        path: Root path to review.
        specific_files: Specific files to review.
        use_git_diff: Use git diff instead of files.
        render: Renderer instance.

    Returns:
        List of file paths to review.
    """
    if use_git_diff:
        return ["git diff"]  # Special marker

    if specific_files:
        # Filter to only existing text files
        result = []
        for f in specific_files:
            p = Path(f)
            if p.exists() and p.is_file():
                try:
                    if is_text_file(p):
                        result.append(str(p))
                    else:
                        render.print_warning(f"Skipping binary file: {f}")
                except Exception:
                    result.append(str(p))  # Try anyway
            else:
                render.print_warning(f"File not found: {f}")
        return result

    # Collect from path
    target = Path(path)
    if target.is_file():
        return [str(target)]

    # Find code files
    code_extensions = [
        ".py", ".js", ".ts", ".jsx", ".tsx", ".rs", ".go", ".java", ".c", ".cpp",
        ".h", ".hpp", ".cs", ".rb", ".php", ".swift", ".kt", ".scala", ".r",
        ".sh", ".bash", ".zsh", ".ps1", ".sql", ".yaml", ".yml", ".json",
        ".html", ".css", ".scss", ".sass", ".md", ".toml", ".ini", ".cfg",
    ]

    files = []
    for ext in code_extensions:
        files.extend(find_files(f"**/*{ext}", path=str(target)))

    return sorted(set(files))[:50]  # Limit to 50 files


def review_command(
    path: str = typer.Argument(
        ".",
        help="Path to review (file or directory).",
    ),
    review_type: str = typer.Option(
        "all", "--type", "-t",
        help="Type of review (code, security, performance, docs, all).",
    ),
    file: Optional[List[str]] = typer.Option(
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
        help="Model to use.",
    ),
    temperature: float = typer.Option(
        0.3, "--temperature",
        help="Temperature for review (lower = more focused).",
    ),
    max_tokens: int = typer.Option(
        4096, "--max-tokens",
        help="Maximum tokens for review response.",
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
    """Review code with AI-powered analysis.

    Performs automated code review focusing on code quality, security,
    performance, or documentation based on the selected type.

    Examples:
        pollix review src/
        pollix review src/ --type security
        pollix review --diff
        pollix review main.py -o review.md
    """
    # Validate review type
    valid_types = list(REVIEW_PROMPTS.keys())
    if review_type not in valid_types:
        typer.echo(f"Invalid review type: {review_type}. Choose from: {', '.join(valid_types)}")
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

    # Handle git diff mode
    if diff:
        git_diff = _get_git_diff()
        if not git_diff:
            render.print_warning("No unstaged changes found or not in a git repository.")
            raise typer.Exit(0)

        render.print_info("Reviewing unstaged git changes...")

        prompt = (
            f"{REVIEW_PROMPTS[review_type]}\n\n"
            f"Please review the following git diff:\n\n"
            f"```diff\n{git_diff[:150000]}\n```"
        )

        _send_review(prompt, config, render, output)
        return

    # Collect files
    files_to_review = _collect_files(path, file, diff, render)

    if not files_to_review:
        render.print_warning("No files found to review.")
        raise typer.Exit(0)

    render.print_info(f"Reviewing {len(files_to_review)} files...")

    # Build review prompt with file contents
    file_sections = []
    for file_path in files_to_review:
        try:
            if file_path == "git diff":
                continue
            content = read_file(file_path, max_size=50000)
            lang = _get_file_extension_language(file_path)
            file_sections.append(f"### {file_path}\n```{lang}\n{content}\n```")
        except Exception as e:
            render.print_verbose(f"Could not read {file_path}: {e}")

    if not file_sections:
        render.print_warning("Could not read any files for review.")
        raise typer.Exit(0)

    # Add project tree for context
    try:
        tree = get_project_tree(path, max_depth=3)
    except Exception:
        tree = ""

    prompt_parts = [
        REVIEW_PROMPTS[review_type],
        "",
        "## Project Structure",
        f"```\n{tree}\n```" if tree else "",
        "",
        "## Files to Review",
        "",
        "\n\n".join(file_sections),
    ]

    if inline:
        prompt_parts.extend([
            "",
            "For each issue, provide the exact original code and the suggested fix in a search/replace format:",
            "```",
            "SEARCH:",
            "<original code>",
            "REPLACE:",
            "<fixed code>",
            "```",
        ])

    prompt = "\n".join(prompt_parts)

    # Truncate if too long
    max_prompt = 120000
    if len(prompt) > max_prompt:
        prompt = prompt[:max_prompt] + "\n\n[Additional files truncated due to length]"
        render.print_warning("Large review truncated. Consider reviewing specific files.")

    _send_review(prompt, config, render, output)


def _send_review(
    prompt: str,
    config: Config,
    render: Render,
    output_file: Optional[str],
) -> None:
    """Send review request and handle response.

    Args:
        prompt: Review prompt.
        config: Configuration.
        render: Renderer instance.
        output_file: Optional file to save review to.
    """
    try:
        client = PollinationClient(api_key=config.api_key)

        with render.status("Analyzing code..."):
            response = client.chat(
                message=prompt,
                model=config.default_model,
                system_prompt=None,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
            )

        review_text = response.content

        # Render review
        render.rule("Code Review Results")
        render.print_markdown(review_text)
        render.rule()

        # Save to file if requested
        if output_file:
            output_path = Path(output_file)
            output_path.write_text(review_text, encoding="utf-8")
            render.print_success(f"Review saved to {output_file}")

        client.close()

    except Exception as e:
        render.print_error(f"Review failed: {e}")
        raise typer.Exit(1)
