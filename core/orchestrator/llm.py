"""Pluggable LLM backend — swap via LLM_PROVIDER env var. , At first we gonna move with ollama llm"""
import os
import httpx


class LLMBackend:
    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "ollama")
        self.ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    async def complete(self, system: str, user: str) -> str:
        if self.provider == "ollama":
            return await self._ollama(system, user)
        elif self.provider == "anthropic":
            return await self._anthropic(system, user)
        raise ValueError(f"Unknown provider: {self.provider}")

    async def _ollama(self, system: str, user: str) -> str:
        # TODO Phase 1: implement Ollama API call
        raise NotImplementedError

    async def _anthropic(self, system: str, user: str) -> str:
        # TODO Phase 1: implement Anthropic API call
        raise NotImplementedError
