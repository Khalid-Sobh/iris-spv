"""si-to-jsonl: XML -> clean JSONL, and loading that JSONL gives the same result as loading the XML."""
import json

from conftest import FIXTURES
from iris_spv.cli import main
from iris_spv.load import Db, Loader
from iris_spv.logging_setup import get_logger
from iris_spv.pipeline import run_ingest
from iris_spv.sources.file_source import FileSource
from iris_spv.sources.si_xml import SiXmlSource
from conftest import NOW
from datetime import datetime, timezone

SI_DIR = FIXTURES / "si_sample"
DAY = datetime(2026, 10, 28, tzinfo=timezone.utc)


def test_jsonl_is_written_and_has_no_personal_data(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out.jsonl"
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    main(["si-to-jsonl", "--path", str(SI_DIR), "--out", str(out)])
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5 and all(isinstance(json.loads(l), dict) for l in lines)
    text = out.read_text(encoding="utf-8")
    assert "Musterfrau" not in text and "Hans" not in text


def test_loading_the_jsonl_equals_loading_the_xml(tmp_path):
    out = tmp_path / "out.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for raw in SiXmlSource(str(SI_DIR)).fetch():
            f.write(json.dumps(raw, ensure_ascii=False) + "\n")

    def load(source):
        db = Db("sqlite:///:memory:"); ld = Loader(db); ld.init_schema()
        stats = run_ingest(source, ld, "r", get_logger("t", "r"), now=DAY)
        rows = db.query(f"SELECT record_id, spv_score, formation_date, share_capital_eur FROM {ld.records} ORDER BY record_id")
        return stats.as_dict()["inserted"], dict(stats.rejected), rows

    assert load(SiXmlSource(str(SI_DIR))) == load(FileSource(str(out), "handelsregister_si_export"))
