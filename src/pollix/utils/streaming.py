"""Streaming response handler for Server-Sent Events.

Manages parsing of SSE streams, error handling mid-stream, and
buffering of tokens for smooth output.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Iterator, List, Optional


@dataclass
class StreamChunk:
    """A single chunk from a streaming response."""

    content: str = ""
    is_error: bool = False
    is_done: bool = False
    error_message: str = ""
    raw_data: Optional[dict] = None


class StreamHandler:
    """Handle Server-Sent Event streams from the API.

    Parses SSE format, handles errors mid-stream, and yields
    clean text tokens.

    Example:
        >>> handler = StreamHandler()
        >>> for chunk in handler.process_stream(response.iter_lines()):
        ...     if chunk.is_error:
        ...         print(f"Error: {chunk.error_message}")
        ...     elif not chunk.is_done:
        ...         print(chunk.content, end="", flush=True)
    """

    def __init__(self, buffer_size: int = 10) -> None:
        """Initialize the stream handler.

        Args:
            buffer_size: Number of tokens to buffer before yielding.
        """
        self.buffer_size = buffer_size
        self._buffer: List[str] = []
        self._total_content = ""

    def _parse_sse_line(self, line: str) -> Optional[dict]:
        """Parse a single SSE line.

        Args:
            line: Raw SSE line.

        Returns:
            Parsed data dict or None.
        """
        if not line:
            return None

        # Handle "data: {...}" format
        if line.startswith("data: "):
            data_str = line[6:]

            # Stream end marker
            if data_str.strip() == "[DONE]":
                return {"__done__": True}

            try:
                return json.loads(data_str)
            except json.JSONDecodeError:
                # Return raw text if not JSON
                return {"__raw__": data_str}

        # Handle "event: ..." lines (skip)
        if line.startswith("event: "):
            return None

        # Handle "id: ..." lines (skip)
        if line.startswith("id: "):
            return None

        # Handle comments
        if line.startswith(":"):
            return None

        # Try to parse as JSON anyway
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return {"__raw__": line}

    def _extract_token(self, data: dict) -> Optional[str]:
        """Extract text token from parsed SSE data.

        Args:
            data: Parsed SSE data.

        Returns:
            Token string or None.
        """
        # Check for done marker
        if data.get("__done__"):
            return None

        # Raw text
        if "__raw__" in data:
            return str(data["__raw__"])

        # Format: {"token": {"text": "..."}}
        if "token" in data:
            token_data = data["token"]
            if isinstance(token_data, dict):
                return token_data.get("text", token_data.get("content", ""))
            return str(token_data)

        # Format: {"choices": [{"delta": {"content": "..."}}]}
        if "choices" in data:
            choices = data["choices"]
            if isinstance(choices, list) and len(choices) > 0:
                choice = choices[0]
                if isinstance(choice, dict):
                    delta = choice.get("delta", {})
                    if isinstance(delta, dict):
                        return delta.get("content", "")
                    if "text" in choice:
                        return choice["text"]

        # Format: {"outputs": "..."}
        if "outputs" in data:
            outputs = data["outputs"]
            if isinstance(outputs, str):
                return outputs
            if isinstance(outputs, dict):
                return outputs.get("text", outputs.get("content", ""))

        # Direct content fields
        if "text" in data:
            return str(data["text"])
        if "content" in data:
            return str(data["content"])
        if "response" in data:
            return str(data["response"])

        return None

    def _detect_error(self, data: dict) -> Optional[str]:
        """Detect error in SSE data.

        Args:
            data: Parsed SSE data.

        Returns:
            Error message if error detected, None otherwise.
        """
        if "error" in data:
            error = data["error"]
            if isinstance(error, dict):
                return error.get("message", str(error))
            return str(error)

        if "detail" in data:
            detail = data["detail"]
            if isinstance(detail, dict):
                return detail.get("message", str(detail))
            return str(detail)

        # Check for error-like status
        if data.get("status") in ("error", "failed"):
            return data.get("message", "Unknown error")

        return None

    def process_stream(
        self,
        line_iterator: Iterator[str],
        on_token: Optional[Callable[[str], None]] = None,
    ) -> Iterator[StreamChunk]:
        """Process a stream of SSE lines.

        Args:
            line_iterator: Iterator yielding SSE lines.
            on_token: Optional callback for each token.

        Yields:
            StreamChunk objects.
        """
        self._buffer = []
        self._total_content = ""

        for line in line_iterator:
            # Parse the line
            data = self._parse_sse_line(line)

            if data is None:
                continue

            # Check for stream done
            if data.get("__done__"):
                # Yield remaining buffer
                if self._buffer:
                    content = "".join(self._buffer)
                    yield StreamChunk(content=content)
                    self._buffer = []

                yield StreamChunk(is_done=True)
                return

            # Check for errors
            error_msg = self._detect_error(data)
            if error_msg:
                yield StreamChunk(
                    is_error=True,
                    error_message=error_msg,
                    raw_data=data,
                )
                continue

            # Extract token
            token = self._extract_token(data)
            if token:
                self._buffer.append(token)
                self._total_content += token

                if on_token:
                    on_token(token)

                # Yield when buffer is full
                if len(self._buffer) >= self.buffer_size:
                    content = "".join(self._buffer)
                    self._buffer = []
                    yield StreamChunk(content=content, raw_data=data)

        # Yield remaining buffer
        if self._buffer:
            content = "".join(self._buffer)
            yield StreamChunk(content=content)

        # Signal completion
        yield StreamChunk(is_done=True)

    def process_string_stream(self, text: str) -> Iterator[StreamChunk]:
        """Process a stream from a string (for testing/fallback).

        Args:
            text: Text to stream.

        Yields:
            StreamChunk objects simulating a stream.
        """
        # Split into words for simulated streaming
        words = text.split(" ")
        self._buffer = []

        for i, word in enumerate(words):
            token = word + (" " if i < len(words) - 1 else "")
            self._buffer.append(token)

            if len(self._buffer) >= self.buffer_size:
                content = "".join(self._buffer)
                self._buffer = []
                yield StreamChunk(content=content)

        if self._buffer:
            yield StreamChunk(content="".join(self._buffer))

        yield StreamChunk(is_done=True)

    @property
    def total_content(self) -> str:
        """Get all content received so far."""
        return self._total_content


class StreamBuffer:
    """Buffer for collecting and managing stream output.

    Provides utilities for collecting streamed content, detecting
    code blocks, and managing output formatting.
    """

    def __init__(self) -> None:
        """Initialize the buffer."""
        self.content = ""
        self._in_code_block = False
        self._code_block_lang = ""

    def append(self, token: str) -> None:
        """Append a token to the buffer.

        Args:
            token: Text token to append.
        """
        self.content += token

        # Track code blocks
        if "```" in token:
            # Simple code block tracking
            pass

    def get_code_blocks(self) -> List[dict]:
        """Extract code blocks from the content.

        Returns:
            List of code block dicts with language and code.
        """
        blocks = []
        pattern = r"```(\w*)\n(.*?)```"
        for match in re.finditer(pattern, self.content, re.DOTALL):
            blocks.append({
                "language": match.group(1) or "text",
                "code": match.group(2),
            })
        return blocks

    def is_complete(self) -> bool:
        """Check if the response appears complete.

        Returns:
            True if response looks complete.
        """
        # Check for unclosed code blocks
        code_fence_count = self.content.count("```")
        if code_fence_count % 2 != 0:
            return False

        # Check if content ends with sentence-ending punctuation
        stripped = self.content.strip()
        if stripped and stripped[-1] not in ".!?`:)":
            # Might be incomplete, but not always
            pass

        return True

    def __str__(self) -> str:
        """Return the buffered content."""
        return self.content

    def __len__(self) -> int:
        """Return the length of buffered content."""
        return len(self.content)
