"""File system tools for reading and exploring project files.

Provides functions for reading files, listing directories, searching content,
and gathering project structure information with proper error handling,
size limits, and binary file detection.
"""

from __future__ import annotations

import fnmatch
import mimetypes
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple, Union

# Default patterns to ignore when scanning directories
DEFAULT_IGNORE_PATTERNS: List[str] = [
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "*.pyc",
    ".pytest_cache",
    "dist",
    "build",
    "*.egg-info",
    ".tox",
    ".mypy_cache",
    ".egg",
    "*.egg",
    ".coverage",
    "htmlcov",
    ".DS_Store",
    "Thumbs.db",
    ".idea",
    ".vscode",
    "*.min.js",
    "*.min.css",
    ".next",
    ".nuxt",
    "target",  # Rust build
    "vendor",  # Go vendor
    "*.lock",  # Lock files
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
]

# Patterns that suggest sensitive files
SENSITIVE_PATTERNS: List[str] = [
    "*.env*",
    "*.key",
    "*.pem",
    "*.p12",
    "*.pfx",
    "*secret*",
    "*token*",
    "*password*",
    "*credential*",
    "*.htpasswd",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "*.keystore",
    "*.jks",
]

# File extensions considered text by default
TEXT_EXTENSIONS = {
    # Programming languages
    ".py", ".js", ".ts", ".jsx", ".tsx", ".rs", ".go", ".java", ".c", ".cpp",
    ".h", ".hpp", ".cs", ".rb", ".php", ".swift", ".kt", ".scala", ".r",
    ".m", ".mm", ".pl", ".pm", ".lua", ".sh", ".bash", ".zsh", ".fish",
    ".ps1", ".psm1", ".clj", ".cljs", ".ex", ".exs", ".erl", ".hrl",
    ".ml", ".mli", ".fs", ".fsx", ".fsi", ".hs", ".lhs", ".elm", ". purs",
    # Web
    ".html", ".htm", ".css", ".scss", ".sass", ".less", ".xml", ".svg",
    ".vue", ".svelte", ".astro",
    # Data
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".config",
    ".csv", ".tsv", ".sql",
    # Documentation
    ".md", ".rst", ".txt", ".text", ".org", ".adoc", ".wiki",
    # Other
    ".dockerfile", ".gitignore", ".gitattributes", ".editorconfig",
    ".eslint", ".prettierrc", ".babelrc", ".htaccess", ".npmignore",
    ".dockerignore", "makefile", ".mk", ".cmake", ".gradle",
    # Scripts
    ".R", ".rmd", ".ipynb", ".jl", ".cr", ".nim", ".nims",
    # Shell configs
    ".bashrc", ".zshrc", ".vimrc", ".inputrc",
}

BINARY_MIME_PREFIXES = (
    "image/", "audio/", "video/", "application/octet-stream",
    "application/pdf", "application/zip", "application/gzip",
    "application/x-tar", "application/x-bzip", "application/x-7z",
    "application/x-rar", "application/x-exe", "application/x-dll",
    "application/x-object", "application/x-sharedlib",
)


class FileSystemError(Exception):
    """Base exception for file system operations."""

    def __init__(self, message: str, path: Optional[Union[str, Path]] = None) -> None:
        super().__init__(message)
        self.path = Path(path) if path else None


class FileTooLargeError(FileSystemError):
    """Raised when a file exceeds the maximum allowed size."""

    def __init__(self, path: Union[str, Path], size: int, max_size: int) -> None:
        self.size = size
        self.max_size = max_size
        message = (
            f"File '{path}' is too large ({size:,} bytes, "
            f"max: {max_size:,} bytes)"
        )
        super().__init__(message, path)


class BinaryFileError(FileSystemError):
    """Raised when attempting to read a binary file as text."""

    def __init__(self, path: Union[str, Path]) -> None:
        super().__init__(f"File '{path}' appears to be binary", path)


class PermissionDeniedError(FileSystemError):
    """Raised when file access is denied."""

    def __init__(self, path: Union[str, Path]) -> None:
        super().__init__(f"Permission denied: '{path}'", path)


class FileNotFoundError(FileSystemError):
    """Raised when a file does not exist."""

    def __init__(self, path: Union[str, Path]) -> None:
        super().__init__(f"File not found: '{path}'", path)


