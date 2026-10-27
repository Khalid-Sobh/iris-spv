"""Command-line entrypoint:  python -m iris_spv <command>

  ingest     fetch from a source, normalize, score, load into iris_staging
  crosscheck compare staged records with a reference file
  report     print a quality summary
"""
import argparse
import json
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


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="iris_spv", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", help="path to config.yaml (optional)")
    sub = p.add_subparsers(dest="command", required=True)

    ing = sub.add_parser("ingest", help="load records into iris_staging")
    ing.add_argument("--source", choices=["fixture", "export", "portal"], default="fixture")
    ing.add_argument("--path", help="JSONL file (needed for --source export)")
    ing.set_defaults(func=cmd_ingest)

    cc = sub.add_parser("crosscheck", help="compare staged records with a reference file")
    cc.add_argument("--reference", required=True, help="JSONL reference file")
    cc.set_defaults(func=cmd_crosscheck)

    rp = sub.add_parser("report", help="print a quality summary")
    rp.set_defaults(func=cmd_report)

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
