"""Unit tests for field parsing: valid, messy and malformed inputs."""
import pytest

from conftest import NOW
from iris_spv.models import RecordRejected
from iris_spv.normalize import (identity_fields, normalize, normalize_court, parse_capital,
                                parse_date, parse_register, split_legal_form)


def good_raw(**overrides):
    raw = {"name": "Solarpark Test GmbH", "court": "AG Hamburg", "register": "HRB 1234",
           "event": "Neueintragung", "event_date": "2026-09-01", "published": "2026-09-03",
           "object": "Betrieb eines Solarparks.", "capital": "25.000,00 EUR"}
    raw.update(overrides)
    return raw


def test_court_variants_are_unified():
    assert normalize_court("AG Hamburg") == "Amtsgericht Hamburg"
    assert normalize_court("amtsgericht  Hamburg") == "Amtsgericht Hamburg"
    assert normalize_court("Hamburg") == "Amtsgericht Hamburg"


@pytest.mark.parametrize("raw, expected", [
    ("HRB 12345", ("HRB", "12345", "")),
    ("hrb 0042001", ("HRB", "42001", "")),          # case + leading zeros
    ("HRB 270011 B", ("HRB", "270011", "B")),        # Berlin-style suffix
    ("HRA123", ("HRA", "123", "")),                  # no space
])
def test_register_parsing(raw, expected):
    assert parse_register(raw) == expected


@pytest.mark.parametrize("raw, reason", [
    ("", "missing_register_number"), (None, "missing_register_number"),
    ("12345", "bad_register_number"), ("HRB", "bad_register_number"),
    ("VR 4411", "unsupported_register_type"),
])
def test_register_rejections(raw, reason):
    with pytest.raises(RecordRejected) as e:
        parse_register(raw)
    assert e.value.reason == reason


def test_legal_form_longest_match_wins():
    assert split_legal_form("Foo GmbH & Co. KG") == ("Foo", "GmbH & Co. KG")
    assert split_legal_form("Foo GmbH & Co.KG") == ("Foo", "GmbH & Co. KG")
    assert split_legal_form("Foo GmbH") == ("Foo", "GmbH")
    assert split_legal_form("Foo") == ("Foo", "")


def test_dates_iso_and_german():
    assert parse_date("2026-09-14", "x").isoformat() == "2026-09-14"
    assert parse_date("14.09.2026", "x").isoformat() == "2026-09-14"


@pytest.mark.parametrize("raw, reason", [("", "missing_d"), ("2026-13-45", "bad_d"), ("yesterday", "bad_d")])
def test_date_rejections(raw, reason):
    with pytest.raises(RecordRejected) as e:
        parse_date(raw, "d")
    assert e.value.reason == reason


@pytest.mark.parametrize("raw, expected", [
    ("25.000,00 EUR", 25000.0), ("1,00 EUR", 1.0), ("25000", 25000.0), ("", None), (None, None),
])
def test_capital(raw, expected):
    assert parse_capital(raw) == expected


@pytest.mark.parametrize("raw", ["viel Geld", "-5,00 EUR"])
def test_capital_rejections(raw):
    with pytest.raises(RecordRejected) as e:
        parse_capital(raw)
    assert e.value.reason == "bad_capital"


def test_stable_id_ignores_name_and_formatting():
    a = identity_fields({"name": "Alpha GmbH", "court": "AG München", "register": "HRB 0042001"})
    b = identity_fields({"name": "Totally Different Name", "court": "Amtsgericht Muenchen", "register": "hrb 42001"})
    assert a.record_id == b.record_id          # same register tuple -> same ID, whatever the name


def test_same_name_different_register_gives_different_id():
    a = identity_fields({"name": "Same Name GmbH", "court": "AG Hamburg", "register": "HRB 1"})
    b = identity_fields({"name": "Same Name GmbH", "court": "AG Lübeck", "register": "HRB 1"})
    assert a.record_id != b.record_id


def test_full_normalize_happy_path():
    rec = normalize(good_raw(), "fixture", "r1", NOW)
    assert rec.formation_event == "FORMATION"
    assert rec.formation_date == "2026-09-01" and rec.source_date == "2026-09-03"
    assert rec.share_capital_eur == 25000.0
    assert rec.retrieved_at.startswith("2026-10-01")
    assert '"Solarpark Test GmbH"' in rec.raw_payload     # original kept


def test_missing_event_date_is_staged_as_none():
    rec = normalize(good_raw(event_date=""), "fixture", "r1", NOW)
    assert rec.formation_date is None
    assert rec.content_hash == normalize(good_raw(event_date=""), "fixture", "r2", NOW).content_hash


def test_present_but_malformed_event_date_is_still_rejected():
    with pytest.raises(RecordRejected) as e:
        normalize(good_raw(event_date="2026-13-45"), "fixture", "r1", NOW)
    assert e.value.reason == "bad_event_date"


def test_optional_date_returns_none_but_required_date_rejects():
    assert parse_date("", "d", required=False) is None
    with pytest.raises(RecordRejected):
        parse_date("", "d")


def test_gmbh_co_kg_with_words_between_is_recognised():
    assert split_legal_form("Dr. Foo GmbH & Co. Solarpark KG") == ("Dr. Foo Solarpark", "GmbH & Co. KG")
    assert split_legal_form("Foo GmbH & Co. KG") == ("Foo", "GmbH & Co. KG")      # unchanged
    assert split_legal_form("Foo KG") == ("Foo", "KG")                            # a plain KG stays a KG


def test_legal_form_variant_gives_same_identity_fields_as_plain_form():
    a = identity_fields({"name": "Dr. Foo GmbH & Co. Solarpark KG", "court": "AG Aachen", "register": "HRA 1"})
    assert a.legal_form == "GmbH & Co. KG" and a.company_name_norm == "dr foo solarpark"


def test_non_formation_event_rejected():
    with pytest.raises(RecordRejected) as e:
        normalize(good_raw(event="Änderung"), "fixture", "r1", NOW)
    assert e.value.reason == "not_formation_event"


def test_future_event_date_rejected():
    with pytest.raises(RecordRejected) as e:
        normalize(good_raw(event_date="2030-01-01"), "fixture", "r1", NOW)
    assert e.value.reason == "future_event_date"


def test_missing_source_date_rejected():
    with pytest.raises(RecordRejected) as e:
        normalize(good_raw(published=""), "fixture", "r1", NOW)
    assert e.value.reason == "missing_source_date"


def test_malformed_json_marker_rejected():
    with pytest.raises(RecordRejected) as e:
        normalize({"_malformed_line": 12}, "fixture", "r1", NOW)
    assert e.value.reason == "malformed_json"


def test_hash_is_stable_and_detects_change():
    h1 = normalize(good_raw(), "fixture", "run-A", NOW).content_hash
    h2 = normalize(good_raw(), "fixture", "run-B", NOW).content_hash   # other run, same data
    h3 = normalize(good_raw(capital="50.000,00 EUR"), "fixture", "run-A", NOW).content_hash
    assert h1 == h2 and h1 != h3
