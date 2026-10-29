"""Command-line entrypoint:  python -m iris_spv <command>

  ingest     fetch from a source, normalize, score, load into iris_staging
  crosscheck compare staged records with a reference file
  report     print a quality summary
  sql        run ONE read-only SELECT to inspect the database
  si-to-jsonl convert portal SI XML files into clean JSONL (no database needed)
"""
import argparse
import json
import re
import sys
import uuid

from iris_spv.config import load_config
from iris_spv.crosscheck import run_crosscheck
from iris_spv.load import Db, Loader
from iris_spv.logging_setup import get_logger, setup_logging
from iris_spv.pipeline import run_ingest
from iris_spv.report import build_report
from iris_spv.sources import get_source
from iris_spv.sources.file_source import FileSource
from iris_spv.sources.si_xml import SiXmlSource


def _open(cfg) -> tuple[Db, Loader]:
    db = Db(cfg.database_url)
    loader = Loader(db, cfg.schema)    # raises if schema is not iris_staging
    loader.init_schema()               # CREATE ... IF NOT EXISTS: safe to repeat
    return db, loader


def cmd_ingest(args, cfg) -> None:
    run_id = uuid.uuid4().hex[:8]
    source = get_source(args.source, args.path, cfg.portal_max_requests_per_hour)
    log = get_logger(source.name, run_id)
    db, loader = _open(cfg)
    try:
        stats = run_ingest(source, loader, run_id, log)
    finally:
        db.close()
    print(json.dumps(stats.as_dict(), indent=2))


def cmd_crosscheck(args, cfg) -> None:
    run_id = uuid.uuid4().hex[:8]
    reference = FileSource(args.reference, name="reference")
    log = get_logger(reference.name, run_id)
    db, loader = _open(cfg)
    try:
        print(json.dumps(run_crosscheck(loader, reference, log), indent=2))
    finally:
        db.close()


def cmd_report(args, cfg) -> None:
    db, loader = _open(cfg)
    try:
        print(build_report(loader))
    finally:
        db.close()


def cmd_sql(args, cfg) -> None:
    """Inspection helper: one SELECT/WITH statement, printed as a table. Never writes."""
    q = args.query.strip().rstrip(";")
    if not re.match(r"(?is)^(select|with)\b", q) or ";" in q:
        raise ValueError("only a single SELECT/WITH statement is allowed")
    db, _ = _open(cfg)
    try:
        rows = db.query(q)
    finally:
        db.close()
    if not rows:
        print("(0 rows)")
        return
    cols = list(rows[0])
    cell = lambda v: ("" if v is None else str(v))[:args.width]   # long values are cut for readability
    table = [[cell(r[c]) for c in cols] for r in rows]
    widths = [max(len(c), *(len(row[i]) for row in table)) for i, c in enumerate(cols)]
    line = lambda vals: " | ".join(v.ljust(w) for v, w in zip(vals, widths))
    print(line(cols)); print("-+-".join("-" * w for w in widths))
    for row in table:
        print(line(row))
    print(f"({len(rows)} rows)")


def cmd_si_to_jsonl(args, cfg) -> None:
    """XML -> JSONL (one clean record per line, company facts only). Load it later with --source export."""
    written = 0
    with open(args.out, "w", encoding="utf-8") as f:
        for raw in SiXmlSource(args.path).fetch():
            f.write(json.dumps(raw, ensure_ascii=False, sort_keys=True) + "\n")
            written += 1
    print(json.dumps({"written": written, "out": args.out}))


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="iris_spv", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", help="path to config.yaml (optional)")
    sub = p.add_subparsers(dest="command", required=True)

    ing = sub.add_parser("ingest", help="load records into iris_staging")
    ing.add_argument("--source", choices=["fixture", "export", "si", "portal"], default="fixture")
    ing.add_argument("--path", help="JSONL file (--source export) or XML file/folder (--source si)")
    ing.set_defaults(func=cmd_ingest)

    cc = sub.add_parser("crosscheck", help="compare staged records with a reference file")
    cc.add_argument("--reference", required=True, help="JSONL reference file")
    cc.set_defaults(func=cmd_crosscheck)

    rp = sub.add_parser("report", help="print a quality summary")
    rp.set_defaults(func=cmd_report)

    sq = sub.add_parser("sql", help="run one read-only SELECT against the database")
    sq.add_argument("query", help='e.g. "SELECT COUNT(*) AS n FROM iris_staging.corporate_distress_records"')
    sq.add_argument("--width", type=int, default=60, help="cut long values to this many characters")
    sq.set_defaults(func=cmd_sql)

    cv = sub.add_parser("si-to-jsonl", help="convert SI XML files to clean JSONL")
    cv.add_argument("--path", required=True, help="XML file or folder")
    cv.add_argument("--out", required=True, help="JSONL file to write")
    cv.set_defaults(func=cmd_si_to_jsonl)

    args = p.parse_args(argv)
    cfg = load_config(args.config)
    setup_logging(cfg.log_level)
    try:
        args.func(args, cfg)
    except Exception as e:             # one clean line instead of a traceback for expected failures
        get_logger("cli", "-").error("command_failed", extra={"error": f"{type(e).__name__}: {e}"})
        sys.exit(1)


if __name__ == "__main__":
    main()
