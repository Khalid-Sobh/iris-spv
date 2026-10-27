"""SPV signals: simple, transparent rules -> a score plus the evidence behind it.

IMPORTANT: the output is a HYPOTHESIS ("this looks like a project SPV"),
not a fact. Every point of score is traceable to a named rule in `evidence`.
"""
import re

from iris_spv.models import Record
from iris_spv.normalize import fold

# Words in the company NAME that hint at a single-project vehicle.
NAME_TERMS = ["solarpark", "windpark", "photovoltaik", "batteriespeicher",
              "speicher", "projekt", "objekt", "park"]

# Words in the stated PURPOSE (Gegenstand): an activity verb AND a project asset.
ACTIVITY_VERBS = ["errichtung", "betrieb", "planung", "erwerb", "entwicklung", "vermietung"]
ASSET_WORDS = ["solar", "photovoltaik", "wind", "batteriespeicher", "rechenzentrum",
               "grundstueck", "immobilie"]

LOW_CAPITAL_EUR = 25_000.0  # 25k = statutory minimum for a GmbH


def _found(words: list[str], text: str) -> list[str]:
    """Which of `words` occur in the (folded) text? Returned in list order."""
    return [w for w in words if w in text]


def score_spv(rec: Record) -> Record:
    """Fill rec.spv_score / spv_label / spv_evidence / activity_terms. Returns rec."""
    evidence: list[str] = []
    terms: list[str] = []
    score = 0.0

    # Rule 1: project-like word in the name (+0.25)
    name_hits = _found(NAME_TERMS, fold(rec.identity.company_name))
    if name_hits:
        score += 0.25
        terms += name_hits
        evidence.append(f"name_project_term(+0.25): {', '.join(name_hits)}")

    # Rule 2: legal form typical for project vehicles
    if rec.identity.legal_form == "GmbH & Co. KG":
        score += 0.20
        evidence.append("legal_form_gmbh_co_kg(+0.20)")
    elif rec.identity.legal_form.startswith("UG"):
        score += 0.10
        evidence.append("legal_form_ug(+0.10)")

    # Rule 3: purpose names an activity AND a project asset (+0.35)
    purpose = fold(rec.activity_text)
    verbs, assets = _found(ACTIVITY_VERBS, purpose), _found(ASSET_WORDS, purpose)
    if verbs and assets:
        score += 0.35
        terms += assets
        evidence.append(f"purpose_project_asset(+0.35): {verbs[0]} + {assets[0]}")

    # Rule 4: minimal share capital (+0.10)
    if rec.share_capital_eur is not None and rec.share_capital_eur <= LOW_CAPITAL_EUR:
        score += 0.10
        evidence.append(f"low_capital(+0.10): {rec.share_capital_eur:.0f} EUR")

    rec.spv_score = round(score, 2)
    rec.spv_evidence = evidence
    rec.activity_terms = sorted(set(terms))
    # Labels deliberately say "hypothesis".
    if rec.spv_score >= 0.6:
        rec.spv_label = "likely_spv_hypothesis"
    elif rec.spv_score >= 0.35:
        rec.spv_label = "possible_spv_hypothesis"
    else:
        rec.spv_label = "no_spv_signal"
    return rec
