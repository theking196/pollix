# pollix

Unofficial CLI for Pollination AI with file system access, project context awareness, and advanced developer workflows.

## Features

- **Chat with AI** - Interactive and single-shot conversations with streaming support
- **Code Review** - Automated reviews for quality, security, performance, and documentation
- **AI-Assisted Editing** - Edit files with natural language instructions and diff preview
- **Project Context** - Automatic project type detection with smart file inclusion
- **File System Access** - Read, search, and explore project files directly from the CLI
- **Conversation History** - Save and resume conversation threads
- **Rich Output** - Syntax highlighting, markdown rendering, and colored diffs
- **Upgrade Roadmap** - See `ROADMAP.md` for the Pollix plan toward multimodal, media, embeddings, and safe tool workflows

## Installation

```bash
pip install pollix
```

Or install from source:

```bash
git clone https://github.com/pollix-dev/pollix.git
cd pollix
pip install -e .
```

## Quick Start

```bash
# Initialize configuration
pollix init --global

# Start chatting
pollix chat "Hello!"

# Chat with project context
pollix chat "Explain this codebase"

# Review code
pollix review src/ --type security

# List bundled Pollinations model IDs
pollix models

# Edit a file
pollix edit config.yaml -i "add a redis section with port 6379"
```

## Configuration

Pollix uses a hierarchical configuration system:

1. **CLI arguments** (highest priority)
2. **Environment variables**
3. **Local config** (`.pollix/config.yaml`)
4. **Global config** (`~/.pollix/config.yaml`)
5. **Defaults** (lowest priority)

### Initialize Configuration

```bash
# Interactive global setup
pollix init --global

# Quick setup with flags
pollix init --global --api-key YOUR_KEY --model openai

# Project-specific local config
pollix init --local
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `POLLINATIONS_KEY` | Your Pollinations API key (preferred) |
| `POLLINATION_API_KEY` | Backward-compatible API key alias |
| `POLLIX_API_KEY` | Pollix-specific API key alias |
| `POLLIX_DEFAULT_MODEL` | Default model (default: openai) |
| `POLLIX_CONTEXT_MODE` | Context mode: minimal, auto, full, files |
| `POLLIX_TEMPERATURE` | Sampling temperature (0.0 - 1.0) |
| `POLLIX_MAX_TOKENS` | Maximum tokens per response |
| `POLLIX_THEME` | UI theme: dark, light |

## Commands

### `chat` - Chat with Pollination AI

```bash
# Basic chat
pollix chat "What is the best way to handle errors in Python?"

# With file attachments
pollix chat "Explain this code" -f src/main.py
pollix chat "Fix the bug" -f src/main.py -f src/utils.py

# With specific context mode
pollix chat "Review my code" --context-mode full
pollix chat "Quick question" --context-mode minimal

# Custom model and parameters
pollix chat "Complex task" -m claude --temperature 0.2 --top-p 0.9

# Request JSON output
pollix chat "Return a JSON object with one greeting field" --json --no-stream

# Interactive mode
pollix chat

# Pipe support
cat error.log | pollix chat "What's causing this error?"
git diff | pollix chat "Summarize these changes"

# Save/load conversations
pollix chat "Let's discuss architecture" --save project-plan
pollix chat "Continue" --load project-plan
```

**Options:**
- `--model, -m`: Model name (openai, openai-fast, deepseek, gemini, claude)
- `--file, -f`: Include specific files (repeatable)
- `--context-mode`: minimal, auto, full, files
- `--stream/--no-stream`: Enable/disable streaming
- `--system, -s`: Custom system prompt
- `--history, -h`: Number of previous messages to include
- `--save`: Save conversation thread name
- `--load`: Load previous conversation
- `--temperature`: Sampling temperature (0.0 - 1.0)
- `--max-tokens`: Maximum response tokens
- `--top-p`: Nucleus sampling cutoff
- `--frequency-penalty`: Penalize frequently repeated tokens
- `--presence-penalty`: Penalize tokens already present
- `--seed`: Best-effort deterministic seed, if supported by the selected model
- `--json`: Request a JSON object response using OpenAI-compatible `response_format`

**Interactive Commands:**
- `/quit`, `/q` - Exit
- `/clear` - Clear screen
- `/context` - Show context info
- `/save <name>` - Save conversation
- `/load <name>` - Load conversation
- `/help` - Show help

### `models` - List Models

```bash
# Show bundled model identifiers and the live discovery endpoint
pollix models

# Fetch the current model list from Pollinations
pollix models --live

# Use any model with chat/review/edit
pollix chat "Hello" -m gemma
pollix chat "Search this" -m gemini-search
```

The default model is `openai`. Common alternatives include `openai-fast`, `gemma`, `claude`, `gemini`, `deepseek`, `kimi`, and `qwen-coder`. Pollinations may add models over time, so the CLI allows custom model IDs instead of blocking unknown future models.

### `review` - Code Review

```bash
# Review entire directory
pollix review src/

