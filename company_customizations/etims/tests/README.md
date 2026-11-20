# CHUI eTIMS regression checks — 19 November 2026

Development bench only. This baseline inspects actual Frappe schema, indexes, Git branches, scheduler, workers, registered queue controller, historical mock records and parcel data. It does not create jobs, submit tax invoices, migrate schema or invoke processing methods. Optional Backoffice GET checks use your existing extractor. No API keys are included.

## Run

1. Review `config.py`. Defaults use the known branches, historic fixture IDs and the parcel schema from the sync script. Confirm the DocType and child table names on your site.
2. Start `cd ~/frappe-bench` then `bench --site YOUR_DEV_SITE console`.
3. Inside the console run `%run ../apps/company_customizations/company_customizations/etims/tests/run_tests.py all`

| Stage | Script | What it checks |
|---|---|---|
| 01 | test_01_environment.py | Apps, branches, schema survival, scheduler, workers |
| 02 | test_02_submission.py | Fields, physical uniqueness, existing historical submission/link |
| 03 | test_03_queue.py | Fields, statuses, uniqueness, manager config, historical outcome |
| 04 | test_04_bridge.py | Active controller override and process method |
| 05 | test_05_etl.py | Stored parcels, payment attempts, precision, optional live GETs and batch summary |
| 06 | test_06_sandbox.py | Expected HTTPS sandbox host, without initiating a session or sale |

`OK` means the checks executed successfully; `skipped` means no evidence was collected for that test. Missing historical fixtures are intentionally skipped, not marked passed. An exact sandbox host must be independently verified, not guessed.

## Optional extraction checks

Set `EXTRACTOR_FACTORY` to a dotted path to a zero-argument wrapper returning your existing extractor. Its `api_get(path)` must perform read-only GETs. Set `EXTRACT_BATCH` to a wrapper for the existing extraction dry-run returning the complete summary dictionary only after reviewing that it cannot make writes. Leave either blank until the actual implementation signature is confirmed.

## Not yet automated

Fresh mock submission creation, forced duplicate/concurrent insert attempts, queue execution/retry/recovery, provider mock response and no-network assertions, pagination fault injection, and sandbox connectivity require the actual app-source method signatures and mock boundaries. Historical evidence and unique-index checks are not substitutes for those behavioral tests. Run `bench --site YOUR_DEV_SITE migrate` only as intentional maintenance, not as a regression test. Do not run the suite against production. Eligibility/payload/real invoice tests belong to later stages.
