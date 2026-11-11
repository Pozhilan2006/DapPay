from __future__ import annotations

import json
from typing import Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from app.ai_investigation.prompts import SYSTEM_PROMPT
from app.ai_investigation.schemas import LLMInvestigationResponse
from app.core.config import Settings


class InvestigationProviderError(RuntimeError):
    pass


class InvestigationLLMProvider(Protocol):
    async def generate(self, user_prompt: str) -> LLMInvestigationResponse: ...


class OllamaInvestigationProvider:
    """Small adapter over the configured Ollama API; it exposes no tools."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client

    async def generate(self, user_prompt: str) -> LLMInvestigationResponse:
        if not self._settings.ollama_model.strip():
            raise InvestigationProviderError("Ollama model is not configured.")
        base_url = self._settings.ollama_base_url.rstrip("/")
        try:
            parsed = urlsplit(base_url)
        except ValueError:
            raise InvestigationProviderError(
                "Configured Ollama endpoint is invalid."
            ) from None
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise InvestigationProviderError(
                "Configured Ollama endpoint is invalid."
            )
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self._settings.investigation_llm_timeout_seconds
        )
        try:
            response = await client.post(
                f"{base_url}/api/chat",
                json={
                    "model": self._settings.ollama_model,
                    "stream": False,
                    "format": LLMInvestigationResponse.model_json_schema(),
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException:
            raise InvestigationProviderError(
                "Investigation provider timed out."
            ) from None
        except httpx.HTTPError:
            raise InvestigationProviderError(
                "Investigation provider is unavailable."
            ) from None
        except (ValueError, json.JSONDecodeError):
            raise InvestigationProviderError(
                "Investigation provider returned invalid JSON."
            ) from None
        finally:
            if owns_client:
                await client.aclose()
        try:
            content = payload["message"]["content"]
            if not isinstance(content, str):
                raise TypeError
            parsed_content = json.loads(content)
            return LLMInvestigationResponse.model_validate(parsed_content)
        except (KeyError, TypeError, ValueError, ValidationError):
            raise InvestigationProviderError(
                "Investigation provider returned a malformed structured response."
            ) from None
