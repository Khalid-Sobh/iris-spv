"""Live adapter for the public Handelsregister portal: deliberately a guarded stub.

Why a stub: the portal has no official API. Its terms of use (Nutzungsordnung) allow only
individual retrievals (point 3: no systematic retrieval to build or update a parallel
register) and cap use at 60 searches/retrievals per hour (point 5). So this adapter:
  * is disabled unless explicitly enabled,
  * always goes through the rate limiter,
  * does NOT contain a scraper. Retrieved records should be exported by hand
    (or via an authorised channel) and ingested with `--source export`.
"""
from typing import Iterator

from iris_spv.ratelimit import RateLimiter


class PortalDisabled(Exception):
    pass


class PortalSource:
    name = "handelsregister_portal"

    def __init__(self, max_per_hour: int = 60, enabled: bool = False):
        self.enabled = enabled
        self.limiter = RateLimiter(max_per_hour)

    def fetch(self) -> Iterator[dict]:
        if not self.enabled:
            raise PortalDisabled(
                "Live portal access is disabled: the portal terms forbid systematic retrieval "
                "and cap use at 60/hour. Use --source fixture, or --source export --path <file>."
            )
        self.limiter.acquire()      # every request must pass through here
        raise NotImplementedError("Portal parsing is intentionally not implemented; see README.")
        yield {}                    # pragma: no cover  (keeps this a generator)