def is_text_file(path: Union[str, Path], sample_size: int = 8192) -> bool:
    """Check if a file is a text file (not binary).

    Uses a combination of file extension checking and content sniffing
    to determine if a file contains text data.

    Args:
        path: Path to the file to check.
        sample_size: Number of bytes to read for content analysis.

    Returns:
        True if the file is text, False if binary.

    Raises:
        FileNotFoundError: If the file does not exist.
        PermissionDeniedError: If the file cannot be read.
    """
    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(file_path)

    # Check extension first
    ext = file_path.suffix.lower()
    name = file_path.name.lower()

    # Known text extensions
    if ext in TEXT_EXTENSIONS or name in TEXT_EXTENSIONS:
        return True

    # Known binary extensions
    binary_extensions = {
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff",
        ".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a",
        ".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm",
        ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".exe", ".dll", ".so", ".dylib", ".bin", ".dat",
        ".db", ".sqlite", ".sqlite3", ".mdb",
        ".o", ".obj", ".a", ".lib",
        ".ttf", ".otf", ".woff", ".woff2", ".eot",
    }
    if ext in binary_extensions:
        return False

    # Try MIME type detection
    mime_type, _ = mimetypes.guess_type(str(file_path))
    if mime_type:
        if mime_type.startswith("text/"):
            return True
        if mime_type.startswith(BINARY_MIME_PREFIXES):
            return False

    # Content-based detection
    try:
        with open(file_path, "rb") as f:
            sample = f.read(sample_size)
    except PermissionError:
        raise PermissionDeniedError(file_path)

    if not sample:
        return True  # Empty files are text

    # Check for null bytes (strong indicator of binary)
    if b"\x00" in sample:
        return False

    # Check for high ratio of non-printable characters
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        pass

    # Try latin-1 as fallback
    non_printable = sum(1 for byte in sample if byte < 32 and byte not in (9, 10, 13))
    if non_printable / len(sample) > 0.30:
        return False

    return True


def read_file(
    path: Union[str, Path],
    max_size: int = 100_000,
    allow_binary: bool = False,
) -> str:
    """Read a text file with size limit and safety checks.

    Args:
        path: Path to the file to read.
        max_size: Maximum file size in bytes.
        allow_binary: If True, attempt to read binary files anyway.

    Returns:
        The file contents as a string.

    Raises:
        FileNotFoundError: If the file does not exist.
        PermissionDeniedError: If the file cannot be read.
        FileTooLargeError: If the file exceeds max_size.
        BinaryFileError: If the file is binary and allow_binary is False.
    """
    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(file_path)

    if not file_path.is_file():
        raise FileSystemError(f"'{file_path}' is not a file", file_path)

    # Check file size
    try:
        size = file_path.stat().st_size
    except PermissionError:
        raise PermissionDeniedError(file_path)
    except OSError as e:
        raise FileSystemError(f"Cannot stat file: {e}", file_path)

    if size > max_size:
        raise FileTooLargeError(file_path, size, max_size)

    # Check if binary
    if not allow_binary:
        try:
            if not is_text_file(file_path):
                raise BinaryFileError(file_path)
        except (FileNotFoundError, PermissionDeniedError):
            raise

    # Read the file
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except PermissionError:
        raise PermissionDeniedError(file_path)
    except UnicodeDecodeError:
        if allow_binary:
            with open(file_path, "r", encoding="latin-1") as f:
                return f.read()
        raise BinaryFileError(file_path)
    except OSError as e:
        raise FileSystemError(f"Error reading file: {e}", file_path)


def is_sensitive_file(path: Union[str, Path]) -> bool:
    """Check if a file path matches sensitive file patterns.

    Args:
        path: Path to check.

    Returns:
        True if the file matches sensitive patterns.
    """
    name = Path(path).name
    return any(fnmatch.fnmatch(name, pattern) for pattern in SENSITIVE_PATTERNS)


def should_ignore(
    path: Union[str, Path],
    ignore_patterns: Optional[List[str]] = None,
    root: Optional[Union[str, Path]] = None,
) -> bool:
    """Check if a path should be ignored based on patterns.

    Args:
        path: Path to check.
        ignore_patterns: List of glob patterns to ignore.
        root: Root directory for relative path matching.

    Returns:
        True if the path should be ignored.
    """
    patterns = ignore_patterns or DEFAULT_IGNORE_PATTERNS
    file_path = Path(path)

    # Check name against patterns
    name = file_path.name
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return True

    # Check relative path against patterns
    if root:
        try:
            rel_path = file_path.relative_to(root)
            parts = list(rel_path.parts)
            for pattern in patterns:
                # Check if any path component matches
                if any(fnmatch.fnmatch(part, pattern) for part in parts):
                    return True
                # Check full relative path
                if fnmatch.fnmatch(str(rel_path), pattern):
                    return True
        except ValueError:
            pass

    return False


