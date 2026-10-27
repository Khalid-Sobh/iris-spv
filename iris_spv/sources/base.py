"""The whole source interface: a name and a fetch() that yields raw dicts."""
from typing import Iterator, Protocol


class Source(Protocol):
    name: str                       # written to the `source` column and every log line

    def fetch(self) -> Iterator[dict]:
        ...
