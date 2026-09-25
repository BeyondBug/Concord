"""tools.yaml loader — reads the connector manifest at runtime."""
import yaml

from core.models.manifest import ManifestConfig


def load_manifest(path: str = "connectors/tools.yaml") -> ManifestConfig:
    # Explicit UTF-8: the platform default (cp1252 on Windows) differs from Linux.
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return ManifestConfig(**data)
