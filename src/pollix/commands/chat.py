"""Chat command for interactive and single-shot conversations with Pollination AI."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import typer

from pollix.api.client import PollinationClient, Message
from pollix.context.builder import ContextBuilder, ContextMode
from pollix.fs.tools import read_file, read_stdin
from pollix.utils.config import Config, ConfigManager
from pollix.utils.render import Render


# Conversation history storage
HISTORY_DIR = Path.home() / ".pollix" / "history"


def _ensure_history_dir() -> None:
    """Ensure the conversation history directory exists."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def _save_conversation(name: str, messages: List[dict]) -> None:
    """Save a conversation thread to disk.

    Args:
        name: Thread name.
        messages: List of message dictionaries.
    """
    _ensure_history_dir()
    file_path = HISTORY_DIR / f"{name}.jsonl"

    with open(file_path, "w", encoding="utf-8") as f:
        for msg in messages:
            import json
            f.write(json.dumps(msg) + "\n")


def _load_conversation(name: str) -> List[dict]:
    """Load a conversation thread from disk.

    Args:
        name: Thread name.

    Returns:
        List of message dictionaries.
    """
    file_path = HISTORY_DIR / f"{name}.jsonl"

    if not file_path.exists():
        return []

    import json
    messages = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    return messages


def _list_conversations() -> List[str]:
    """List available conversation threads.

    Returns:
        List of conversation names.
    """
    _ensure_history_dir()
    conversations = []
    for file_path in HISTORY_DIR.glob("*.jsonl"):
        conversations.append(file_path.stem)
    return sorted(conversations)


