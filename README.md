# IRIS-CORP-SPV: Commercial Register SPV Formation Radar

Ingests commercial-register formation entries (German Handelsregister), flags **hypotheses** about
new project SPVs, and loads everything into `iris_staging.corporate_distress_records`.
Small on purpose: one CLI, plain SQL, no orchestrator.

## Quick start

```bash
# Local (SQLite, no services needed)
pip install -r requirements-dev.txt
make test          # 72 tests
make run           # ingest fixtures -> cross-check -> quality report

# Docker (Postgres 17 + app)
make docker-up     # copies .env.example to .env, builds, runs the demo
make docker-test   # runs the test suite inside the image
```

Step-by-step guide with expected output: **`WALKTHROUGH.md`**.

Commands (`python -m iris_spv ...`):

| Command | What it does |
|---|---|
| `ingest --source fixture` | load the synthetic sample (default, reproducible) |
| `ingest --source export --path file.jsonl` | load records you exported from the public portal |
| `ingest --source si --path data/si` | load structured-content (SI) XML files you exported from the portal (file or folder) |
| `si-to-jsonl --path data/si --out data/records.jsonl` | convert SI XML to clean JSONL (company facts only); load it later with `--source export` |
| `ingest --source portal` | refuses by design, see "Data provenance" |
| `crosscheck --reference file.jsonl` | compare staged records with a reference source |
| `report` | print the quality summary |
| `sql "SELECT ..."` | read-only helper to inspect the database between steps |

Config: `config.example.yaml` (optional), `DATABASE_URL` env var overrides it. No secrets in the repo.

## Data provenance

* **Primary source:** the German commercial register (Handelsregister), i.e. announcements of new entries (*Neueintragung*).
* **No official API exists, and the portal's own terms limit automated use.** Checked on the official site
  (Registerportal, "Informationen", Nutzungsordnung, page version 2.12.12 of 2026-09-22):
  * point 3: retrieval is allowed for information purposes through **individual** requests; **systematic
    retrievals to build, extend or update a parallel full or partial register are not allowed**;
  * point 5: at most 60 searches or retrievals per hour; for more, a registered IP can be requested from the
    Servicestelle Registerportal at AG Hagen (point 7);
  * point 6: IPs are blocked and sessions ended on suspected violations;
  * point 4: data protection law (GDPR) applies to retrieving, storing, using and passing on the data.
* **Consequence:** a continuous radar that harvests new formations from the portal would likely count as
  building a parallel partial register (point 3), even below 60 requests/hour. So this project does **not**
  scrape the portal. `--source portal` is a disabled stub (rate limiter wired in, no scraper). Real data
  should come from individual lookups exported by hand (`--source export`), a licensed data provider, or an
  arrangement with the portal operator, as JSONL. I did not check the portal's `robots.txt`.
* **Real data via SI XML.** The portal offers each entry as "Strukturierter Registerinhalt" (XJustiz XML).
  `--source si` reads those files from individual lookups. It extracts company-level facts only and never
  reads the people sections (managing directors' names, birth dates, addresses), so no personal data reaches the
  database or `raw_payload`. Sole traders (a person, not a company) are rejected as `missing_name`.
  The register number is read only from the company's own entry: a KG's file also lists its general partner
  (a separate GmbH with its own number), which must not be picked up. A KG has no share capital, so its capital
  is the sum of the limited partners' liability contributions (labelled `capital_basis`), and partnerships state
  no business purpose in the register, so the purpose rule cannot fire for them.
  The SI file has no announcement date and no first-entry date, so `event_date` is the founding date
  (`gruendungsdatum`, or the first articles date) and `published` is the extract date. Both are labelled in the
  payload (`event_basis`, `published_basis`). Keep the XML files out of git (they contain personal data):
  put them in `data/` (git-ignored).
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
| (added) | `source`, `source_url`, `retrieved_at`, `run_id`, `first_seen_at`, `last_seen_at` | provenance |
| (added) | `spv_score`, `spv_label`, `spv_evidence` | hypothesis + the rules that fired |
| (added) | `crosscheck_status`, `crosscheck_evidence` | validation outcome |

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
* Privacy: `raw_payload` keeps each source record as-is. The synthetic fixtures contain no personal data,
  but real exports (e.g. managing directors) would, so GDPR applies (portal terms, point 4).
* The portal's legal notice says the data may not be published or reused under the name "Handelsregister"
  (section 8(2) HGB). Keep that in mind before publishing real data from this tool.
* For SI files the "formation" date is the founding date, not the date of the register entry.
* If a source states no formation date (common for older KG extracts), the record is staged with an empty
  `formation_date` instead of being lost; it is never guessed. A date that is present but malformed is still
  rejected. Filter with `WHERE formation_date IS NOT NULL` when a known date is needed.
* Legal form: `GmbH & Co. KG` is also recognised with words in between (`Foo GmbH & Co. Solarpark KG`).
* Upgrading from an earlier version of this project: the SQLite file must be recreated (`make clean`);
  Postgres is upgraded automatically.
* On a content change the latest version wins (no version history table).
* Only HRA/HRB entries are accepted; associations/co-operatives (VR, GnR, ...) are rejected on purpose.
* Court names are unified by prefix only, there is no list of official court names.
* The staging table is my own design: I could not find an existing `corporate_distress_records`
  definition in the base repo's top-level files (its `alembic/` folder was not inspected). If a migration
  defines it, align `iris_spv/schema.sql` with it.
* Validated with SQLite (tests) and a real Postgres server. The Dockerfile and compose file were written
  but not built in the authoring environment, so run `make docker-up` once before relying on them.

## Validation query

`sql/validation.sql` has eight checks (duplicates, untraceable rows, evidence, name-match rule, reject audit).
Results on the fixtures are in `QUALITY_REPORT.md`.
