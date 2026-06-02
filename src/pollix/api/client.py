"""Pollination API client with streaming support and error handling.

This module provides a robust HTTP client for the Pollination AI API,
supporting both streaming (SSE) and non-streaming modes with automatic
retries, rate limiting, and proper timeout handling.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Union

import httpx

# API Configuration
API_BASE_URL = "https://gen.pollinations.ai"
CHAT_COMPLETIONS_ENDPOINT = f"{API_BASE_URL}/v1/chat/completions"
MODELS_ENDPOINT = f"{API_BASE_URL}/v1/models"
API_KEY_ENV_VARS = ("POLLINATIONS_KEY", "POLLINATION_API_KEY", "POLLIX_API_KEY")

# Timeout configuration (connect, read, write, pool)
DEFAULT_TIMEOUT = httpx.Timeout(connect=30.0, read=120.0, write=30.0, pool=5.0)

# Retry configuration
MAX_RETRIES = 5
MIN_BACKOFF = 1.0
MAX_BACKOFF = 60.0
BACKOFF_MULTIPLIER = 2.0

# Known Pollinations text/audio model identifiers. The API can add models at any
# time, so this list is used for defaults, prompts, and helpful error messages;
# callers may still pass a custom model name.
AVAILABLE_MODELS = [
    "openai",
    "openai-fast",
    "openai-large",
    "gpt-5.4-mini",
    "gpt-5.5",
    "qwen-coder",
    "mistral",
    "mistral-4",
    "openai-audio",
    "openai-audio-large",
    "gemini",
    "gemini-3.5-flash",
    "gemini-flash-lite-3.1",
    "gemini-fast",
    "deepseek",
    "gemma",
    "deepseek-pro",
    "grok",
    "grok-large",
    "grok-4.3",
    "gemini-search",
    "gemini-search-fast",
    "gemini-search-large",
    "midijourney",
    "midijourney-large",
    "claude-fast",
    "claude",
    "claude-large",
    "claude-opus-4.7",
    "claude-opus-4.8",
    "perplexity-fast",
    "perplexity-deep",
    "perplexity",
    "perplexity-reasoning",
    "kimi",
    "kimi-k2.6",
    "gemini-large",
    "nova-fast",
    "nova",
    "glm",
    "llama",
    "llama-maverick",
    "llama-scout",
    "minimax",
    "mistral-large",
    "polly",
    "qwen-coder-large",
    "qwen-large",
    "qwen-vision",
    "qwen-vision-pro",
    "step-flash",
    "step-3.5-flash",
    "qwen-safety",
]
DEFAULT_MODEL = "openai"
RECOMMENDED_MODELS = [
    "openai",
    "openai-fast",
    "claude",
    "gemini",
    "deepseek",
    "gemma",
    "kimi",
    "qwen-coder",
]


class APIError(Exception):
    """Base exception for API-related errors."""

    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_body = response_body

    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code:
            parts.append(f"(HTTP {self.status_code})")
        if self.response_body:
            parts.append(f"Response: {self.response_body[:500]}")
        return " ".join(parts)


class AuthenticationError(APIError):
    """Raised when API authentication fails (401)."""

    def __init__(
        self,
        message: str = "Authentication failed. Check POLLINATIONS_KEY or POLLINATION_API_KEY.",
        response_body: Optional[str] = None,
    ) -> None:
        super().__init__(message, status_code=401, response_body=response_body)


class RateLimitError(APIError):
    """Raised when rate limit is exceeded (429)."""

    def __init__(self, message: str = "Rate limit exceeded. Please wait before retrying.", retry_after: Optional[int] = None, response_body: Optional[str] = None) -> None:
        super().__init__(message, status_code=429, response_body=response_body)
        self.retry_after = retry_after


class ServerError(APIError):
    """Raised when server returns 5xx error."""

    def __init__(self, message: str = "Server error. Please try again later.", status_code: int = 500, response_body: Optional[str] = None) -> None:
        super().__init__(message, status_code=status_code, response_body=response_body)


class ValidationError(APIError):
    """Raised when request validation fails (400)."""

    def __init__(self, message: str = "Invalid request. Check your parameters.", response_body: Optional[str] = None) -> None:
        super().__init__(message, status_code=400, response_body=response_body)


class MessageRole(str, Enum):
    """Valid message roles for the Pollination API."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


@dataclass
class Message:
    """A single message in the conversation."""

    role: MessageRole
    content: Union[str, List[Dict[str, Any]]]

    def to_dict(self) -> Dict[str, Any]:
        """Convert message to API-compatible dictionary."""
        return {"role": self.role.value, "content": self.content}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        """Create a Message from a dictionary."""
        return cls(
            role=MessageRole(data.get("role", "user")),
            content=data.get("content", ""),
        )

    @classmethod
    def user(cls, content: Union[str, List[Dict[str, Any]]]) -> "Message":
        """Create a user message."""
        return cls(role=MessageRole.USER, content=content)

    @classmethod
    def assistant(cls, content: str) -> "Message":
        """Create an assistant message."""
        return cls(role=MessageRole.ASSISTANT, content=content)

    @classmethod
    def system(cls, content: str) -> "Message":
        """Create a system message."""
        return cls(role=MessageRole.SYSTEM, content=content)