def chat_command(
    message: Optional[str] = typer.Argument(
        None,
        help="Message to send. Use '-' to read from stdin. If omitted, enters interactive mode.",
    ),
    model: str = typer.Option(
        None, "--model", "-m",
        help="Model name to use (default: from config).",
    ),
    file: Optional[List[str]] = typer.Option(
        None, "--file", "-f",
        help="Include specific file(s). Can be used multiple times.",
    ),
    context_mode: str = typer.Option(
        None, "--context-mode",
        help="Context gathering mode (minimal, auto, full, files).",
    ),
    stream: Optional[bool] = typer.Option(
        None, "--stream/--no-stream",
        help="Enable streaming output (default: from config).",
    ),
    system: Optional[str] = typer.Option(
        None, "--system", "-s",
        help="Custom system prompt.",
    ),
    history_count: int = typer.Option(
        10, "--history", "-h",
        help="Number of previous messages to include.",
    ),
    save: Optional[str] = typer.Option(
        None, "--save",
        help="Save conversation with this name.",
    ),
    load: Optional[str] = typer.Option(
        None, "--load",
        help="Load previous conversation by name.",
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
        help="Enable verbose output.",
    ),
    debug: bool = typer.Option(
        False, "--debug",
        help="Enable debug mode.",
    ),
) -> None:
    """Chat with Pollination AI.

    Send a message to the AI and get a response. Supports streaming,
    file attachments, conversation history, and multiple context modes.

    Examples:
        pollix chat "Hello!"
        pollix chat "Explain this code" -f src/main.py
        pollix chat "Review this" -f *.py --context-mode full
        echo "Hello" | pollix chat -
        pollix chat  # Interactive mode
    """
    # Load configuration
    config_manager = ConfigManager()
    cli_overrides = {
        k: v for k, v in {
            "api_key": api_key,
            "default_model": model,
            "default_context_mode": context_mode,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "verbose": verbose,
            "debug": debug,
        }.items() if v is not None
    }
    config = config_manager.load_config(cli_overrides)

    # Initialize renderer
    render = Render(theme=config.theme, verbose=config.verbose, debug=config.debug)

    # Check API key
    if not config.api_key:
        render.print_error(
            "No API key configured. Set POLLINATION_API_KEY environment variable "
            "or run 'pollix init --global' to configure."
        )
        raise typer.Exit(1)

    # Handle stdin input
    if message == "-" or (message is None and not sys.stdin.isatty()):
        stdin_content = read_stdin()
        if stdin_content:
            if message and message != "-":
                message = f"{message}\n\n{stdin_content}"
            else:
                message = stdin_content
        elif message == "-":
            message = ""

    # Enter interactive mode if no message
    if not message:
        _interactive_mode(config, render, file or [], context_mode, system, save)
        return

    # Load previous conversation if requested
    conversation_history = []
    if load:
        previous = _load_conversation(load)
        conversation_history = [
            Message.from_dict(msg) for msg in previous[-history_count:]
        ]
        render.print_verbose(f"Loaded conversation '{load}' ({len(conversation_history)} messages)")

    # Read attached files
    file_contents = {}
    if file:
        for file_path in file:
            try:
                content = read_file(file_path, max_size=config.max_file_size)
                file_contents[file_path] = content
                render.print_verbose(f"Attached file: {file_path} ({len(content)} chars)")
            except Exception as e:
                render.print_warning(f"Could not read file '{file_path}': {e}")

    # Build context
    ctx_mode = context_mode or config.default_context_mode or "auto"
    custom_files = list(file_contents.keys()) if ctx_mode == "files" else None

    with render.status("Building context..."):
        builder = ContextBuilder()
        context = builder.build(
            mode=ContextMode(ctx_mode),
            custom_files=custom_files,
            custom_prompt=system,
        )

    render.print_verbose(f"Context mode: {ctx_mode}")
    render.print_verbose(f"Estimated tokens: {context.estimated_tokens}")

    # Prepare the full message with context
    full_message = message
    if file_contents:
        file_sections = []
        for path, content in file_contents.items():
            file_sections.append(f"## File: {path}\n```\n{content}\n```")
        full_message = full_message + "\n\n" + "\n\n".join(file_sections)

    # Add context if not in minimal mode
    if ctx_mode != "minimal":
        context_prompt = context.to_prompt()
        full_message = f"{context_prompt}\n\n---\n\n{full_message}"

    # Send request
    try:
        client = PollinationClient(
            api_key=config.api_key,
        )

        use_stream = stream if stream is not None else config.stream_output

        if use_stream:
            # Streaming response
            render.print_verbose("Using streaming mode")

            with render.status("Waiting for response..."):
                token_iterator = client.chat_stream(
                    message=full_message,
                    model=config.default_model,
                    system_prompt=context.system_prompt if ctx_mode == "minimal" else None,
                    conversation_history=conversation_history if load else None,
                    temperature=config.temperature,
                    max_tokens=config.max_tokens,
                )

            # Stream to console
            response_text = ""
            for token in token_iterator:
                response_text += token
                render.print(token, end="")

            render.print()  # Newline
        else:
            # Non-streaming response
            with render.status("Waiting for response..."):
                response = client.chat(
                    message=full_message,
                    model=config.default_model,
                    system_prompt=context.system_prompt if ctx_mode == "minimal" else None,
                    conversation_history=conversation_history if load else None,
                    temperature=config.temperature,
                    max_tokens=config.max_tokens,
                )
                response_text = response.content

            # Render response as markdown
            render.print_markdown(response_text)

        # Save conversation if requested
        if save:
            all_messages = []
            if load:
                all_messages = _load_conversation(load)

            all_messages.append({"role": "user", "content": message})
            all_messages.append({"role": "assistant", "content": response_text})

            _save_conversation(save, all_messages)
            render.print_success(f"Conversation saved as '{save}'")

        client.close()

    except Exception as e:
        render.print_error(f"Request failed: {e}")
        raise typer.Exit(1)


