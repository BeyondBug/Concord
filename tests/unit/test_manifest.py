# Manifest loader tests
# TODO Phase 1


def test_manifest_loads_as_utf8_regardless_of_platform_encoding(tmp_path):
    # Regression: connectors/tools.yaml was saved as cp1252 and load_manifest
    # used the platform default encoding, so it only loaded on Windows.
    from core.manifest import load_manifest
    p = tmp_path / "tools.yaml"
    p.write_bytes('version: "1.0"\n# kagent — em dash\nconnectors: []\n'.encode())
    assert load_manifest(str(p)).connectors == []


def test_repo_manifest_is_valid_utf8():
    from pathlib import Path
    Path("connectors/tools.yaml").read_bytes().decode("utf-8")