def list_dir(
    path: Union[str, Path] = ".",
    ignore_patterns: Optional[List[str]] = None,
    show_hidden: bool = False,
) -> List[Dict[str, Union[str, int, bool]]]:
    """List directory contents with filtering.

    Args:
        path: Directory to list.
        ignore_patterns: Glob patterns to exclude.
        show_hidden: Include hidden files and directories.

    Returns:
        List of file/directory entries with metadata.

    Raises:
        FileNotFoundError: If the directory does not exist.
        PermissionDeniedError: If the directory cannot be read.
    """
    dir_path = Path(path)

    if not dir_path.exists():
        raise FileNotFoundError(dir_path)

    if not dir_path.is_dir():
        raise FileSystemError(f"'{dir_path}' is not a directory", dir_path)

    results: List[Dict[str, Union[str, int, bool]]] = []

    try:
        entries = sorted(dir_path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        raise PermissionDeniedError(dir_path)

    for entry in entries:
        # Skip hidden entries unless requested
        if not show_hidden and entry.name.startswith("."):
            continue

        # Skip ignored entries
        if should_ignore(entry, ignore_patterns, root=dir_path):
            continue

        try:
            stat = entry.stat()
            info: Dict[str, Union[str, int, bool]] = {
                "name": entry.name,
                "path": str(entry),
                "is_dir": entry.is_dir(),
                "size": stat.st_size if entry.is_file() else 0,
                "modified": int(stat.st_mtime),
            }
            results.append(info)
        except (OSError, PermissionError):
            # Skip entries we can't stat
            continue

    return results


def get_project_tree(
    path: Union[str, Path] = ".",
    max_depth: int = 4,
    ignore_patterns: Optional[List[str]] = None,
    show_hidden: bool = False,
) -> str:
    """Generate an ASCII tree of the project structure.

    Args:
        path: Root directory to start from.
        max_depth: Maximum recursion depth.
        ignore_patterns: Glob patterns to exclude.
        show_hidden: Include hidden files and directories.

    Returns:
        ASCII tree as a string.

    Raises:
        FileNotFoundError: If the directory does not exist.
    """
    root = Path(path)

    if not root.exists():
        raise FileNotFoundError(root)

    if not root.is_dir():
        raise FileSystemError(f"'{root}' is not a directory", root)

    lines: List[str] = [str(root.name) or "."]

    def _tree(dir_path: Path, prefix: str = "", depth: int = 0) -> None:
        if depth >= max_depth:
            return

        try:
            entries = sorted(
                dir_path.iterdir(),
                key=lambda e: (not e.is_dir(), e.name.lower()),
            )
        except (OSError, PermissionError):
            return

        # Filter entries
        filtered: List[Path] = []
        for entry in entries:
            if not show_hidden and entry.name.startswith("."):
                continue
            if should_ignore(entry, ignore_patterns, root=root):
                continue
            filtered.append(entry)

        for i, entry in enumerate(filtered):
            is_last = i == len(filtered) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{entry.name}")

            if entry.is_dir():
                extension = "    " if is_last else "│   "
                _tree(entry, prefix + extension, depth + 1)

    _tree(root)
    return "\n".join(lines)


def find_files(
    pattern: str,
    path: Union[str, Path] = ".",
    ignore_patterns: Optional[List[str]] = None,
) -> List[str]:
    """Find files matching a glob pattern.

    Args:
        pattern: Glob pattern to match (e.g., "*.py", "**/*.js").
        path: Root directory to search in.
        ignore_patterns: Patterns for directories to skip.

    Returns:
        List of matching file paths as strings.
    """
    root = Path(path)
    results: List[str] = []

    if not root.exists() or not root.is_dir():
        return results

    # Use rglob for recursive patterns
    if "**" in pattern:
        matches = root.rglob(pattern.replace("**", "").lstrip("/"))
    else:
        matches = root.glob(pattern)

    for match in matches:
        if match.is_file():
            if not should_ignore(match, ignore_patterns, root=root):
                results.append(str(match))

    return sorted(results)


def grep_files(
    pattern: str,
    path: Union[str, Path] = ".",
    extensions: Optional[List[str]] = None,
    ignore_patterns: Optional[List[str]] = None,
    max_matches: int = 100,
    case_sensitive: bool = False,
) -> List[Dict[str, Union[str, int]]]:
    """Search for content across files.

    Args:
        pattern: Regular expression to search for.
        path: Root directory to search in.
        extensions: File extensions to include (e.g., [".py", ".js"]).
        ignore_patterns: Patterns for files/directories to skip.
        max_matches: Maximum number of matches to return.
        case_sensitive: Whether the search is case-sensitive.

    Returns:
        List of match dictionaries with file, line, and content.
    """
    root = Path(path)
    results: List[Dict[str, Union[str, int]]] = []

    if not root.exists() or not root.is_dir():
        return results

    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        regex = re.compile(pattern, flags)
    except re.error:
        # Escape special characters if invalid regex
        regex = re.compile(re.escape(pattern), flags)

    files_to_search: List[Path] = []

    # Collect files
    for item in root.rglob("*"):
        if not item.is_file():
            continue
        if should_ignore(item, ignore_patterns, root=root):
            continue
        if extensions and item.suffix not in extensions:
            continue
        files_to_search.append(item)

    # Search files
    for file_path in files_to_search:
        if len(results) >= max_matches:
            break

        try:
            if not is_text_file(file_path):
                continue
        except (FileNotFoundError, PermissionDeniedError, FileSystemError):
            continue

        try:
            content = read_file(file_path, max_size=500_000)
        except (FileTooLargeError, BinaryFileError, PermissionDeniedError):
            continue

        for line_num, line in enumerate(content.splitlines(), 1):
            if regex.search(line):
                results.append({
                    "file": str(file_path),
                    "line": line_num,
                    "content": line.strip(),
                    "path": str(file_path.relative_to(root)) if file_path.is_relative_to(root) else str(file_path),
                })

                if len(results) >= max_matches:
                    break

    return results


def get_file_stats(path: Union[str, Path]) -> Dict[str, Union[int, str, float]]:
    """Get statistics about a file.

    Args:
        path: Path to the file.

    Returns:
        Dictionary with size, line count, modification time, etc.

    Raises:
        FileNotFoundError: If the file does not exist.
        PermissionDeniedError: If the file cannot be accessed.
    """
    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(file_path)

    try:
        stat = file_path.stat()
    except PermissionError:
        raise PermissionDeniedError(file_path)

    # Calculate line count
    line_count = 0
    if file_path.is_file():
        try:
            content = read_file(file_path, max_size=10_000_000)
            line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        except (FileTooLargeError, BinaryFileError, FileSystemError):
            line_count = -1  # Unknown

    return {
        "path": str(file_path),
        "size": stat.st_size,
        "size_human": _human_readable_size(stat.st_size),
        "lines": line_count,
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "modified_timestamp": stat.st_mtime,
        "is_text": is_text_file(file_path) if file_path.is_file() else False,
        "extension": file_path.suffix,
        "name": file_path.name,
    }


def read_multiple(
    paths: List[Union[str, Path]],
    max_total: int = 200_000,
    max_size_per_file: int = 100_000,
    ignore_binary: bool = True,
    ignore_sensitive: bool = True,
) -> Dict[str, str]:
    """Read multiple files with a total size cap.

    Args:
        paths: List of file paths to read.
        max_total: Maximum total size across all files.
        max_size_per_file: Maximum size per individual file.
        ignore_binary: Skip binary files instead of raising error.
        ignore_sensitive: Skip files matching sensitive patterns.

    Returns:
        Dictionary mapping file paths to their contents.
    """
    results: Dict[str, str] = {}
    total_size = 0

    for path in paths:
        file_path = Path(path)
        file_key = str(file_path)

        # Skip sensitive files
        if ignore_sensitive and is_sensitive_file(file_path):
            results[file_key] = f"# [Skipped sensitive file: {file_path.name}]\n"
            continue

        try:
            content = read_file(file_path, max_size=max_size_per_file)
        except BinaryFileError:
            if ignore_binary:
                continue
            raise
        except (FileNotFoundError, PermissionDeniedError, FileTooLargeError):
            continue

        file_size = len(content.encode("utf-8"))

        if total_size + file_size > max_total:
            # Truncate to fit within budget
            remaining = max_total - total_size
            if remaining > 100:
                truncated = content.encode("utf-8")[:remaining].decode("utf-8", errors="ignore")
                results[file_key] = truncated + f"\n\n# [Truncated: exceeded {max_total} byte total limit]\n"
                break
            else:
                break

        results[file_key] = content
        total_size += file_size

    return results


def _human_readable_size(size_bytes: int) -> str:
    """Convert bytes to human-readable format.

    Args:
        size_bytes: Size in bytes.

    Returns:
        Human-readable string (e.g., "1.5 KB").
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    else:
        return f"{size_bytes / (1024 ** 3):.1f} GB"


def read_stdin() -> str:
    """Read content from standard input.

    Returns:
        Content from stdin as a string.
    """
    import sys

    if sys.stdin.isatty():
        return ""

    try:
        return sys.stdin.read()
    except KeyboardInterrupt:
        return ""


def get_gitignore_patterns(path: Union[str, Path] = ".") -> List[str]:
    """Read patterns from .gitignore file.

    Args:
        path: Directory containing .gitignore.

    Returns:
        List of ignore patterns from .gitignore, or empty list if none exists.
    """
    gitignore = Path(path) / ".gitignore"

    if not gitignore.exists():
        return []

    try:
        content = read_file(gitignore, max_size=100_000)
    except (FileSystemError, BinaryFileError):
        return []

    patterns: List[str] = []
    for line in content.splitlines():
        line = line.strip()
        # Skip empty lines and comments
        if not line or line.startswith("#"):
            continue
        # Remove trailing comments
        if " #" in line:
            line = line.split(" #")[0].strip()
        patterns.append(line)

    return patterns