def _interactive_mode(
    config: Config,
    render: Render,
    files: List[str],
    context_mode: Optional[str],
    system_prompt: Optional[str],
    save_name: Optional[str],
) -> None:
    """Run interactive chat session.

    Args:
        config: Current configuration.
        render: Renderer instance.
        files: List of attached files.
        context_mode: Context mode override.
        system_prompt: Custom system prompt.
        save_name: Conversation save name.
    """
    render.print_banner()
    render.print_info(f"Model: [bold]{config.default_model}[/bold]")
    render.print_info(f"Context mode: [bold]{context_mode or config.default_context_mode}[/bold]")
    render.print_info("Type [bold]/help[/bold] for commands, [bold]/quit[/bold] to exit")
    render.rule()

    # Build context once for the session
    ctx_mode = context_mode or config.default_context_mode or "auto"
    builder = ContextBuilder()
    context = builder.build(
        mode=ContextMode(ctx_mode),
        custom_prompt=system_prompt,
    )

    # Read attached files
    file_contents = {}
    for file_path in files:
        try:
            content = read_file(file_path, max_size=config.max_file_size)
            file_contents[file_path] = content
        except Exception as e:
            render.print_warning(f"Could not read file '{file_path}': {e}")

    conversation_history: List[Message] = []
    all_messages: List[dict] = []

    client = PollinationClient(api_key=config.api_key)

    try:
        while True:
            try:
                user_input = render.prompt("You")
            except (EOFError, KeyboardInterrupt):
                render.print()
                break

            if not user_input.strip():
                continue

            # Handle commands
            if user_input.startswith("/"):
                cmd = user_input[1:].strip().lower()
                if cmd in ("quit", "q", "exit"):
                    break
                elif cmd == "help":
                    _print_help(render)
                    continue
                elif cmd == "clear":
                    render.clear()
                    continue
                elif cmd == "context":
                    render.print_info(f"Context mode: {ctx_mode}")
                    render.print_info(f"Estimated tokens: {context.estimated_tokens}")
                    continue
                elif cmd.startswith("save "):
                    name = cmd[5:].strip()
                    if name:
                        _save_conversation(name, all_messages)
                        render.print_success(f"Conversation saved as '{name}'")
                    continue
                elif cmd.startswith("load "):
                    name = cmd[5:].strip()
                    loaded = _load_conversation(name)
                    if loaded:
                        conversation_history = [Message.from_dict(m) for m in loaded[-20:]]
                        all_messages = loaded
                        render.print_success(f"Loaded conversation '{name}'")
                    else:
                        render.print_warning(f"No conversation found: '{name}'")
                    continue
                else:
                    render.print_warning(f"Unknown command: /{cmd}")
                    continue

            # Prepare message
            full_message = user_input
            if file_contents:
                file_sections = []
                for path, content in file_contents.items():
                    file_sections.append(f"## File: {path}\n```\n{content}\n```")
                full_message = full_message + "\n\n" + "\n\n".join(file_sections)

            if ctx_mode != "minimal":
                context_prompt = context.to_prompt()
                full_message = f"{context_prompt}\n\n---\n\n{full_message}"

            # Send request
            try:
                token_iterator = client.chat_stream(
                    message=full_message,
                    model=config.default_model,
                    system_prompt=context.system_prompt if ctx_mode == "minimal" else None,
                    conversation_history=conversation_history[-10:] if conversation_history else None,
                    temperature=config.temperature,
                    max_tokens=config.max_tokens,
                )

                render.print("[bold cyan]Assistant:[/bold cyan] ", end="")

                response_text = ""
                for token in token_iterator:
                    response_text += token
                    render.print(token, end="")

                render.print()

                # Update conversation history
                conversation_history.append(Message.user(user_input))
                conversation_history.append(Message.assistant(response_text))

                all_messages.append({"role": "user", "content": user_input})
                all_messages.append({"role": "assistant", "content": response_text})

            except Exception as e:
                render.print_error(f"Request failed: {e}")

    finally:
        client.close()

        if save_name:
            _save_conversation(save_name, all_messages)
            render.print_success(f"Conversation saved as '{save_name}'")

        render.print_info("Goodbye!")


def _print_help(render: Render) -> None:
    """Print interactive mode help.

    Args:
        render: Renderer instance.
    """
    help_text = """
## Interactive Commands

- **/quit** or **/q** - Exit the session
- **/clear** - Clear the screen
- **/context** - Show current context info
- **/save <name>** - Save conversation
- **/load <name>** - Load a conversation
- **/help** - Show this help

## Tips

- Use ↑/↓ arrow keys to navigate input history
- Paste multi-line text with Ctrl+Shift+V
- Code blocks are automatically syntax-highlighted
"""
    render.print_markdown(help_text)
