"""A name match must never count as confirmation."""
from conftest import NOW
from iris_spv.crosscheck import run_crosscheck
from iris_spv.pipeline import run_ingest


def status_of(loader, court_like, number):
    return loader.db.query(f"SELECT crosscheck_status AS s FROM {loader.records} "
                           f"WHERE register_court LIKE '%{court_like}%' AND register_number='{number}'")[0]["s"]


def test_crosscheck_statuses(loader, fixture_source, reference_source, log):
    run_ingest(fixture_source, loader, "run1", log, now=NOW)
    counts = run_crosscheck(loader, reference_source, log)
    assert counts == {"confirmed_by_register_id": 2, "name_candidate_only": 2,
                      "no_reference_match": 5, "reference_rows_skipped": 1}
    assert status_of(loader, "Hamburg", "123401") == "confirmed_by_register_id"   # same ID
    assert status_of(loader, "Lübeck", "55102") == "name_candidate_only"          # same name only
    assert status_of(loader, "Oldenburg", "215578") == "name_candidate_only"      # name twin, other court


def test_name_candidate_evidence_says_not_proof(loader, fixture_source, reference_source, log):
    run_ingest(fixture_source, loader, "run1", log, now=NOW)
    run_crosscheck(loader, reference_source, log)
    ev = loader.db.query(f"SELECT crosscheck_evidence AS e FROM {loader.records} WHERE register_number='55102'")[0]["e"]
    assert "NOT evidence of identity" in ev
