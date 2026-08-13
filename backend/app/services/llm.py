"""Provider boundary for validated LLM outputs.

Key features:
- Singleton client: genai.Client is created once at module level, not per call.
- Smart 429 rate-limit backoff: handles RESOURCE_EXHAUSTED errors gracefully by respecting quota reset windows.
- Valid SDK v2 model fallbacks: gemini-2.0-flash, gemini-2.0-flash-lite, gemini-1.5-flash-8b.
- Token usage logging for cost & performance monitoring.
- Clear diagnostic error messages when quota is fully exhausted.
"""

from __future__ import annotations

import logging
import random
import re
import threading
import time
from typing import TypeVar

from google import genai
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)

StructuredOutput = TypeVar("StructuredOutput", bound=BaseModel)

# Valid model fallback list for Google GenAI v2 SDK
FALLBACK_MODELS = [
    settings.GEMINI_MODEL,
    "gemini-flash-latest",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]

# ── Singleton client ────────────────────────────────────────────────────────
_client: genai.Client | None = None
_client_lock = threading.Lock()


def _get_client() -> genai.Client:
    """Return the shared Gemini client, creating it on first call (thread-safe)."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:  # double-checked locking
                _client = genai.Client(api_key=settings.GEMINI_API_KEY)
                logger.info("Gemini client initialised (default_model=%s)", settings.GEMINI_MODEL)
    return _client


# ── Public errors ───────────────────────────────────────────────────────────

class LLMServiceError(RuntimeError):
    """Raised when a provider cannot produce a valid structured result."""


def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "resource_exhausted" in msg or "quota" in msg


def _extract_retry_seconds(exc: Exception) -> float | None:
    """Extract retryDelay from Google API error response if available."""
    match = re.search(r"retry in (\d+(?:\.\d+)?)s", str(exc), re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


# ── Core call ───────────────────────────────────────────────────────────────

def generate_structured(
    prompt: str,
    output_type: type[StructuredOutput],
    *,
    attempts: int = 5,
) -> StructuredOutput:
    """Call Gemini and parse the response into a validated Pydantic model.

    Handles 429 rate limits gracefully with backoff and model fallback.
    """
    if settings.LLM_PROVIDER != "gemini":
        raise LLMServiceError(f"Unsupported LLM provider: {settings.LLM_PROVIDER}")
    if not settings.GEMINI_API_KEY:
        raise LLMServiceError("GEMINI_API_KEY is required for this workflow stage.")

    client = _get_client()
    last_error: Exception | None = None

    # Filter invalid/empty models and deduplicate
    models_to_try = []
    for m in FALLBACK_MODELS:
        if m and m not in models_to_try:
            models_to_try.append(m)

    for attempt in range(1, attempts + 1):
        model_name = models_to_try[(attempt - 1) % len(models_to_try)]
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_json_schema": output_type.model_json_schema(),
                },
            )
            result = output_type.model_validate_json(response.text)

            usage = getattr(response, "usage_metadata", None)
            if usage:
                logger.debug(
                    "LLM call success | model=%s type=%s prompt_tokens=%s output_tokens=%s",
                    model_name,
                    output_type.__name__,
                    getattr(usage, "prompt_token_count", "?"),
                    getattr(usage, "candidates_token_count", "?"),
                )
            return result

        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                if _is_rate_limit_error(exc):
                    suggested_delay = _extract_retry_seconds(exc)
                    # Respect Google's retry delay if provided, up to 25 seconds max delay
                    delay = min(suggested_delay + 1.0, 25.0) if suggested_delay else max(5.0, attempt * 4.0)
                    logger.warning(
                        "Gemini rate limit (429) on attempt %d/%d for %s (model %s) — backing off for %.1fs: %s",
                        attempt,
                        attempts,
                        output_type.__name__,
                        model_name,
                        delay,
                        exc,
                    )
                else:
                    base_delay = 2 ** attempt
                    jitter = base_delay * 0.3 * (random.random() * 2 - 1)
                    delay = max(1.0, base_delay + jitter)
                    logger.warning(
                        "LLM attempt %d/%d failed for %s (model %s) — retrying in %.1fs: %s",
                        attempt,
                        attempts,
                        output_type.__name__,
                        model_name,
                        delay,
                        exc,
                    )
                time.sleep(delay)

    if last_error and _is_rate_limit_error(last_error):
        raise LLMServiceError(
            f"Gemini API rate limit / daily quota reached (HTTP 429) for {output_type.__name__}. "
            "Please wait 30–60 seconds before clicking 'Retry from checkpoint', or verify your GEMINI_API_KEY in backend/.env."
        ) from last_error

    raise LLMServiceError(
        f"The model failed to produce a valid {output_type.__name__} after {attempts} attempts: {last_error}"
    ) from last_error
