"""Tool Registry — discovers connectors from the manifest at startup."""
from core.models.manifest import ManifestConfig, ConnectorConfig


class ToolRegistry:
    def __init__(self, manifest: ManifestConfig):
        self._connectors: dict[str, ConnectorConfig] = {
            c.name: c for c in manifest.connectors
        }

    def get_connectors_for_agent(self, agent_domain: str) -> list[ConnectorConfig]:
        return [c for c in self._connectors.values() if c.agent == agent_domain]

    def list_all(self) -> list[ConnectorConfig]:
        return list(self._connectors.values())

    # TODO Phase 1: health-check each connector on startup
    # TODO Phase 1: emit metrics on connector availability
