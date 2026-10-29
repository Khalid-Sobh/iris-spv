"""The `sql` inspection command: reads work, anything else is refused."""
import pytest

from iris_spv.cli import main


def run(monkeypatch, query):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    main(["sql", query])


def test_select_prints_a_table(monkeypatch, capsys):
    run(monkeypatch, "SELECT COUNT(*) AS n FROM iris_staging.corporate_distress_records")
    out = capsys.readouterr().out
    assert "n" in out and "0" in out and "(1 rows)" in out


@pytest.mark.parametrize("bad", [
    "DELETE FROM iris_staging.corporate_distress_records",
    "DROP TABLE iris_staging.corporate_distress_records",
    "SELECT 1; DELETE FROM iris_staging.corporate_distress_records",
])
def test_non_select_is_refused(monkeypatch, bad):
    with pytest.raises(SystemExit):
        run(monkeypatch, bad)