@dataclass
class ChatRequest:
    """Request payload for the chat API."""

    messages: List[Message]
    model: str = DEFAULT_MODEL
    stream: bool = True
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    seed: Optional[int] = None
    response_format: Optional[Dict[str, str]] = None

    def to_api_payload(self) -> Dict[str, Any]:
        """Convert to the API request format."""
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [msg.to_dict() for msg in self.messages],
            "stream": self.stream,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        if self.top_p is not None:
            payload["top_p"] = self.top_p
        if self.top_k is not None:
            payload["top_k"] = self.top_k
        if self.frequency_penalty is not None:
            payload["frequency_penalty"] = self.frequency_penalty
        if self.presence_penalty is not None:
            payload["presence_penalty"] = self.presence_penalty
        if self.seed is not None:
            payload["seed"] = self.seed
        if self.response_format is not None:
            payload["response_format"] = self.response_format

        return payload


@dataclass
class ChatResponse:
    """Response from the chat API."""

    content: str
    model: str
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
    raw_response: Optional[Dict[str, Any]] = None


class PollinationClient:
    """HTTP client for the Pollination AI API.

    Provides methods for sending chat requests with support for both streaming
    and non-streaming responses. Handles authentication, retries with exponential
    backoff, and proper error handling.

    Example:
        >>> client = PollinationClient(api_key="your-key")
        >>> response = client.chat("Hello, how are you?")
        >>> print(response.content)

        >>> # Streaming
        >>> for token in client.chat_stream("Tell me a story"):
        ...     print(token, end="", flush=True)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = API_BASE_URL,
        timeout: Optional[httpx.Timeout] = None,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        """Initialize the API client.

        Args:
            api_key: Pollination API key. If not provided, reads from
                     POLLINATIONS_KEY or POLLINATION_API_KEY environment variable.
            base_url: Base URL for the API.
            timeout: Request timeout configuration.
            max_retries: Maximum number of retry attempts.

        Raises:
            AuthenticationError: If no API key is provided or found in environment.
        """
        self.api_key = api_key or self._api_key_from_env()

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout or DEFAULT_TIMEOUT
        self.max_retries = max_retries

        # Initialize HTTP client with connection pooling. Keep HTTP/2 disabled so
        # the CLI works with the normal httpx install and does not require the
        # optional h2 package.
        self._client = httpx.Client(
            timeout=self.timeout,
            headers=self._default_headers(),
            http2=False,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )

    @staticmethod
    def _api_key_from_env() -> Optional[str]:
        """Return the first supported Pollinations API key from the environment."""
        for env_var in API_KEY_ENV_VARS:
            value = os.environ.get(env_var)
            if value:
                return value
        return None

    def _default_headers(self) -> Dict[str, str]:
        """Generate default HTTP headers for all requests."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": f"pollix/0.1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff delay.

        Args:
            attempt: Current retry attempt (0-indexed).

        Returns:
            Delay in seconds, clamped between MIN_BACKOFF and MAX_BACKOFF.
        """
        delay = MIN_BACKOFF * (BACKOFF_MULTIPLIER ** attempt)
        return min(delay, MAX_BACKOFF)

    def _handle_error_response(self, response: httpx.Response) -> None:
        """Process error responses and raise appropriate exceptions.

        Args:
            response: The HTTP response to process.

        Raises:
            AuthenticationError: For 401 responses.
            RateLimitError: For 429 responses.
            ValidationError: For 400 responses.
            ServerError: For 5xx responses.
            APIError: For other error responses.
        """
        status_code = response.status_code
        try:
            body = response.text
        except Exception:
            body = "<unable to read response body>"

        if status_code == 401:
            raise AuthenticationError(response_body=body)
        elif status_code == 429:
            retry_after = None
            try:
                retry_after = int(response.headers.get("retry-after", 0))
            except (ValueError, TypeError):
                pass
            raise RateLimitError(retry_after=retry_after, response_body=body)
        elif status_code == 400:
            raise ValidationError(response_body=body)
        elif status_code >= 500:
            raise ServerError(status_code=status_code, response_body=body)
        else:
            raise APIError(
                f"Unexpected error: {response.reason_phrase}",
                status_code=status_code,
                response_body=body,
            )

    def _make_request(
        self, payload: Dict[str, Any], stream: bool = False
    ) -> httpx.Response:
        """Make HTTP request with retry logic.

        Args:
            payload: Request body payload.
            stream: Whether to request a streaming response.

        Returns:
            The HTTP response object.

        Raises:
            APIError: If all retries are exhausted or a non-retryable error occurs.
        """
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                response = self._client.post(
                    CHAT_COMPLETIONS_ENDPOINT,
                    json=payload,
                    headers={"Accept": "text/event-stream" if stream else "application/json"},
                    timeout=self.timeout,
                )

                if response.status_code == 200:
                    return response

                # Handle retryable errors without raising before the next attempt.
                if response.status_code in (429, 500, 502, 503, 504):
                    body = response.text[:500]
                    if response.status_code == 429:
                        retry_after = None
                        try:
                            retry_after = int(response.headers.get("retry-after", 0))
                        except (ValueError, TypeError):
                            pass
                        last_error = RateLimitError(
                            retry_after=retry_after,
                            response_body=body,
                        )
                        delay = retry_after or self._calculate_backoff(attempt)
                    else:
                        last_error = ServerError(
                            status_code=response.status_code,
                            response_body=body,
                        )
                        delay = self._calculate_backoff(attempt)
                    time.sleep(delay)
                    continue

                # Non-retryable errors
                self._handle_error_response(response)

            except httpx.TimeoutException as e:
                last_error = APIError(f"Request timeout: {e}", status_code=408)
                delay = self._calculate_backoff(attempt)
                time.sleep(delay)

            except httpx.NetworkError as e:
                last_error = APIError(f"Network error: {e}")
                delay = self._calculate_backoff(attempt)
                time.sleep(delay)

            except (AuthenticationError, ValidationError):
                raise

        # All retries exhausted
        if last_error:
            raise last_error
        raise APIError("Max retries exceeded")

    def chat(
        self,
        message: str,
        model: str = DEFAULT_MODEL,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[List[Message]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        top_p: Optional[float] = None,
        frequency_penalty: Optional[float] = None,
        presence_penalty: Optional[float] = None,
        seed: Optional[int] = None,
        response_format: Optional[Dict[str, str]] = None,
    ) -> ChatResponse:
        """Send a chat message and get a complete response.

        Args:
            message: The user message to send.
            model: Model name to use.
            system_prompt: Optional system prompt to set context.
            conversation_history: Previous messages in the conversation.
            temperature: Sampling temperature (0.0 - 1.0).
            max_tokens: Maximum tokens in the response.
            top_p: Nucleus sampling cutoff.
            frequency_penalty: Penalize repeated tokens by frequency.
            presence_penalty: Penalize tokens already present.
            seed: Best-effort deterministic seed, if supported by the model.
            response_format: OpenAI-compatible response format object.

        Returns:
            ChatResponse containing the assistant's reply.

        Raises:
            APIError: If the request fails after all retries.
        """
        messages: List[Message] = []

        if system_prompt:
            messages.append(Message.system(system_prompt))

        if conversation_history:
            messages.extend(conversation_history)

        messages.append(Message.user(message))

        request = ChatRequest(
            messages=messages,
            model=model,
            stream=False,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            frequency_penalty=frequency_penalty,
            presence_penalty=presence_penalty,
            seed=seed,
            response_format=response_format,
        )

        payload = request.to_api_payload()
        response = self._make_request(payload, stream=False)

        try:
            data = response.json()
        except json.JSONDecodeError as e:
            raise APIError(f"Failed to parse response: {e}", response_body=response.text[:500])

        # Parse the response - handle different API response formats
        content = self._extract_content(data)

        return ChatResponse(
            content=content,
            model=model,
            raw_response=data,
        )

    def chat_stream(
        self,
        message: str,
        model: str = DEFAULT_MODEL,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[List[Message]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        top_p: Optional[float] = None,
        frequency_penalty: Optional[float] = None,
        presence_penalty: Optional[float] = None,
        seed: Optional[int] = None,
        response_format: Optional[Dict[str, str]] = None,
    ) -> Iterator[str]:
        """Send a chat message and stream the response tokens.

        Args:
            message: The user message to send.
            model: Model name to use.
            system_prompt: Optional system prompt to set context.
            conversation_history: Previous messages in the conversation.
            temperature: Sampling temperature (0.0 - 1.0).
            max_tokens: Maximum tokens in the response.
            top_p: Nucleus sampling cutoff.
            frequency_penalty: Penalize repeated tokens by frequency.
            presence_penalty: Penalize tokens already present.
            seed: Best-effort deterministic seed, if supported by the model.
            response_format: OpenAI-compatible response format object.

        Yields:
            Response tokens as they arrive from the API.

        Raises:
            APIError: If the request fails.
        """
        messages: List[Message] = []

        if system_prompt:
            messages.append(Message.system(system_prompt))

        if conversation_history:
            messages.extend(conversation_history)

        messages.append(Message.user(message))

        request = ChatRequest(
            messages=messages,
            model=model,
            stream=True,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            frequency_penalty=frequency_penalty,
            presence_penalty=presence_penalty,
            seed=seed,
            response_format=response_format,
        )

        payload = request.to_api_payload()

        try:
            response = self._make_request(payload, stream=True)
        except APIError:
            raise

        # Parse Server-Sent Events
        for line in response.iter_lines():
            if not line:
                continue

            line_str = line.decode("utf-8") if isinstance(line, bytes) else line

            # Skip SSE comments and non-data lines
            if not line_str.startswith("data: "):
                continue

            data_str = line_str[6:]  # Remove "data: " prefix

            # Check for stream end
            if data_str.strip() == "[DONE]":
                break

            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            # Extract token from various SSE formats
            token = self._extract_stream_token(data)
            if token:
                yield token

    def _extract_content(self, data: Dict[str, Any]) -> str:
        """Extract content string from API response.

        Handles multiple response formats that the API might return.

        Args:
            data: Parsed JSON response from the API.

        Returns:
            The extracted content string.
        """
        # Format 1: {"outputs": "content"}
        if "outputs" in data:
            outputs = data["outputs"]
            if isinstance(outputs, str):
                return outputs
            elif isinstance(outputs, dict):
                return outputs.get("text", outputs.get("content", str(outputs)))
            elif isinstance(outputs, list) and len(outputs) > 0:
                first = outputs[0]
                if isinstance(first, dict):
                    return first.get("text", first.get("content", str(first)))
                return str(first)

        # Format 2: {"choices": [{"message": {"content": "..."}}]}
        if "choices" in data:
            choices = data["choices"]
            if isinstance(choices, list) and len(choices) > 0:
                choice = choices[0]
                if isinstance(choice, dict):
                    if "message" in choice and isinstance(choice["message"], dict):
                        return choice["message"].get("content", "")
                    if "text" in choice:
                        return choice["text"]
                    if "content" in choice:
                        return choice["content"]

        # Format 3: {"response": "..."} or {"text": "..."}
        if "response" in data:
            return str(data["response"])
        if "text" in data:
            return str(data["text"])
        if "content" in data:
            return str(data["content"])

        # Fallback: return the whole response as string
        return str(data)

    def _extract_stream_token(self, data: Dict[str, Any]) -> Optional[str]:
        """Extract a token from a streaming SSE data payload.

        Args:
            data: Parsed JSON from an SSE data line.

        Returns:
            The token string, or None if no valid token found.
        """
        # Format 1: {"token": {"text": "..."}}
        if "token" in data:
            token_data = data["token"]
            if isinstance(token_data, dict):
                return token_data.get("text", token_data.get("content", ""))
            return str(token_data)

        # Format 2: {"choices": [{"delta": {"content": "..."}}]}
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

        # Format 3: {"outputs": "..."}
        if "outputs" in data:
            outputs = data["outputs"]
            if isinstance(outputs, str):
                return outputs
            if isinstance(outputs, dict):
                return outputs.get("text", outputs.get("content", ""))

        # Format 4: Direct content fields
        if "text" in data:
            return str(data["text"])
        if "content" in data:
            return str(data["content"])

        return None

    def validate_model(self, model: str) -> str:
        """Validate and return a model name.

        Args:
            model: Requested model name.

        Returns:
            The model name if valid.

        Raises:
            ValidationError: If the model is not recognized.
        """
        if not model or not model.strip():
            raise ValidationError("Model name cannot be empty.")

        return model.strip()

    def list_models(self) -> List[str]:
        """Fetch available model names from the Pollinations model endpoint.

        Returns:
            Sorted model names. Falls back to the bundled known model list if the
            discovery endpoint is unavailable or returns an unexpected shape.
        """
        try:
            response = self._client.get(MODELS_ENDPOINT, timeout=self.timeout)
            if response.status_code != 200:
                return list(AVAILABLE_MODELS)

            data = response.json()
            if isinstance(data, dict) and isinstance(data.get("data"), list):
                return sorted(
                    str(item["id"])
                    for item in data["data"]
                    if isinstance(item, dict) and item.get("id")
                ) or list(AVAILABLE_MODELS)
            if isinstance(data, list):
                names = []
                for item in data:
                    if isinstance(item, dict):
                        name = item.get("id") or item.get("name")
                        if name:
                            names.append(str(name))
                    elif isinstance(item, str):
                        names.append(item)
                return sorted(set(names)) or list(AVAILABLE_MODELS)
        except Exception:
            return list(AVAILABLE_MODELS)

        return list(AVAILABLE_MODELS)

    def close(self) -> None:
        """Close the HTTP client and release resources."""
        self._client.close()

    def __enter__(self) -> "PollinationClient":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.close()
