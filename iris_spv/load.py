"""Database access + staging loader. SQL is plain; one tiny wrapper hides the
difference between Postgres (psycopg) and SQLite (stdlib).

SQL is written with %(name)s placeholders; for SQLite they become :name.
"""
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from iris_spv.models import Record

STAGING_SCHEMA = "iris_staging"   # the only schema this tool may write to
SCHEMA_SQL = Path(__file__).with_name("schema.sql")


def clean_pg_url(url: str) -> str:
    """'postgresql+psycopg2://...' (SQLAlchemy style, as in the IRIS base repo) -> 'postgresql://...'.

    psycopg itself rejects the '+driver' part, so we drop it.
    """
    return re.sub(r"^(postgres(?:ql)?)\+\w+://", r"\1://", url)


class Db:
    """Minimal wrapper: execute / query / commit."""

    def __init__(self, url: str):
        if url.startswith("sqlite:///"):
            self.dialect = "sqlite"
            path = url[len("sqlite:///"):]
            self.conn = sqlite3.connect(":memory:")
            self.conn.row_factory = sqlite3.Row
            # ATTACH makes `iris_staging.table` valid in SQLite, same as Postgres.
            self.conn.execute("ATTACH DATABASE ? AS iris_staging", (path,))
        else:
            import psycopg                      # imported lazily: tests don't need a server
            from psycopg.rows import dict_row
            self.dialect = "postgres"
            self.conn = psycopg.connect(clean_pg_url(url), row_factory=dict_row)

    def _sql(self, sql: str) -> str:
        if self.dialect == "sqlite":            # %(x)s -> :x
            return re.sub(r"%\((\w+)\)s", r":\1", sql)
        return sql

    def execute(self, sql: str, params: dict | None = None) -> None:
        self.conn.execute(self._sql(sql), params or {})

    def query(self, sql: str, params: dict | None = None) -> list[dict]:
        return [dict(r) for r in self.conn.execute(self._sql(sql), params or {}).fetchall()]

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


