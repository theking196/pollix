"""Context builder for project-aware AI interactions.

Automatically detects project types, gathers relevant files, and constructs
system prompts with project context for more accurate AI responses.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pollix.fs.tools import (
    DEFAULT_IGNORE_PATTERNS,
    find_files,
    get_file_stats,
    get_gitignore_patterns,
    get_project_tree,
    is_sensitive_file,
    is_text_file,
    read_file,
    read_multiple,
    should_ignore,
)

# Approximate tokens per character (rough estimate for most text)
TOKENS_PER_CHAR = 0.25

# Maximum context sizes by mode
MODE_BUDGETS = {
    "minimal": 1_000,
    "auto": 8_000,
    "full": 32_000,
    "files": 16_000,
}

# Project type detection config files
PROJECT_TYPE_INDICATORS: Dict[str, List[str]] = {
    "python": ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile", "poetry.lock"],
    "node": ["package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", ".npmrc"],
    "rust": ["Cargo.toml", "Cargo.lock", "rust-toolchain"],
    "go": ["go.mod", "go.sum"],
    "java": ["pom.xml", "build.gradle", "build.gradle.kts", "gradlew"],
    "ruby": ["Gemfile", "Gemfile.lock", "*.gemspec"],
    "php": ["composer.json", "composer.lock"],
    "dotnet": ["*.csproj", "*.sln", "*.fsproj"],
    "flutter": ["pubspec.yaml"],
    "elixir": ["mix.exs", "mix.lock"],
    "haskell": ["stack.yaml", "package.yaml", "*.cabal"],
    "docker": ["Dockerfile", "docker-compose.yml", "docker-compose.yaml", ".dockerignore"],
}

# Key config files to include by project type
KEY_CONFIG_FILES: Dict[str, List[str]] = {
    "python": ["pyproject.toml", "setup.py", "requirements.txt", "setup.cfg", "README.md", "README.rst"],
    "node": ["package.json", "tsconfig.json", "jsconfig.json", "README.md", ".eslintrc*"],
    "rust": ["Cargo.toml", "README.md", "rust-toolchain"],
    "go": ["go.mod", "README.md"],
    "java": ["pom.xml", "build.gradle", "README.md"],
    "ruby": ["Gemfile", "README.md"],
    "php": ["composer.json", "README.md"],
    "dotnet": ["*.csproj", "README.md"],
    "flutter": ["pubspec.yaml", "README.md"],
    "elixir": ["mix.exs", "README.md"],
    "haskell": ["stack.yaml", "package.yaml", "README.md"],
    "docker": ["Dockerfile", "docker-compose.yml", "README.md"],
}

# System prompts by project type
PROJECT_SYSTEM_PROMPTS: Dict[str, str] = {
    "python": (
        "You are assisting with a Python project. "
        "Use Python best practices, type hints, and modern syntax (3.9+). "
        "Prefer pathlib over os.path, use dataclasses where appropriate, "
        "and follow PEP 8 style guidelines."
    ),
    "node": (
        "You are assisting with a Node.js/JavaScript/TypeScript project. "
        "Use modern ES2020+ or TypeScript features, async/await for async code, "
        "and follow the project's linting configuration."
    ),
    "rust": (
        "You are assisting with a Rust project. "
        "Follow Rust idioms, use proper error handling with Result, "
        "and leverage the type system for safety. Prefer standard library where possible."
    ),
    "go": (
        "You are assisting with a Go project. "
        "Follow Go conventions: short variable names, explicit error handling, "
        "and composition over inheritance. Use gofmt style."
    ),
    "java": (
        "You are assisting with a Java/Kotlin project. "
        "Use modern Java features where appropriate, follow the project's build system, "
        "and adhere to standard naming conventions."
    ),
    "ruby": (
        "You are assisting with a Ruby project. "
        "Follow Ruby idioms, use expressive names, and respect the project's Gemfile setup."
    ),
    "php": (
        "You are assisting with a PHP project. "
        "Use modern PHP features, follow PSR standards, and respect composer dependencies."
    ),
    "dotnet": (
        "You are assisting with a .NET project. "
        "Use modern C# features, async/await patterns, and follow the project's coding style."
    ),
    "flutter": (
        "You are assisting with a Flutter/Dart project. "
        "Follow Flutter best practices, use widget composition, and respect the pubspec configuration."
    ),
    "elixir": (
        "You are assisting with an Elixir project. "
        "Use functional programming patterns, pattern matching, and OTP principles where appropriate."
    ),
    "haskell": (
        "You are assisting with a Haskell project. "
        "Use pure functions, proper type signatures, and idiomatic Haskell patterns."
    ),
    "docker": (
        "You are assisting with a containerized project. "
        "Follow Docker best practices: minimal images, multi-stage builds, and proper layer caching."
    ),
    "generic": (
        "You are assisting with a software project. "
        "Analyze the provided context carefully and provide accurate, helpful responses. "
        "Consider the project's structure and dependencies when making suggestions."
    ),
}


class ContextMode(str, Enum):
    """Context gathering modes."""

    MINIMAL = "minimal"
    AUTO = "auto"
    FULL = "full"
    FILES = "files"


@dataclass
class ProjectContext:
    """Collected project context for AI interaction."""

    project_type: str = "generic"
    project_types: List[str] = field(default_factory=list)
    working_directory: str = ""
    git_branch: Optional[str] = None
    git_repo: bool = False
    project_tree: str = ""
    key_files: Dict[str, str] = field(default_factory=dict)
    file_metadata: List[Dict] = field(default_factory=list)
    estimated_tokens: int = 0
    system_prompt: str = ""
    context_mode: str = "auto"
    warnings: List[str] = field(default_factory=list)

    def to_prompt(self, user_query: str = "") -> str:
        """Convert context to a full prompt string.

        Args:
            user_query: The user's query to append.

        Returns:
            Formatted context string.
        """
        parts: List[str] = []

        # Header
        parts.append("# Project Context")
        parts.append("")

        # Working directory
        parts.append(f"**Working Directory:** `{self.working_directory}`")

        # Git info
        if self.git_repo:
            branch_info = f" (branch: {self.git_branch})" if self.git_branch else ""
            parts.append(f"**Git Repository:** Yes{branch_info}")

        # Project type
        if self.project_types:
            parts.append(f"**Project Type(s):** {', '.join(self.project_types)}")
        parts.append("")

        # Project tree
        if self.project_tree:
            parts.append("## Project Structure")
            parts.append("```")
            parts.append(self.project_tree)
            parts.append("```")
            parts.append("")

        # Key files
        if self.key_files:
            parts.append("## Key Configuration Files")
            parts.append("")
            for file_path, content in self.key_files.items():
                parts.append(f"### {file_path}")
                parts.append("```")
                # Truncate very long files
                if len(content) > 5000:
                    content = content[:5000] + "\n... [truncated]"
                parts.append(content)
                parts.append("```")
                parts.append("")

        # Warnings
        if self.warnings:
            parts.append("## Warnings")
            for warning in self.warnings:
                parts.append(f"- ⚠️ {warning}")
            parts.append("")

        # Token estimate
        parts.append(f"*Estimated context tokens: ~{self.estimated_tokens:,}*")
        parts.append("")

        # User query
        if user_query:
            parts.append("---")
            parts.append("")
            parts.append(f"**User Query:** {user_query}")

        return "\n".join(parts)


class ContextBuilder:
    """Builds project context for AI interactions.

    Automatically detects project structure, identifies relevant files,
    and assembles context within token budgets.

    Example:
        >>> builder = ContextBuilder()
        >>> context = builder.build(mode=ContextMode.AUTO)
        >>> print(context.project_type)
        'python'
    """

    def __init__(self, root_path: Optional[str] = None) -> None:
        """Initialize the context builder.

        Args:
            root_path: Root directory to analyze. Defaults to current directory.
        """
        self.root = Path(root_path or ".").resolve()
        self._project_type_cache: Optional[str] = None
        self._tree_cache: Optional[str] = None

    def detect_project_type(self) -> Tuple[str, List[str]]:
        """Detect the project type(s) by looking for config files.

        Returns:
            Tuple of (primary type, list of all detected types).
        """
        if self._project_type_cache:
            return self._project_type_cache, self._project_types_cache

        detected: List[str] = []

        for project_type, indicators in PROJECT_TYPE_INDICATORS.items():
            for indicator in indicators:
                if "*" in indicator:
                    # Glob pattern
                    matches = list(self.root.glob(indicator))
                    if any(m.exists() for m in matches):
                        detected.append(project_type)
                        break
                else:
                    if (self.root / indicator).exists():
                        detected.append(project_type)
                        break

        if not detected:
            detected = ["generic"]

        primary = detected[0]
        self._project_type_cache = primary
        self._project_types_cache = detected
        return primary, detected

    def get_git_info(self) -> Tuple[bool, Optional[str]]:
        """Get git repository information.

        Returns:
            Tuple of (is_git_repo, current_branch).
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            is_repo = result.returncode == 0 and result.stdout.strip() == "true"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False, None

        if not is_repo:
            return False, None

        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            branch = result.stdout.strip() if result.returncode == 0 else None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            branch = None

        return True, branch

    def get_system_prompt(self, project_type: str, custom_prompt: Optional[str] = None) -> str:
        """Get the system prompt for the project type.

        Args:
            project_type: Detected project type.
            custom_prompt: Optional custom system prompt override.

        Returns:
            System prompt string.
        """
        if custom_prompt:
            return custom_prompt

        base_prompt = PROJECT_SYSTEM_PROMPTS.get(project_type, PROJECT_SYSTEM_PROMPTS["generic"])

        # Add general instructions
        general = (
            "When providing code, ensure it's complete and runnable. "
            "Explain your reasoning when making architectural decisions. "
            "If you're unsure about something, say so rather than guessing."
        )

        return f"{base_prompt}\n\n{general}"

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text.

        Args:
            text: Text to estimate.

        Returns:
            Estimated token count.
        """
        return int(len(text) * TOKENS_PER_CHAR)

    def _get_key_files(self, project_type: str, budget: int) -> Dict[str, str]:
        """Read key configuration files for the project type.

        Args:
            project_type: Detected project type.
            budget: Token budget for file contents.

        Returns:
            Dictionary of file paths to contents.
        """
        key_files: Dict[str, str] = {}
        tokens_used = 0

        # Get patterns for this project type
        patterns = KEY_CONFIG_FILES.get(project_type, ["README.md", "README.rst"])

        # Always try to include README
        readme_files = ["README.md", "README.rst", "README.txt", "README"]
        for readme in readme_files:
            readme_path = self.root / readme
            if readme_path.exists():
                try:
                    content = read_file(readme_path, max_size=50_000)
                    file_tokens = self._estimate_tokens(content)
                    if tokens_used + file_tokens < budget * 0.5:  # Reserve half budget for README
                        key_files[str(readme_path.relative_to(self.root))] = content
                        tokens_used += file_tokens
                    break
                except Exception:
                    continue

        # Include other key config files
        for pattern in patterns:
            if tokens_used >= budget:
                break

            if "*" in pattern:
                matches = list(self.root.glob(pattern))
            else:
                matches = [self.root / pattern]

            for match in matches:
                rel_path = str(match.relative_to(self.root))
                if rel_path in key_files:
                    continue

                try:
                    if not match.exists() or not match.is_file():
                        continue
                    if is_sensitive_file(match):
                        continue

                    content = read_file(match, max_size=30_000)
                    file_tokens = self._estimate_tokens(content)

                    if tokens_used + file_tokens < budget:
                        key_files[rel_path] = content
                        tokens_used += file_tokens
                except Exception:
                    continue

        return key_files

    def _get_all_readable_files(self, budget: int) -> Dict[str, str]:
        """Get all readable files up to token budget.

        Args:
            budget: Token budget.

        Returns:
            Dictionary of file paths to contents.
        """
        files: Dict[str, str] = {}
        tokens_used = 0

        # Get ignore patterns from .gitignore
        gitignore_patterns = get_gitignore_patterns(self.root)
        ignore_patterns = list(DEFAULT_IGNORE_PATTERNS) + gitignore_patterns

        for item in self.root.rglob("*"):
            if tokens_used >= budget:
                break

            if not item.is_file():
                continue

            if should_ignore(item, ignore_patterns, root=self.root):
                continue

            if is_sensitive_file(item):
                continue

            rel_path = str(item.relative_to(self.root))

            try:
                if not is_text_file(item):
                    continue

                content = read_file(item, max_size=20_000)
                file_tokens = self._estimate_tokens(content)

                if tokens_used + file_tokens < budget:
                    files[rel_path] = content
                    tokens_used += file_tokens
                else:
                    # Add truncated version if we have room
                    remaining = budget - tokens_used
                    if remaining > 500:
                        truncated = content[:int(remaining / TOKENS_PER_CHAR)]
                        files[rel_path] = truncated + "\n... [truncated by context budget]"
                        break

            except Exception:
                continue

        return files

    def build(
        self,
        mode: ContextMode = ContextMode.AUTO,
        custom_files: Optional[List[str]] = None,
        custom_prompt: Optional[str] = None,
        max_depth: int = 4,
    ) -> ProjectContext:
        """Build project context.

        Args:
            mode: Context gathering mode.
            custom_files: Specific files to include (for FILES mode).
            custom_prompt: Custom system prompt override.
            max_depth: Maximum depth for project tree.

        Returns:
            Assembled ProjectContext.
        """
        context = ProjectContext()
        context.context_mode = mode.value
        context.working_directory = str(self.root)

        # Detect project type
        primary_type, all_types = self.detect_project_type()
        context.project_type = primary_type
        context.project_types = all_types

        # Get git info
        is_git, branch = self.get_git_info()
        context.git_repo = is_git
        context.git_branch = branch

        # Get system prompt
        context.system_prompt = self.get_system_prompt(primary_type, custom_prompt)

        # Calculate token budget
        budget = MODE_BUDGETS.get(mode.value, MODE_BUDGETS["auto"])

        if mode == ContextMode.MINIMAL:
            # Minimal mode: just working directory and project type
            context.estimated_tokens = self._estimate_tokens(context.to_prompt())
            return context

        elif mode == ContextMode.FILES:
            # Files mode: only specified files
            if custom_files:
                context.key_files = read_multiple(
                    custom_files,
                    max_total=int(budget / TOKENS_PER_CHAR),
                )
                for file_path in custom_files:
                    rel_path = str(Path(file_path).relative_to(self.root)) if Path(file_path).is_relative_to(self.root) else file_path
                    if rel_path not in context.key_files:
                        context.warnings.append(f"Could not read file: {file_path}")

        elif mode == ContextMode.FULL:
            # Full mode: project tree + all readable files
            ignore_patterns = list(DEFAULT_IGNORE_PATTERNS) + get_gitignore_patterns(self.root)
            try:
                context.project_tree = get_project_tree(
                    self.root,
                    max_depth=max_depth,
                    ignore_patterns=ignore_patterns,
                )
            except Exception:
                context.project_tree = "[Could not generate project tree]"

            # Estimate tree tokens
            tree_tokens = self._estimate_tokens(context.project_tree)
            remaining_budget = budget - tree_tokens

            # Get all readable files
            context.key_files = self._get_all_readable_files(remaining_budget)

        else:
            # Auto mode: project tree + key config files
            ignore_patterns = list(DEFAULT_IGNORE_PATTERNS) + get_gitignore_patterns(self.root)
            try:
                context.project_tree = get_project_tree(
                    self.root,
                    max_depth=max_depth,
                    ignore_patterns=ignore_patterns,
                )
            except Exception:
                context.project_tree = "[Could not generate project tree]"

            # Estimate tree tokens
            tree_tokens = self._estimate_tokens(context.project_tree)
            remaining_budget = budget - tree_tokens

            # Get key config files
            context.key_files = self._get_key_files(primary_type, remaining_budget)

        # Calculate total tokens
        prompt_text = context.to_prompt()
        context.estimated_tokens = self._estimate_tokens(prompt_text)

        # Add warning if context is large
        if context.estimated_tokens > budget * 0.9:
            context.warnings.append(
                f"Context is near budget limit (~{context.estimated_tokens:,} / {budget:,} tokens). "
                "Some files may have been truncated."
            )

        return context

    def get_files_content(self, file_paths: List[str]) -> Dict[str, str]:
        """Read specific files and return their contents.

        Args:
            file_paths: List of file paths to read.

        Returns:
            Dictionary of file paths to contents.
        """
        result: Dict[str, str] = {}
        for path in file_paths:
            try:
                full_path = self.root / path if not Path(path).is_absolute() else Path(path)
                content = read_file(full_path)
                rel_path = str(full_path.relative_to(self.root)) if full_path.is_relative_to(self.root) else str(full_path)
                result[rel_path] = content
            except Exception as e:
                result[path] = f"[Error reading file: {e}]"
        return result
