"""SPV scoring: every point must be explained by evidence."""
from conftest import NOW
from iris_spv.normalize import normalize
from iris_spv.signals import score_spv


def scored(**overrides):
    raw = {"name": "Bäckerei Kornblume GmbH", "court": "AG Düsseldorf", "register": "HRB 98765",
           "event": "Neueintragung", "event_date": "2026-09-08", "published": "2026-09-11",
           "object": "Herstellung und Verkauf von Backwaren.", "capital": "50.000,00 EUR"}
    raw.update(overrides)
    return score_spv(normalize(raw, "fixture", "r", NOW))


def test_ordinary_company_has_no_signal():
    rec = scored()
    assert rec.spv_score == 0 and rec.spv_label == "no_spv_signal" and rec.spv_evidence == []


def test_project_company_scores_high_with_evidence():
    rec = scored(name="Solarpark Foo GmbH & Co. KG", register="HRA 5",
                 object="Planung, Errichtung und Betrieb eines Solarparks.", capital="1.000,00 EUR")
    assert rec.spv_score == 0.9 and rec.spv_label == "likely_spv_hypothesis"
    assert len(rec.spv_evidence) == 4                      # all four rules fired, all explained
    assert "solar" in rec.activity_terms


def test_label_always_says_hypothesis_never_fact():
    rec = scored(name="Windpark Foo GmbH", object="Betrieb von Windenergieanlagen.", capital="25.000,00 EUR")
    assert rec.spv_label.endswith("_hypothesis")


def test_missing_purpose_and_capital_is_handled():
    rec = scored(name="Verwaltung Elbe GmbH", object="", capital="")
    assert rec.spv_score == 0


def test_scoring_is_deterministic():
    assert scored(name="Solarpark X GmbH").spv_evidence == scored(name="Solarpark X GmbH").spv_evidence
