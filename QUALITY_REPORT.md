# Quality and error report

Run on the shipped synthetic fixtures (19 input lines). Figures describe pipeline behaviour on test data,
**not** real register coverage.

## Coverage

| Measure | Result |
|---|---|
| Input lines | 19 |
| Staged (accepted) | 9 |
| Rejected | 10 (each with a reason code and raw payload) |
| Accounting: staged + rejected = input | 19 = 19 (nothing lost) |
| Second run | 0 inserted, 9 unchanged, rejects not duplicated |
| Same result on SQLite and on real Postgres | yes |

## Rejected data

| Reason | Count | Why it was rejected |
|---|---|---|
| `duplicate_in_batch` | 1 | identical record seen twice; first kept |
| `conflicting_duplicate` | 1 | same register ID, different capital; first kept, conflict recorded |
| `missing_register_number` | 1 | no HRA/HRB number, so no stable ID is possible |
| `bad_event_date` | 1 | `2026-13-45` is not a date |
| `not_formation_event` | 1 | event was a change (*Änderung*), not a formation |
| `malformed_json` | 1 | truncated line in the input file |
| `unsupported_register_type` | 1 | `VR` (association) register |
| `future_event_date` | 1 | formation date in the future |
| `missing_source_date` | 1 | no publication date, so no source evidence |
| `bad_capital` | 1 | capital was not a number |

## Edge cases handled (all covered by tests)

* German date and number formats, lowercase register numbers, leading zeros, Berlin-style `B` suffix, courts without the `AG` prefix.
* Missing purpose text and missing capital are accepted (score simply has fewer signals).
* Two companies with the **same name** in different courts stay separate records.
* Re-running the same file changes nothing; a changed record is updated and keeps `first_seen_at`.

## SPV hypotheses and cross-check

| SPV label | Records |
|---|---|
| likely_spv_hypothesis | 6 |
| possible_spv_hypothesis | 1 |
| no_spv_signal | 2 |

| Cross-check status | Records |
|---|---|
| confirmed_by_register_id | 2 |
| name_candidate_only | 2 |
| no_reference_match | 5 |

The two `name_candidate_only` rows share a name with a reference entry but not its register ID, so they are not confirmed.
One reference row without a register number was skipped.

## Evidence for acceptance

| Criterion | Evidence |
|---|---|
| Stable IDs, source dates, evidence | `record_id` = court+type+number; `source`, `source_date`, `retrieved_at`, `raw_payload`, `spv_evidence` on every row (validation query 3 and 4 return 0 problems) |
| Name match never definitive | `crosscheck.py`; test `test_name_candidate_evidence_says_not_proof`; validation query 5 returns 0 |
| Deterministic / auditable | no clock use inside normalization (`now` injected); rules listed with weights; same input gives same hashes (tested) |
| Authorised sources only | portal automation deliberately absent; rate limiter and disabled stub tested |
| Staging only | loader refuses other schemas (tested) |

## Known gaps

* No real portal parser, so coverage of live register data is zero by design (see README, "Data provenance").
* No mapping for real OffeneRegister or GLEIF dumps, only the documented JSONL shape.
* SPV rules are keyword heuristics and will miss SPVs with neutral names or purposes, and flag some non-SPVs.
* Staging table design is mine and should be aligned with any existing IRIS definition.
