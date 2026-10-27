"""Quality summary printed as Markdown (pipe it into a file if you like)."""
from iris_spv.load import Loader


def _table(rows: list[dict], headers: tuple[str, str]) -> str:
    if not rows:
        return "_none_\n"
    lines = [f"| {headers[0]} | {headers[1]} |", "|---|---|"]
    lines += [f"| {list(r.values())[0]} | {list(r.values())[1]} |" for r in rows]
    return "\n".join(lines) + "\n"


def build_report(loader: Loader) -> str:
    q = loader.db.query
    total = q(f"SELECT COUNT(*) AS n FROM {loader.records}")[0]["n"]
    labels = q(f"SELECT spv_label AS label, COUNT(*) AS n FROM {loader.records} "
               "GROUP BY spv_label ORDER BY n DESC, label")
    checks = q(f"SELECT COALESCE(crosscheck_status, 'not_run') AS status, COUNT(*) AS n "
               f"FROM {loader.records} GROUP BY 1 ORDER BY n DESC, status")
    rejects = q(f"SELECT reason, COUNT(*) AS n FROM {loader.rejects} GROUP BY reason ORDER BY n DESC, reason")
    top = q(f"SELECT company_name, spv_score FROM {loader.records} ORDER BY spv_score DESC, record_id LIMIT 5")
    return (
        f"# Quality summary\n\nStaged records: **{total}**\n\n"
        f"## SPV hypotheses (hypotheses, not facts)\n{_table(labels, ('label', 'records'))}\n"
        f"## Cross-check status\n{_table(checks, ('status', 'records'))}\n"
        f"## Rejected records by reason\n{_table(rejects, ('reason', 'records'))}\n"
        f"## Top 5 by SPV score\n{_table(top, ('company', 'score'))}"
    )
