"""The ingest run: fetch -> normalize -> score -> dedupe -> load. Nothing else.

Stages are plain functions (normalize, score_spv) so each is unit-testable.
"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from iris_spv.load import Loader
from iris_spv.models import RecordRejected
from iris_spv.normalize import normalize
from iris_spv.signals import score_spv


@dataclass
class RunStats:
    run_id: str
    source: str
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    rejected: Counter = field(default_factory=Counter)   # reason -> count

    def as_dict(self) -> dict:
        return {"run_id": self.run_id, "source": self.source, "fetched": self.fetched,
                "inserted": self.inserted, "updated": self.updated, "unchanged": self.unchanged,
                "rejected_total": sum(self.rejected.values()), "rejected": dict(self.rejected)}


def run_ingest(source, loader: Loader, run_id: str, log, now: datetime | None = None) -> RunStats:
    stats = RunStats(run_id=run_id, source=source.name)
    seen: dict[str, str] = {}      # record_id -> content_hash seen earlier in THIS run
    log.info("run_started")

    for raw in source.fetch():
        stats.fetched += 1
        try:
            rec = score_spv(normalize(raw, source.name, run_id, now))

            # In-batch duplicate handling: the first occurrence wins, the rest are
            # rejected with a reason, so nothing disappears silently.
            rid = rec.identity.record_id
            if rid in seen:
                reason = "duplicate_in_batch" if seen[rid] == rec.content_hash else "conflicting_duplicate"
                raise RecordRejected(reason, rid)
            seen[rid] = rec.content_hash

            outcome = loader.upsert(rec)          # inserted | updated | unchanged
            setattr(stats, outcome, getattr(stats, outcome) + 1)
        except RecordRejected as e:
            stats.rejected[e.reason] += 1
            loader.save_reject(run_id, source.name, e.reason, e.detail, raw)
            log.warning("record_rejected", extra={"reason": e.reason, "detail": e.detail})

    loader.commit()
    log.info("run_finished", extra=stats.as_dict())
    return stats
