"""tools.yaml loader — reads the connector manifest at runtime."""
import yaml
from core.models.manifest import ManifestConfig


def load_manifest(path: str = "connectors/tools.yaml") -> ManifestConfig:
    with open(path) as fh:
        data = yaml.safe_load(fh)
    return ManifestConfig(**data)
