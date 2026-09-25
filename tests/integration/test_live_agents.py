"""
Live verification against a real kagent / HolmesGPT (docs/AGENTS_SETUP.md).

Marked slow and skipped unless the backends are actually reachable through the
repo manifest (connectors/tools.yaml) — these tests never pass by default and
never talk to a stand-in. Run after the port-forwards are up:

    CONCORD_ALLOW_INSECURE_TRANSPORT=1 HOLMES_MODEL=ollama-qwen \
        pytest tests/integration/test_live_agents.py -m slow -v
"""
import os
from datetime import UTC, datetime

import pytest

from core.models.finding import Finding

pytestmark = pytest.mark.slow

_REPO_MANIFEST = os.path.join(os.path.dirname(__file__), "..", "..",
                              "connectors", "tools.yaml")


@pytest.fixture(autouse=True)
def _repo_manifest(monkeypatch):
    monkeypatch.setenv("CONCORD_MANIFEST", os.path.abspath(_REPO_MANIFEST))


def _finding():
    return Finding(id="LIVE-1", source="live-test", artifact="k8s/",
                   severity="HIGH", title="Workloads may run privileged or unpinned",
                   description="Check running pods for privileged securityContext "
                               "and :latest images.",
                   raw={}, timestamp=datetime.now(UTC))


async def test_live_kagent_answers():
    from agents.kubernetes.agent import KubernetesAgent
    agent = KubernetesAgent()
    st = await agent.status(fresh=True)
    if not st.active:
        pytest.skip(f"kagent not live: {st.detail}")
    resp = await agent.analyze(_finding())
    print("\nkagent root cause:", resp.root_cause, "\nfix:", resp.suggested_fix)
    assert resp.metadata["backend"] == "kagent" and len(resp.metadata["answer"]) > 20


async def test_live_holmes_answers():
    from agents.observability.agent import ObservabilityAgent
    agent = ObservabilityAgent()
    st = await agent.status(fresh=True)
    if not st.active:
        pytest.skip(f"HolmesGPT not live: {st.detail}")
    resp = await agent.analyze(_finding())
    print("\nHolmesGPT root cause:", resp.root_cause, "\nfix:", resp.suggested_fix)
    assert resp.metadata["backend"] == "holmesgpt" and len(resp.metadata["answer"]) > 20
