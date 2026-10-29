"""Reads 'Strukturierter Registerinhalt' (SI) XML files exported from the register portal.

The files follow the XJustiz register format. We extract ONLY company-level facts
(name, court, register number, founding date, purpose, capital) and never read
the <natuerlichePerson> parts (managing directors: names, birth dates, addresses).
Personal data therefore never reaches the database or the raw_payload column.

Register number search order (first hit wins), ALWAYS for the company itself:
  1) the company's own <registereintragung><registernummer>
  2) the structured case number <aktenzeichen.strukturiert> (register + laufendeNummer)
  3) the free-text case number <aktenzeichen.freitext>
A KG's file also lists its general partner (a separate GmbH with its OWN register
number). Taking "the first registernummer in the file" would pick that wrong number,
so the number is only ever read from the company's own participant.

Capital: companies (GmbH/UG) have a share capital. A KG has none; we then use the
sum of the limited partners' liability contributions (Hafteinlagen) and label it
(capital_basis). Partnerships also state no business purpose in the register.

What the SI file does NOT contain: the announcement date and the date of the
first register entry. So we use (and label in the payload):
  event_date <- founding date (gruendungsdatum) or first articles date (ersteSatzung)
  published  <- extract date (abrufdatum)
"""
import re
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator

COMPANY_ROLE = "287"          # role code of the legal entity in XJustiz


def _local(tag: str) -> str:
    """'{http://www.xjustiz.de}code' -> 'code' (ignore namespaces)."""
    return tag.rsplit("}", 1)[-1]


def _iter(el, name):
    return (e for e in el.iter() if _local(e.tag) == name)


def _text(el, name) -> str:
    """Text of the first descendant called `name` ('' if absent)."""
    for e in _iter(el, name):
        return (e.text or "").strip()
    return ""


def _company_org(root):
    """The <organisation> of the participant with role 287 (None for sole traders)."""
    for b in _iter(root, "beteiligung"):
        codes = [(c.text or "").strip() for r in _iter(b, "rollenbezeichnung") for c in _iter(r, "code")]
        if COMPANY_ROLE in codes:
            return next(_iter(b, "organisation"), None)   # a natural person has no <organisation>
    return None


def _court_name(root) -> str:
    for org in _iter(root, "organisation"):
        name = _text(org, "bezeichnung.aktuell")
        if name.startswith("Amtsgericht"):
            return re.sub(r"\s*-\s*Registergericht\s*-?\s*$", "", name).strip()
    return ""


def _register(root, org) -> str:
    if org is not None:                                       # 1) the company's own entry
        reg = _text(org, "registernummer")
        if reg:
            return reg
    for ak in _iter(root, "aktenzeichen.strukturiert"):       # 2) structured case number
        return f"{_text(ak, 'code')} {_text(ak, 'laufendeNummer')}".strip()
    return _text(root, "aktenzeichen.freitext")               # 3) free-text case number


def _capital(root) -> tuple[str, str]:
    """(amount text, basis label). Share capital, else sum of Hafteinlagen, else unknown."""
    cap_el = next(_iter(root, "kapital"), None)
    if cap_el is not None and _text(cap_el, "zahl"):
        return f"{_text(cap_el, 'zahl')} {_text(cap_el, 'code')}".strip(), "kapital (share capital)"
    amounts = []
    for h in _iter(root, "hafteinlage"):
        number, currency = _text(h, "zahl"), _text(h, "code")
        if not number:
            continue
        if currency and currency != "EUR":
            return "", "hafteinlage not in EUR: not summed"
        try:
            amounts.append(Decimal(number))
        except InvalidOperation:
            return "", "hafteinlage unreadable: not summed"
    if amounts:
        return f"{sum(amounts)} EUR", "sum of Hafteinlagen (limited partners' liability contributions)"
    return "", ""


def parse_si_file(path: Path) -> dict:
    """One SI file -> one raw record in the same shape the JSONL sources use."""
    root = ET.parse(path).getroot()
    org = _company_org(root)

    # Founding date: layout A has gruendungsdatum, layout B only the first articles date.
    founding, basis = _text(root, "gruendungsdatum"), "gruendungsdatum"
    if not founding:
        first_articles = next(_iter(root, "ersteSatzung"), None)
        founding = _text(first_articles, "satzungsdatum") if first_articles is not None else ""
        basis = "ersteSatzung"

    # Purpose: the <gegenstand> directly under <basisdatenRegister> (not the court-file title).
    purpose = ""
    for basis_el in _iter(root, "basisdatenRegister"):
        for child in basis_el:
            if _local(child.tag) == "gegenstand":
                purpose = (child.text or "").strip()

    capital, capital_basis = _capital(root)

    return {
        "name": _text(org, "bezeichnung.aktuell") if org is not None else "",
        "court": _court_name(root),
        "register": _register(root, org),
        "event": "formation",                 # derived from the founding date, see module docstring
        "event_date": founding,
        "published": _text(root, "abrufdatum"),
        "object": purpose,
        "capital": capital,
        "source_url": "",
        # Provenance extras (kept in raw_payload):
        "euid": _text(org, "euid") if org is not None else "",
        "seat": _text(org, "ort") if org is not None else "",
        "event_basis": basis,
        "capital_basis": capital_basis,
        "published_basis": "abrufdatum (extract date; announcement date not in SI file)",
        "source_file": path.name,
    }


class SiXmlSource:
    """Yields one raw record per .xml file (a single file or a whole folder)."""

    def __init__(self, path: str, name: str = "handelsregister_si_export"):
        self.path = Path(path)
        self.name = name

    def fetch(self) -> Iterator[dict]:
        files = [self.path] if self.path.is_file() else sorted(self.path.glob("*.xml"))
        for f in files:
            try:
                yield parse_si_file(f)
            except ET.ParseError as e:
                # Broken file: flag it, normalize() rejects it, the run continues.
                yield {"_unreadable_file": f.name, "_error": str(e)[:120]}