class Loader:
    """All writes to staging go through this class."""

    def __init__(self, db: Db, schema: str = STAGING_SCHEMA):
        # Safety guard: refuse anything but staging (e.g. a mistyped iris_core).
        if schema != STAGING_SCHEMA:
            raise ValueError(f"refusing to write to schema '{schema}': only '{STAGING_SCHEMA}' is allowed")
        self.db = db
        self.records = f"{schema}.corporate_distress_records"
        self.rejects = f"{schema}.corporate_distress_rejects"

    def init_schema(self) -> None:
        pg = self.db.dialect == "postgres"
        if pg:
            self.db.execute(f"CREATE SCHEMA IF NOT EXISTS {STAGING_SCHEMA}")
        ddl = (SCHEMA_SQL.read_text()
               .replace("@SCHEMA@", STAGING_SCHEMA)
               .replace("@TS@", "TIMESTAMPTZ" if pg else "TEXT")
               .replace("@DATE@", "DATE" if pg else "TEXT")
               .replace("@NUM@", "DOUBLE PRECISION" if pg else "REAL"))
        for statement in ddl.split(";"):
            if statement.strip():
                self.db.execute(statement)
        self.db.commit()

    def upsert(self, rec: Record) -> str:
        """Insert or update one record. Returns 'inserted' | 'updated' | 'unchanged'."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        i = rec.identity
        params = {
            "record_id": i.record_id, "source": rec.source, "source_url": rec.source_url,
            "source_date": rec.source_date, "retrieved_at": rec.retrieved_at, "run_id": rec.run_id,
            "company_name": i.company_name, "company_name_norm": i.company_name_norm,
            "legal_form": i.legal_form, "register_court": i.register_court,
            "register_type": i.register_type, "register_number": i.register_number,
            "register_suffix": i.register_suffix, "formation_event": rec.formation_event,
            "formation_date": rec.formation_date, "share_capital_eur": rec.share_capital_eur,
            "activity_text": rec.activity_text,
            "activity_terms": json.dumps(rec.activity_terms, ensure_ascii=False),
            "spv_score": rec.spv_score, "spv_label": rec.spv_label,
            "spv_evidence": json.dumps(rec.spv_evidence, ensure_ascii=False),
            "content_hash": rec.content_hash, "raw_payload": rec.raw_payload, "now": now,
        }
        existing = self.db.query(
            f"SELECT content_hash FROM {self.records} WHERE record_id = %(record_id)s", params)
        if not existing:
            self.db.execute(f"""
                INSERT INTO {self.records} (
                    record_id, source, source_url, source_date, retrieved_at, run_id,
                    company_name, company_name_norm, legal_form, register_court, register_type,
                    register_number, register_suffix, formation_event, formation_date,
                    share_capital_eur, activity_text, activity_terms, spv_score, spv_label,
                    spv_evidence, content_hash, raw_payload, first_seen_at, last_seen_at)
                VALUES (
                    %(record_id)s, %(source)s, %(source_url)s, %(source_date)s, %(retrieved_at)s, %(run_id)s,
                    %(company_name)s, %(company_name_norm)s, %(legal_form)s, %(register_court)s, %(register_type)s,
                    %(register_number)s, %(register_suffix)s, %(formation_event)s, %(formation_date)s,
                    %(share_capital_eur)s, %(activity_text)s, %(activity_terms)s, %(spv_score)s, %(spv_label)s,
                    %(spv_evidence)s, %(content_hash)s, %(raw_payload)s, %(now)s, %(now)s)""", params)
            return "inserted"
        if existing[0]["content_hash"] == rec.content_hash:
            # Same data seen again: only note that we saw it. Nothing is rewritten.
            self.db.execute(
                f"UPDATE {self.records} SET last_seen_at = %(now)s, run_id = %(run_id)s "
                "WHERE record_id = %(record_id)s", params)
            return "unchanged"
        # Content really changed: latest version wins, first_seen_at is preserved.
        self.db.execute(f"""
            UPDATE {self.records} SET
                source=%(source)s, source_url=%(source_url)s, source_date=%(source_date)s,
                retrieved_at=%(retrieved_at)s, run_id=%(run_id)s, company_name=%(company_name)s,
                company_name_norm=%(company_name_norm)s, legal_form=%(legal_form)s,
                formation_date=%(formation_date)s, share_capital_eur=%(share_capital_eur)s,
                activity_text=%(activity_text)s, activity_terms=%(activity_terms)s,
                spv_score=%(spv_score)s, spv_label=%(spv_label)s, spv_evidence=%(spv_evidence)s,
                content_hash=%(content_hash)s, raw_payload=%(raw_payload)s, last_seen_at=%(now)s
            WHERE record_id=%(record_id)s""", params)
        return "updated"

    def save_reject(self, run_id: str, source: str, reason: str, detail: str, raw: dict) -> None:
        payload = json.dumps(raw, ensure_ascii=False, sort_keys=True)
        # Deterministic ID: re-running the same bad data does not pile up duplicates.
        reject_id = hashlib.sha256(f"{source}|{reason}|{payload}".encode()).hexdigest()[:24]
        if self.db.query(f"SELECT 1 AS x FROM {self.rejects} WHERE reject_id = %(id)s", {"id": reject_id}):
            return
        self.db.execute(
            f"INSERT INTO {self.rejects} (reject_id, run_id, source, reason, detail, raw_payload, rejected_at) "
            "VALUES (%(id)s, %(run_id)s, %(source)s, %(reason)s, %(detail)s, %(payload)s, %(at)s)",
            {"id": reject_id, "run_id": run_id, "source": source, "reason": reason, "detail": detail,
             "payload": payload, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})

    def set_crosscheck(self, record_id: str, status: str, evidence: list[str]) -> None:
        self.db.execute(
            f"UPDATE {self.records} SET crosscheck_status=%(s)s, crosscheck_evidence=%(e)s "
            "WHERE record_id=%(id)s",
            {"s": status, "e": json.dumps(evidence, ensure_ascii=False), "id": record_id})

    def commit(self) -> None:
        self.db.commit()
