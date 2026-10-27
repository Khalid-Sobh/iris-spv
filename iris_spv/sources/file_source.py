"""Reads records from a JSONL file (one JSON object per line).

Used for three things:
  * the synthetic fixtures shipped in the repo (fully reproducible runs)
  * records exported by hand from the public portal (within its 60/hour limit)
  * reference data (e.g. open-data dumps) used by `crosscheck`
"""
import json
from pathlib import Path
from typing import Iterator


class FileSource:
    def __init__(self, path: str, name: str):
        self.path = Path(path)
        self.name = name

    def fetch(self) -> Iterator[dict]:
        with self.path.open(encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    # Don't crash the run: flag the line, normalize() rejects it.
                    yield {"_malformed_line": lineno, "_text": line.strip()[:200]}
