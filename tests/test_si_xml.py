"""SI XML reader: both layouts, no personal data, bad files rejected."""
import json
from datetime import datetime, timezone

from conftest import FIXTURES
from iris_spv.pipeline import run_ingest
from iris_spv.sources.si_xml import SiXmlSource, parse_si_file

SI_DIR = FIXTURES / "si_sample"
EXTRACT_DAY = datetime(2026, 10, 28, tzinfo=timezone.utc)   # same day as the fixture extracts


def test_layout_a_register_in_registereintragung():
    raw = parse_si_file(SI_DIR / "a_layout_solarpark.xml")
    assert raw["name"] == "Solarpark Testwiese GmbH & Co. KG"
    assert raw["court"] == "Amtsgericht Bremen"
    assert raw["register"] == "HRA 99001 HB"
    assert raw["event_date"] == "2026-10-20" and raw["event_basis"] == "gruendungsdatum"
    assert raw["published"] == "2026-10-28"                     # extract date, labelled as such
    assert raw["capital"] == "1000 EUR"
    assert raw["object"].startswith("Planung, Errichtung")      # purpose, not the court-file title
    assert raw["euid"] == "DEH1101.HRA99001HB"


def test_layout_b_structured_case_number_and_court_cleanup():
    raw = parse_si_file(SI_DIR / "b_layout_windpark.xml")
    assert raw["register"] == "HRB 990002"
    assert raw["court"] == "Amtsgericht Beispielstadt"          # '- Registergericht -' removed
    assert raw["event_date"] == "2026-09-01" and raw["event_basis"] == "ersteSatzung"
    assert raw["capital"] == "25000.00 EUR"


def test_kg_uses_its_own_register_number_not_the_general_partners():
    """Regression: the file also lists the general partner's own number (HRB 99004)."""
    raw = parse_si_file(SI_DIR / "e_kg_with_general_partner.xml")
    assert raw["register"] == "HRA 99003"            # the KG's number, from the structured case number
    assert "99004" not in json.dumps(raw)            # the partner's number must not leak in
    assert raw["court"] == "Amtsgericht Musterstadt"


def test_kg_capital_is_sum_of_hafteinlagen_and_labelled():
    raw = parse_si_file(SI_DIR / "e_kg_with_general_partner.xml")
    assert raw["capital"] == "1000.00 EUR"
    assert "Hafteinlagen" in raw["capital_basis"]
    assert raw["object"] == ""                        # partnerships state no purpose in the register


def test_company_keeps_share_capital_basis():
    assert "share capital" in parse_si_file(SI_DIR / "a_layout_solarpark.xml")["capital_basis"]


def test_missing_founding_date_is_staged_as_unknown_not_guessed(tmp_path, loader, log):
    text = (SI_DIR / "e_kg_with_general_partner.xml").read_text()
    text = text.replace("<tns:gruendungsdatum>2026-10-10</tns:gruendungsdatum>", "")
    (tmp_path / "no_date.xml").write_text(text)
    stats = run_ingest(SiXmlSource(str(tmp_path)), loader, "r", log, now=EXTRACT_DAY)
    assert stats.inserted == 1 and not stats.rejected                      # kept, not lost
    row = loader.db.query(f"SELECT formation_date, register_number FROM {loader.records}")[0]
    assert row["formation_date"] is None and row["register_number"] == "99003"   # empty, never invented


def test_no_personal_data_in_output():
    dumped = json.dumps([r for r in SiXmlSource(str(SI_DIR)).fetch()], ensure_ascii=False)
    for secret in ("Erika", "Musterfrau", "1980-01-01", "Mustermann", "Hans", "Beispiel,"):
        assert secret not in dumped


def test_end_to_end_ingest_from_xml_folder(loader, log):
    stats = run_ingest(SiXmlSource(str(SI_DIR)), loader, "run1", log, now=EXTRACT_DAY)
    assert stats.fetched == 5 and stats.inserted == 3
    assert dict(stats.rejected) == {"missing_name": 1, "unreadable_source_file": 1}   # sole trader, broken XML
    rows = loader.db.query(f"SELECT company_name, spv_label, source FROM {loader.records}")
    assert {r["source"] for r in rows} == {"handelsregister_si_export"}
    labels = {r["company_name"]: r["spv_label"] for r in rows}
    assert labels["Solarpark Testwiese GmbH & Co. KG"] == "likely_spv_hypothesis"
    assert labels["Windpark Beispielhain Projekt GmbH"] == "likely_spv_hypothesis"
    assert labels["Batteriespeicher Musterdorf GmbH & Co. KG"] == "possible_spv_hypothesis"   # no purpose in a KG
    # personal data never reaches the payload column either
    payloads = " ".join(r["raw_payload"] for r in loader.db.query(f"SELECT raw_payload FROM {loader.records}"))
    assert "Musterfrau" not in payloads and "Hans" not in payloads


def test_single_file_path_works():
    records = list(SiXmlSource(str(SI_DIR / "a_layout_solarpark.xml")).fetch())
    assert len(records) == 1
