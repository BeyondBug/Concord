"""Router — decides which agent(s) handle a finding."""
from core.models.finding import Finding
from core.mcp_runtime.registry import ToolRegistry


class Router:
    ARTIFACT_ROUTES: dict[str, str] = {
        ".tf":        "infra",
        ".hcl":       "infra",
        ".yaml":      "kubernetes",
        ".yml":       "kubernetes",
        "Dockerfile": "cicd",
        "image:":     "cicd",
    }

    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def route(self, finding: Finding) -> list[str]:
        """Return list of agent domains that should analyze this finding."""
        for pattern, domain in self.ARTIFACT_ROUTES.items():
            if pattern in finding.artifact:
                if self.registry.get_connectors_for_agent(domain):
                    return [domain]
        return ["cicd"]  # fallback