# Review specific files
pollix review main.py utils.py

# Security-focused review
pollix review src/ --type security

# Performance review
pollix review src/ --type performance

# Review unstaged git changes
pollix review --diff

# Save review to file
pollix review src/ --type all -o review-report.md
```

**Options:**
- `--type, -t`: code, security, performance, docs, all (default: all)
- `--file, -f`: Specific files to review
- `--output, -o`: Save review to file
- `--diff`: Review only unstaged git changes
- `--inline`: Show inline suggestions

### `edit` - AI-Assisted File Editing

```bash
# Edit with instruction
pollix edit config.yaml -i "add a redis section with port 6379"

# Edit with positional argument
pollix edit main.py "refactor this to use async/await"

# Show diff before applying (default)
pollix edit app.py "add error handling" --diff

# Dry run (preview only)
pollix edit app.py "restructure imports" --dry-run

# Skip backup
pollix edit readme.md "fix typos" --no-backup

# Output to different file
pollix edit template.py "add logging" -o template_with_logging.py
```

**Options:**
- `--instruction, -i`: Edit instruction
- `--output, -o`: Output file (default: overwrite input)
- `--diff/--no-diff`: Show/hide diff preview
- `--context-lines`: Lines of context around edits
- `--backup/--no-backup`: Create backup
- `--dry-run`: Preview changes without applying

### `init` - Configuration Setup

```bash
# Interactive global setup
pollix init --global

# Non-interactive setup
pollix init --global --no-interactive --api-key YOUR_KEY

# Local project config
pollix init --local

# Force overwrite
pollix init --global --force
```

**Options:**
- `--global, -g`: Global config in ~/.pollix/
- `--local, -l`: Local config in ./.pollix/
- `--interactive/--no-interactive`: Interactive prompts
- `--api-key`: API key for non-interactive setup
- `--force`: Overwrite existing config

## Project Structure

```
pollix/
├── pyproject.toml          # Project configuration
├── README.md               # This file
├── .env.example            # Environment variable template
└── src/pollix/
    ├── __init__.py         # Package version
    ├── __main__.py         # python -m pollix entry point
    ├── cli.py              # Main Typer CLI app
    ├── api/
    │   └── client.py       # Pollination API HTTP client
    ├── fs/
    │   └── tools.py        # File system operations
    ├── context/
    │   └── builder.py      # Context assembly for AI prompts
    ├── commands/
    │   ├── chat.py         # Chat command implementation
    │   ├── review.py       # Code review implementation
    │   ├── edit.py         # File editing implementation
    │   └── init.py         # Config initialization
    └── utils/
        ├── config.py       # Configuration management
        ├── streaming.py    # SSE stream handling
        └── render.py       # Rich console output
```

## API Client

The `PollinationClient` class provides:

- **Streaming and non-streaming** chat completion
- **Automatic retries** with exponential backoff
- **Rate limit handling** with retry-after support
- **Timeout configuration** (30s connect, 120s read)
- **Connection pooling** via httpx
- **Context manager** support

```python
from pollix.api.client import PollinationClient

# Basic usage
client = PollinationClient(api_key="your-key")
response = client.chat("Hello!")
print(response.content)

# Streaming
for token in client.chat_stream("Tell me a story"):
    print(token, end="", flush=True)

# Context manager (auto-closes)
with PollinationClient(api_key="your-key") as client:
    response = client.chat("Hello!")
```

## File System Tools

The `pollix.fs.tools` module provides:

| Function | Description |
|----------|-------------|
| `read_file(path)` | Read text file with size limit and binary detection |
| `list_dir(path)` | List directory with gitignore-style filtering |
| `get_project_tree(path)` | ASCII tree of project structure |
| `find_files(pattern)` | Glob search for files |
| `grep_files(pattern)` | Content search across files |
| `get_file_stats(path)` | File size, line count, modification time |
| `is_text_file(path)` | Check if file is text (not binary) |
| `read_multiple(paths)` | Read multiple files with total size cap |

## Context Builder

The context builder automatically:

1. **Detects project type** by looking for config files (package.json, Cargo.toml, etc.)
2. **Generates system prompts** tailored to the project type
3. **Includes project tree** for structural context
4. **Reads key config files** (README, package files)
5. **Manages token budget** to stay within limits
6. **Respects .gitignore** patterns

Context modes:
- `minimal` - Just the user query + working directory
- `auto` - Auto-detect relevant files (default)
- `full` - Entire project tree + all readable files
- `files` - Only specified files

## Development

```bash
# Clone repository
git clone https://github.com/pollix-dev/pollix.git
cd pollix

# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest

# Code formatting
black src/ tests/
ruff check --fix src/ tests/

# Type checking
mypy src/pollix
```

## Requirements

- Python 3.9+
- Pollination API key (get one at [pollination.ai](https://pollination.ai))

## License

MIT License - see LICENSE file for details.

## Disclaimer

This is an unofficial CLI for Pollination AI. It is not affiliated with or endorsed by Pollination.
