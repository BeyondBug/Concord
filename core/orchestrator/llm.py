"""Pluggable LLM backend — swap via LLM_PROVIDER env var.

Only ever called after a Finding has passed through the triage gate
(see core/triage/gate.py). By the time a request reaches here, a rule
has already decided it's worth spending model time on.
"""
import os

import httpx

DEFAULT_TIMEOUT_SECONDS = 30.0


class LLMBackend:
    """Routes a completion request to the configured LLM provider.

    Provider is resolved once at construction from LLM_PROVIDER, not
    per request — a running instance talks to exactly one backend for
    its whole lifetime, so behavior stays predictable.
    """

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self.provider = os.getenv("LLM_PROVIDER", "ollama")
        self.ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "llama3.1")
        # Injected in tests to avoid real network calls; created per-call otherwise.
        self._http_client = http_client

    async def complete(self, system: str, user: str) -> str:
        """Run one completion.

        `system` sets the agent's behavior/persona, `user` carries the
        finding context being evaluated.
        """
        if self.provider == "ollama":
            return await self._ollama(system, user)
        elif self.provider == "anthropic":
            return await self._anthropic(system, user)
        raise ValueError(f"Unknown provider: {self.provider}")

    async def _ollama(self, system: str, user: str) -> str:
        """Call a self-hosted Ollama instance's /api/chat endpoint."""
        payload = {
            "model": self.ollama_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }

        client = self._http_client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS)
        try:
            response = await client.post(f"{self.ollama_url}/api/chat", json=payload)
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Could not reach Ollama at {self.ollama_url}. Is `ollama serve` running?"
            ) from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Ollama did not respond within {DEFAULT_TIMEOUT_SECONDS}s "
                f"(model={self.ollama_model})"
            ) from exc
        finally:
            if self._http_client is None:
                await client.aclose()

        if response.status_code != 200:
            raise RuntimeError(f"Ollama returned {response.status_code}: {response.text[:200]}")

        data = response.json()
        try:
            return data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(f"Unexpected Ollama response shape: {data}") from exc

    async def _anthropic(self, system: str, user: str) -> str:
        # TODO Phase 1: implement Anthropic API call.
        # Needs the `anthropic` package added to requirements/base.txt.
        # Not built yet because LLM_PROVIDER=ollama is the current default —
        # this is here so the interface exists once it's someone's turn to pick it up.
        raise NotImplementedError("Anthropic provider not yet implemented")