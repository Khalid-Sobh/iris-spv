# IRIS-CORP-SPV: Commercial Register SPV Formation Radar

Ingests commercial-register formation entries (German Handelsregister), flags **hypotheses** about
new project SPVs, and loads everything into `iris_staging.corporate_distress_records`.
Small on purpose: one CLI, plain SQL, no orchestrator.

## Quick start

```bash
# Local (SQLite, no services needed)
pip install -r requirements-dev.txt
make test          # 46 tests
make run           # ingest fixtures -> cross-check -> quality report

# Docker (Postgres 17 + app)
make docker-up     # copies .env.example to .env, builds, runs the demo
make docker-test   # runs the test suite inside the image
```

Commands (`python -m iris_spv ...`):

| Command | What it does |
|---|---|
| `ingest --source fixture` | load the synthetic sample (default, reproducible) |
| `ingest --source export --path file.jsonl` | load records you exported from the public portal |
| `ingest --source portal` | refuses by design, see "Data provenance" |
| `crosscheck --reference file.jsonl` | compare staged records with a reference source |
| `report` | print the quality summary |

Config: `config.example.yaml` (optional), `DATABASE_URL` env var overrides it. No secrets in the repo.

## Data provenance

* **Primary source:** the German commercial register (Handelsregister), i.e. announcements of new entries (*Neueintragung*).
* **No official API exists.** The public portal caps automated retrieval at 60 queries/hour and forbids bulk
  automation, so this project does **not** scrape it. `--source portal` is a disabled stub (rate limiter wired in,
  no scraper). Records are brought in through `--source export` (hand-exported, within the portal's limits)
  or any authorised channel, as JSONL.
* **Fixtures are synthetic.** `fixtures/handelsregister_sample.jsonl` uses invented companies and register
  numbers (`example.invalid` URLs) shaped like register announcements. They exist to make runs reproducible
  and to exercise every edge case. They say nothing about real companies.
* **Reference data** (`fixtures/reference_sample.jsonl`) stands in for open datasets (e.g. OffeneRegister, GLEIF)
  used only for validation. The pipeline reads a simple JSONL shape; mapping a real dump to it is not included.

## How it works

```
source (JSONL) -> normalize -> score SPV hypothesis -> dedupe -> upsert into iris_staging
                      |                                              \-> rejects table (reason codes)
                      \-> RecordRejected(reason)  --------------------/
crosscheck: staged rows vs reference file -> confirmed_by_register_id | name_candidate_only | no_reference_match
```

| File | Role |
|---|---|
| `sources/` | adapters: a `name` and `fetch()` yielding raw dicts |
| `normalize.py` | name, court, HRA/HRB, dates, capital, event -> clean record or reject reason |
| `signals.py` | transparent SPV rules, each with evidence |
| `load.py` | Postgres/SQLite wrapper, idempotent upsert, rejects, staging-only guard |
| `pipeline.py`, `crosscheck.py`, `report.py`, `cli.py` | orchestration (plain functions) |

## Schema mapping

| Source field | Column | Normalization |
|---|---|---|
| `court` | `register_court` | `AG München` / `München` -> `Amtsgericht München` |
| `register` | `register_type`, `register_number`, `register_suffix` | `hrb 0042001` -> `HRB`, `42001`; Berlin-style `B` suffix kept |
| court + type + number | `record_id` | **stable ID**, never the name |
| `name` | `company_name`, `company_name_norm`, `legal_form` | legal form split off; folded for candidate matching only |
| `event` | `formation_event` | only formations accepted (`FORMATION`) |
| `event_date` | `formation_date` | ISO or `dd.mm.yyyy` -> ISO date; future dates rejected |
| `published` | `source_date` | publication date at the source (required) |
| `capital` | `share_capital_eur` | `25.000,00 EUR` -> `25000.0` |
| `object` | `activity_text`, `activity_terms` | purpose text; matched terms as JSON |
| whole record | `raw_payload`, `content_hash` | original kept; hash detects real changes |
| (ours) | `source`, `source_url`, `retrieved_at`, `run_id`, `first_seen_at`, `last_seen_at` | provenance |
| (ours) | `spv_score`, `spv_label`, `spv_evidence` | hypothesis + the rules that fired |
| (ours) | `crosscheck_status`, `crosscheck_evidence` | validation outcome |

Rejected input goes to `iris_staging.corporate_distress_rejects` with a reason code and the raw payload.

## SPV hypothesis rules (`signals.py`)

Name has a project term (+0.25) · legal form `GmbH & Co. KG` (+0.20) or `UG` (+0.10) · purpose names an
activity **and** a project asset (+0.35) · share capital ≤ 25,000 EUR (+0.10).
Score ≥ 0.6 `likely_spv_hypothesis`, ≥ 0.35 `possible_spv_hypothesis`, else `no_spv_signal`.
These are heuristics: a high score means "worth a human look", never "is an SPV".

## Safety

* Writes only to `iris_staging`. The loader raises on any other schema (tested). In a shared Postgres,
  also use a role that only has privileges on `iris_staging`.
* A **name match is never ownership evidence.** Same name + different register ID -> `name_candidate_only`
  with an explicit "NOT evidence of identity" note.
* Re-runs are idempotent: unchanged rows only get `last_seen_at`; changed rows are updated and `first_seen_at` is kept.

## Assumptions and limitations

* Input shape is the simple JSONL documented above. There is no real portal parser.
* On a content change the latest version wins (no version history table).
* Only HRA/HRB entries are accepted; associations/co-operatives (VR, GnR, ...) are rejected on purpose.
* Court names are unified by prefix only, there is no list of official court names.
* The staging table is my own design: I could not find an existing `corporate_distress_records`
  definition in the base repo's top-level files (its `alembic/` folder was not inspected). If a migration
  defines it, align `iris_spv/schema.sql` with it.
* Validated with SQLite (tests) and a real Postgres server. The Dockerfile and compose file were written
  but not built in the authoring environment, so run `make docker-up` once before relying on them.

## Validation query

`sql/validation.sql` has seven checks (duplicates, untraceable rows, evidence, name-match rule, reject audit).
Results on the fixtures are in `QUALITY_REPORT.md`.
