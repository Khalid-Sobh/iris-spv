"""Cross-check staged records against a reference source (e.g. an open-data dump).

Rules (the point of the exercise):
  * same register ID (court + type + number)  -> 'confirmed_by_register_id'
  * same NAME but different register ID       -> 'name_candidate_only'
    A name match is NEVER treated as proof of identity or ownership.
  * nothing                                   -> 'no_reference_match'
"""
from collections import defaultdict

from iris_spv.load import Loader
from iris_spv.models import RecordRejected
from iris_spv.normalize import identity_fields


def run_crosscheck(loader: Loader, reference_source, log) -> dict:
    # 1) Index the reference records by ID and by normalized name.
    by_id, by_name = {}, defaultdict(list)
    skipped = 0
    for raw in reference_source.fetch():
        try:
            ident = identity_fields(raw)
        except (RecordRejected, AttributeError):
            skipped += 1          # unusable reference row: skip, but count it
            continue
        by_id[ident.record_id] = raw.get("source_url", "")
        by_name[ident.company_name_norm].append(ident.record_id)

    # 2) Compare every staged record.
    counts = {"confirmed_by_register_id": 0, "name_candidate_only": 0, "no_reference_match": 0}
    staged = loader.db.query(f"SELECT record_id, company_name_norm FROM {loader.records}")
    for row in staged:
        rid = row["record_id"]
        if rid in by_id:
            status = "confirmed_by_register_id"
            evidence = [f"reference:{reference_source.name}", f"id:{rid}", f"url:{by_id[rid]}"]
        elif by_name.get(row["company_name_norm"]):
            status = "name_candidate_only"
            evidence = [f"reference:{reference_source.name}",
                        "same name, different register ID: NOT evidence of identity",
                        *[f"candidate_id:{c}" for c in by_name[row["company_name_norm"]]]]
        else:
            status, evidence = "no_reference_match", [f"reference:{reference_source.name}"]
        loader.set_crosscheck(rid, status, evidence)
        counts[status] += 1
        log.info("crosscheck", extra={"record_id": rid, "status": status})

    loader.commit()
    counts["reference_rows_skipped"] = skipped
    return counts
