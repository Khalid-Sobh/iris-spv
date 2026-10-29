"""Plain data containers shared by every stage of the pipeline."""
from dataclasses import dataclass, field


class RecordRejected(Exception):
    """Raised by any stage when a record cannot be accepted.

    `reason` is a short machine-readable code (it ends up in the rejects
    table and in the quality report); `detail` is free text for humans.
    """

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass
class Identity:
    """Who the company is. Used for both staged and reference records."""
    record_id: str          # stable key: court|type|number+suffix
    company_name: str
    company_name_norm: str  # casefolded, no legal form: for candidate matching only
    legal_form: str
    register_court: str
    register_type: str      # HRA / HRB
    register_number: str
    register_suffix: str


@dataclass
class Record:
    """One validated, staging-ready formation record."""
    identity: Identity
    source: str
    source_url: str
    source_date: str        # publication date at the source (ISO)
    retrieved_at: str       # when WE fetched it (ISO, UTC)
    run_id: str
    formation_event: str    # always FORMATION for accepted records
    formation_date: str | None  # ISO; None = the source states no date (never guessed)
    share_capital_eur: float | None
    activity_text: str
    content_hash: str       # hash of business fields: detects real changes
    raw_payload: str        # original record as JSON: nothing is lost
    # Filled in by signals.py. These are HYPOTHESES, never facts.
    spv_score: float = 0.0
    spv_label: str = "no_spv_signal"
    spv_evidence: list[str] = field(default_factory=list)
    activity_terms: list[str] = field(default_factory=list)
