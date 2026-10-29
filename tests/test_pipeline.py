"""End-to-end ingest on the shipped fixtures (in-memory DB)."""
from conftest import NOW
from iris_spv.pipeline import run_ingest

EXPECTED_REJECTS = {
    "duplicate_in_batch": 1, "conflicting_duplicate": 1, "missing_register_number": 1,
    "bad_event_date": 1, "not_formation_event": 1, "malformed_json": 1,
    "unsupported_register_type": 1, "future_event_date": 1, "missing_source_date": 1, "bad_capital": 1,
}


def count(loader, table):
    return loader.db.query(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]


def test_ingest_counts_and_reject_reasons(loader, fixture_source, log):
    stats = run_ingest(fixture_source, loader, "run1", log, now=NOW)
    assert stats.fetched == 19 and stats.inserted == 9
    assert dict(stats.rejected) == EXPECTED_REJECTS
    # Nothing lost: every fetched line is either staged or in the rejects table.
    assert count(loader, loader.records) + count(loader, loader.rejects) == stats.fetched


def test_rerun_is_idempotent(loader, fixture_source, log):
    run_ingest(fixture_source, loader, "run1", log, now=NOW)
    again = run_ingest(fixture_source, loader, "run2", log, now=NOW)
    assert (again.inserted, again.updated, again.unchanged) == (0, 0, 9)
    assert count(loader, loader.records) == 9              # no duplicate rows
    assert count(loader, loader.rejects) == 10             # rejects not duplicated either


def test_changed_content_updates_row_and_keeps_first_seen(loader, tmp_path, fixture_source, log):
    run_ingest(fixture_source, loader, "run1", log, now=NOW)
    before = loader.db.query(f"SELECT first_seen_at FROM {loader.records} WHERE register_number='748812'")[0]
    changed = tmp_path / "changed.jsonl"
    changed.write_text('{"name": "Batteriespeicher Rheinau 1 GmbH", "court": "AG Mannheim", "register": "HRB 748812", '
                       '"event": "Neueintragung", "event_date": "2026-09-10", "published": "2026-09-12", '
                       '"object": "Errichtung und Betrieb von Batteriespeichern.", "capital": "50.000,00 EUR"}\n')
    from iris_spv.sources.file_source import FileSource
    stats = run_ingest(FileSource(str(changed), "fixture"), loader, "run2", log, now=NOW)
    assert stats.updated == 1
    row = loader.db.query(f"SELECT share_capital_eur, first_seen_at, run_id FROM {loader.records} "
                          "WHERE register_number='748812'")[0]
    assert row["share_capital_eur"] == 50000.0 and row["run_id"] == "run2"
    assert row["first_seen_at"] == before["first_seen_at"]


def test_same_name_different_court_stays_separate(loader, fixture_source, log):
    run_ingest(fixture_source, loader, "run1", log, now=NOW)
    rows = loader.db.query(f"SELECT record_id FROM {loader.records} WHERE company_name LIKE 'Solarpark Alsterwiese%'")
    assert len(rows) == 2                                   # Hamburg + Lübeck: a name is not an identity


def test_every_staged_row_has_source_dates_and_evidence_fields(loader, fixture_source, log):
    run_ingest(fixture_source, loader, "run1", log, now=NOW)
    bad = loader.db.query(f"SELECT COUNT(*) AS n FROM {loader.records} WHERE source IS NULL OR source_date IS NULL "
                          "OR retrieved_at IS NULL OR raw_payload IS NULL OR spv_evidence IS NULL")
    assert bad[0]["n"] == 0


def test_report_shows_unknown_formation_dates(loader, tmp_path, log):
    from iris_spv.report import build_report
    from iris_spv.sources.file_source import FileSource
    f = tmp_path / "x.jsonl"
    f.write_text('{"name": "Foo GmbH", "court": "AG Hamburg", "register": "HRB 1", "event": "Neueintragung", '
                 '"event_date": "", "published": "2026-09-12"}\n')
    run_ingest(FileSource(str(f), "fixture"), loader, "r", log, now=NOW)
    assert "formation date unknown: 1" in build_report(loader)
