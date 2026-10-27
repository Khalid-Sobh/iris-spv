"""Factory: turn a CLI source name into an adapter, so cli.py stays generic."""
from pathlib import Path

from iris_spv.sources.file_source import FileSource
from iris_spv.sources.portal import PortalSource

DEFAULT_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "handelsregister_sample.jsonl"


def get_source(name: str, path: str | None = None, max_per_hour: int = 60):
    if name == "fixture":
        return FileSource(path or str(DEFAULT_FIXTURE), name="fixture")
    if name == "export":
        if not path:
            raise ValueError("--source export needs --path <file.jsonl>")
        return FileSource(path, name="handelsregister_export")
    if name == "portal":
        return PortalSource(max_per_hour=max_per_hour)
    raise ValueError(f"unknown source: {name}")
