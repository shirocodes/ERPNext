# CHUI eTIMS — Hybrid Integration Implementation Specification and Step-by-Step Guide

Navari Framework + Thin Integration Bridge + CHUI Direct OSCU Adapter

- Document ID: CHUI-ETIMS-IMP-001
- Version: 1.1 — Implementation specification + engineering execution guide
- Date: 13 November 2026
- Status: Proposed implementation direction — development/sandbox GO; production conditional
- Target stack: ERPNext 15 / Frappe 15; kenya_compliance_via_slade (installed 0.8.2, verify exact commit); company_customizations; csf_ke

> Architecture decision: Retain Navari's existing eTIMS workspace, relevant settings, job-queue administration, ledger/receipt interface, and manual controls. Redirect submission through a thin Navari integration bridge into CHUI-owned business validation and direct KRA OSCU logic. Slade360 must have no active path for CHUI submissions.

> Reading guide: Part A specifies the architecture and controls. Part B gives practical implementation steps and test gates. The example code is illustrative, not an installed implementation.

## Part A — Architecture and Implementation Specification

### 1. Objective and scope

Build a direct KRA OSCU sales integration for paid parcel service transactions originating from CHUI Backoffice, using Navari as the operator-facing ERPNext layer and company_customizations as the business-logic and API-adapter layer.

Release 1 includes automatic ingestion of confirmed paid transactions; sales eligibility/tax validation; persistent idempotency; queueing; OSCU device setup and direct submission; response persistence; reconciliation; monitoring; and controlled manual retry/resubmission.

Release 1 excludes automatic credit notes, purchase/supplier eTIMS flows, stock movements, mass historical backfill, and replacement of CHUI's source-of-truth payment ledger. Credit notes remain a controlled manual accounting process until the follow-on release.

#### Success definition

A confirmed, eligible CHUI service sale is submitted once to the authorized KRA OSCU endpoint, receives a durable KRA reference, and is traceable from CHUI parcel/payment reference through the Navari eTIMS workspace. Failures must be visible and recoverable without issuing a second tax invoice for the same sale.

### 2. Target architecture

Principle: Navari owns presentation and job orchestration; CHUI owns eligibility, source snapshots, durable business idempotency, OSCU protocols, and interpretation of KRA results. The bridge contains routing and response-mapping only.

| Boundary | Owner | Responsibilities |
| --- | --- | --- |
| Payment event / parcel data | CHUI Backoffice | Authoritative paid status, reference, paid timestamp, sellable service lines |
| CHUI eTIMS Submission | company_customizations | Transaction snapshot, stable key, validation outcome, KRA status, audit trail |
| Navari UI and configurations | kenya_compliance_via_slade (adapted) | Workspace, roles, operator settings, reports, manual actions |
| Job queue | Navari/Frappe | Durable queue items, scheduling, worker progress, operational retry indicators |
| Thin bridge | Narrow Navari fork change | CHUI provider dispatch and Navari status/receipt projection |
| Direct KRA OSCU adapter | company_customizations | Device initialization, authentication, request mapping, HTTPS API calls, response normalization |
| KRA | External | OSCU registration, submission acceptance/rejection, official identifiers |

#### System boundaries

- No Slade fallback: selecting CHUI OSCU must never silently route to Slade360. Disable the original invoice auto-submit paths and Slade-specific schedulers for CHUI transactions.
- One orchestrator: both paid-parcel automation and UI manual actions call the same `submit_or_reconcile(submission_id)` application service.
- One business truth: the CHUI submission record is authoritative for the sale's KRA state. Navari's ledger is a linked operational view; its job queue is not a substitute for permanent tax-transaction idempotency.
- Safe failure: a network timeout after dispatch creates `Unknown` / `Needs Reconciliation`, not an unconditional retransmission.

### 3. Verified Navari integration points

The public develop branch exposes concrete hooks; the installed 0.8.2 code must be compared before implementation.

| Public source location | Observed behavior | Required action |
| --- | --- | --- |
| `hooks.py` | Sales Invoice lifecycle `doc_events`, eTims Job Queue DocType class override, scheduled auto-submission and queue maintenance | Audit and suppress conflicting Slade-specific triggers; retain safe queue maintenance |
| `apis/process_request.py` | Builds a Slade route and URL when creating the job; optionally enqueues it | Implement a CHUI-specific job factory or provider-aware branch; do not enqueue Slade-derived URLs |
| `overrides/server/etims_job_queue.py` | `CustomETimsJobQueue.run_queue()` delegates to `process_job_request()`; queue has its own request dedupe/retries | Insert provider dispatch at execution; preserve queue semantics only where compatible |
| `overrides/server/sales_invoice.py` | On-submit auto-submission and `send_invoice_details()` manual action | Disable/bypass Slade path for CHUI-origin sales; redirect relevant manual action |
| Navari ledger and print/QR features | ERPNext-specific receipt and status UI exists | Check whether they accept parcel references without an ERPNext Sales Invoice; adapt only necessary fields/views |

Technical caution: Navari's queue releases its active `dedupe_key` on terminal states. This protects its job lifecycle but does not enforce CHUI's permanent “one tax sale per paid event” guarantee. A separate unique business key is mandatory.

Extension strategy: First evaluate Frappe's supported whitelisted-method override and class override capabilities. Because `doc_events` hooks are additive and queue functions may be ordinary Python functions, prefer a minimal maintained Navari fork/patch for the provider dispatcher if clean hooks are insufficient. Avoid monkey-patching as the long-term production integration strategy.

### 4. Processing sequence

1. Detect paid event. CHUI Backoffice emits or exposes an authoritative payment-confirmed event; company_customizations authenticates the source and fetches/verifies current payment state server-side.
2. Create immutable sale snapshot. Capture parcel ID, payment-event/reference, date/time, company, branch, service lines, tax categories, amounts, and buyer details. Do not rebuild fiscal amounts from mutable parcel data on retry.
3. Validate. Require final paid status, eligible service revenue, valid company/branch/device settings, tax-code mappings, currency rules, and reconciliation between line totals/tax totals. Separate CHUI revenue (delivery, COD service fees where applicable) from pass-through merchant COD principal.
4. Claim business idempotency. Insert/update a unique record keyed by `(company, source_system, payment_event_id, sale_type)`. On duplicate, return existing status/reference without creating a new outbound sale.
5. Create Navari queue job. Using a CHUI-specific job factory, enqueue a reference to `submission_id`, with provider `CHUI_OSCU`; commit the submission record before worker dispatch (or use an after-commit/outbox pattern).
6. Dispatch through bridge. Navari queue worker invokes CHUI service by stable submission ID. It must not build Slade360 request headers, URLs, or payloads for this provider.
7. OSCU processing. CHUI maps the frozen transaction to the approved OSCU sale request, signs/authenticates using the registered device context, and submits over TLS to the configured sandbox/production endpoint.
8. Persist result. On accepted response, atomically save the official KRA identifiers, response metadata, and receipt/verification data; update Navari ledger/status projection. On definitive rejection, preserve validation/error details. On uncertain network result, halt automatic resend until reconciled.
9. Monitor and correct. Finance/authorized technical users view the ledger, retry safe failures, or manually reconcile unknown submissions through the same CHUI service.

### 5. Contract between Navari and CHUI

The bridge is deliberately small. Navari passes a stable ID and receives a normalized result; CHUI does not need Navari to know OSCU payload schemas.

```python
# Conceptual contract — names and fields to finalize after local code audit
# Thin Navari bridge

def dispatch_chui_submission(submission_id: str) -> dict:
    handler = frappe.get_attr(
        "company_customizations.etims.service.submit_or_reconcile"
    )
    return handler(submission_id)
```

Request: `{submission_id, provider: "CHUI_OSCU", initiated_by, correlation_id}`. Validate record ownership and caller authorization server-side; do not trust the submitted company or status.

Normalized result: `{submission_id, state, kra_invoice_number?, kra_receipt_url?, kra_receipt_signature?, external_reference?, error_code?, error_message?, retry_after?}`. Field names are internal proposed contract fields, not guaranteed KRA API response names.

| CHUI transaction state | Meaning | Navari presentation |
| --- | --- | --- |
| Draft / Validation Failed | Unprocessed or blocked before dispatch | Draft / action required |
| Queued / Processing | Accepted by job queue, not yet KRA-confirmed | Pending / processing |
| Confirmed | Official success response stored | Completed / receipt shown |
| Rejected | Explicit KRA refusal; requires corrected process | Failed, with cause |
| Retryable Failure | Confirmed safe-to-retry pre-dispatch or transient failure | Retrying |
| Unknown / Needs Reconciliation | Delivery or acknowledgement ambiguous | Needs review; no automatic resend |

### 6. Persistent data model

Create CHUI eTIMS Submission in company_customizations and link it from Navari's workspace and, where feasible, its ledger.

| Field group | Suggested fields |
| --- | --- |
| Source identity | `source_system`, `parcel_id`, `payment_event_id`, `payment_reference`, `sale_type`, `company` |
| Idempotency | `business_key` (UNIQUE), `payload_hash`, `revision`, `attempt_count`, `correlation_id` |
| Fiscal snapshot | `paid_at`, `invoice_date`, `branch_id`, `buyer_type`, `buyer_pin` (if required), `currency`, `net_total`, `tax_total`, `gross_total`, `sale_lines_json` |
| Processing | `state`, `queue_job`, `last_attempt_at`, `next_retry_at`, `last_error_class`, `last_error_code`, `review_required` |
| KRA receipt | `device_identifier`, `kra_invoice_number`, `kra_receipt_reference`, `verification_url`, `accepted_at`, `response_hash` |
| Audit | `initiated_by`, `override_reason`, `reconciled_by`, `reconciled_at`, append-only attempt log |

Add database uniqueness to `business_key` and enforce authorized state transitions. Store raw requests/responses in protected integration logs with secrets/PII redacted. The external document number must also have a unique constraint where the business semantics permit.

Open modeling decision: Determine whether paid parcels will also create ERPNext Sales Invoice records or only CHUI eTIMS submissions. The Navari ledger's native linkage may assume Sales Invoice, so support for direct parcel references must be verified before committing to reuse without an adapter view.

### 7. OSCU adapter design

Suggested package: `company_customizations/etims/` with modules `service.py`, `validation.py`, `models.py`, `idempotency.py`, `mapper.py`, `oscu_client.py`, `responses.py`, `reconciliation.py`, `api.py`, and `tests/`.

Methods: `verify_device()`, `initialize_device()`, `fetch_codes()`, `register_or_validate_item()` where needed, `submit_sale()`, `normalize_response()`, and `reconcile_submission()`. Use KRA's approved OSCU specification for request and response shapes; for sale submission, the original Navari OSCU project documents `TrnsSalesSaveWrReq`.

Environment and credentials: Sandbox/production configuration must be separated, including taxpayer PIN, branch ID, device serial/identifier, communication key, official base URL, timeout, and TLS settings. Treat device activation and key lifecycle as sensitive setup operations. Store secrets using Frappe Password fields or a managed secret store; never hard-code them or log Authorization data.

Operational guardrails: Use timeouts, bounded retry budgets, backoff, circuit breaking, correlation IDs, and rate limits. Distinguish definite non-delivery from ambiguous delivery. Do not treat an HTTP 200 alone as fiscal acceptance; inspect KRA business response codes and identifiers.

### 8. Business rules for CHUI service sales

| Rule | Initial release requirement |
| --- | --- |
| Trigger | Only payment-confirmed parcel service sales; not parcel creation alone |
| Services | CHUI delivery charges and eligible CHUI-owned service/COD fees as approved by Accounting |
| Merchant COD principal | Exclude merchant pass-through funds from CHUI sales revenue/tax invoice base unless Accounting/legal rules require otherwise |
| Tax classification | Map each service line to KRA-approved item/tax classifications and correct rounding |
| Buyer identity | Handle B2C and B2B field requirements per approved KRA specification; avoid inventing missing PIN values |
| Amendments | Do not overwrite accepted submissions; use approved manual correction/credit-note process in release 1 |
| Resubmission | Always run authorization, status check, and idempotency verification, including for manual actions |

Accounting sign-off is required on the tax point, taxable service lines, mapping, buyer data, and cancellation/credit note policy before production.

### 9. Failure handling and audit

| Scenario | Required behavior |
| --- | --- |
| Missing/invalid payment or tax codes | Validation Failed, actionable reason; no job dispatched |
| Same paid event delivered twice | Return existing CHUI submission; no duplicate KRA request |
| Worker crash before network dispatch | Requeue after lease expiry; preserve original business key |
| KRA rejects payload | Record response and field errors; require correction/review |
| Timeout after request may have reached KRA | Unknown, pause automatic retry, reconcile official status/reference first |
| KRA accepted but Navari status write fails | CHUI stays Confirmed; projection repair job catches up without resubmission |
| Manual retry on confirmed record | Refuse duplicate; show existing receipt |
| Wrong environment/branch | Fail closed before dispatch |
| Slade360 remains configured | It must not execute for CHUI provider; add regression test |

Audit requirement: Every attempt logs the business key, correlation ID, actor, timestamp, state transition, masked request/response hashes, queue job, and KRA reference where available. Retain evidence under the company's policy and applicable tax requirements.

### 10. Implementation phases and deliverables

| Phase | Engineering work | Exit gate |
| --- | --- | --- |
| 0 — Baseline / audit | Pin exact app versions/commits; inspect local hooks, queue, ledger DocTypes, scripts and scheduled jobs; back up dev site; confirm KRA direct OSCU authorization | Approved change map, no unknown Slade submit path |
| 1 — Domain model | Confirm accounting fields; create CHUI submission DocType, unique business key, sale snapshot, status machine | Duplicate-event and validation tests pass |
| 2 — Navari bridge | Add `CHUI_OSCU` provider, provider-aware job factory/worker dispatch, UI actions, ledger projection, disable Slade auto path | Manual sandbox job reaches CHUI mock adapter only |
| 3 — OSCU client | Register sandbox device, configure credentials, tax/item mapping, submit/normalize responses | KRA sandbox accepts one valid service sale |
| 4 — Automated pipeline | Connect paid-parcel source, reliable ingestion, enqueue-after-commit/outbox, reconciliation and errors | Paid parcel can complete unattended; duplicate prevented |
| 5 — UAT / security | Cover timeout ambiguity, restarts, queue recovery, access control, mismatched tax totals and ledger reports | Test matrix signed off; no duplicate emission |
| 6 — Production release | Approvals, restricted credentials, feature-flag rollout, monitoring, cutover and rollback readiness | KRA authorization, Finance sign-off and go-live checklist complete |

Recommended implementation order: Start with Phase 0 (local Navari audit), then prove a manual UI → Navari queue → CHUI mock adapter → ledger round trip before connecting KRA. This isolates the hardest compatibility risk. Add actual OSCU calls only after the bridge demonstrates correct queue behavior.

### 11. Development site verification and safe cutover

```bash
cd ~/frappe-bench
bench --site speedychui list-apps
bench doctor

grep -RniE \
  "process_request|run_queue|send_invoice_details|generic_invoices_on_submit_override|scheduler_events|VSCU Slade 360" \
  apps/kenya_compliance_via_slade/kenya_compliance_via_slade \
  --include='*.py'
```

Document each execution point as retain, disable, replace with dispatcher, or out of scope. Capture a DB/site backup before changes; use feature flag `CHUI_OSCU_ENABLED=false` initially. Only enable sandbox when the original Slade submit triggers have been demonstrably disabled for CHUI-origin transactions.

Rollback: Disable the feature flag and pause CHUI queue dispatch while retaining all existing audit records. Do not automatically reactivate Slade360 or replay unconfirmed transactions. Reconcile the outstanding queue first. Use schema migrations and versioned patches for new DocTypes, fields, and permissions; avoid editing production directly.

### 12. Acceptance criteria / UAT matrix

- [ ] An eligible paid parcel creates one durable submission with a frozen line/tax snapshot.
- [ ] An unpaid, reversed, or invalid parcel cannot enter the OSCU submission queue.
- [ ] Two concurrent imports of the same payment event resolve to one business-key record.
- [ ] Navari manual submit invokes CHUI validation and does not call Slade360.
- [ ] Navari job queue dispatches by `submission_id`; CHUI adapter receives no Slade URL or credentials.
- [ ] Sandbox success stores the official receipt details and displays them correctly in Navari.
- [ ] Definitive KRA rejection shows actionable error without marking receipt confirmed.
- [ ] Ambiguous timeout is held for reconciliation; no blind automatic second submission.
- [ ] Background worker crash and queue recovery do not create duplicate fiscal transactions.
- [ ] Confirmed transactions cannot be re-sent by repeated manual button clicks.
- [ ] Accounting confirms service/tax totals and excludes unauthorized pass-through COD principal.
- [ ] Environment isolation, role permissions, log redaction, and secret handling pass review.

### 13. Decisions / prerequisites still open

| Decision | Owner | Required before |
| --- | --- | --- |
| OSCU direct integration registration, device approval and sandbox access | CHUI / KRA liaison | Phase 3 |
| Final tax/service definitions, buyer data and fiscal recognition point | Accounting + Engineering | Phase 1 / production |
| Direct parcel submission versus ERPNext Sales Invoice document creation | Accounting + ERP team | Phase 1 |
| Exact local Navari code version, queue hooks and ledger compatibility | ERP engineering | Phase 2 |
| Authorized operator roles for manual submission/reconciliation | Finance / Security | Phase 5 |
| Manual credit-note workflow | Accounting | Production |
| AGPL-3.0 obligations for the modified Navari fork | Legal / Engineering | Distribution / deployment |

### 14. Release decision

GO for technical implementation and sandbox validation. Production remains NO-GO until local source compatibility is verified, Slade execution is removed from the CHUI path, direct KRA OSCU authorization is confirmed, the end-to-end UAT matrix passes, and Finance signs off on tax treatment.

## References

1. Navari via Slade repository: https://github.com/navariltd/kenya-compliance-via-slade
2. Navari direct OSCU repository (reference implementation, no longer actively developed): https://github.com/navariltd/kenya-compliance
3. Public Navari hooks: https://raw.githubusercontent.com/navariltd/kenya-compliance-via-slade/develop/kenya_compliance_via_slade/hooks.py
4. Public Navari queue: https://raw.githubusercontent.com/navariltd/kenya-compliance-via-slade/develop/kenya_compliance_via_slade/kenya_compliance_via_slade/overrides/server/etims_job_queue.py
5. Public Navari request builder: https://raw.githubusercontent.com/navariltd/kenya-compliance-via-slade/develop/kenya_compliance_via_slade/kenya_compliance_via_slade/apis/process_request.py
6. Frappe hooks: https://docs.frappe.io/framework/user/en/python-api/hooks
7. KRA system-to-system integration: https://www.kra.go.ke/business/etims-electronic-tax-invoice-management-system/learn-about-etims/etims-system-to-system-integration
8. KRA OSCU activation guide: https://www.kra.go.ke/images/publications/OSCU_VSCU_Step-by-Step_Guide-on-how-to-sign-up.pdf

> Verification note: architectural guidance is based on publicly available source and user-provided project context; local installed code and actual KRA sandbox behavior have not been inspected or tested in this document.

## Part B — Step-by-Step Engineering Implementation Guide

```bash
grep -RniE \
  'process_request|process_job_request|run_queue|send_invoice_details|on_submit|scheduler_events|VSCU Slade 360|build_headers|get_server_url' \
  "$NAVARI" --include='*.py'

grep -RniE 'Slade|etims|eTims Job Queue|Integration Request' \
  "$NAVARI" --include='*.js' | head -100
```

In a read-only Frappe console, inspect the DocType metadata and hook registrations:

```python
bench --site speedychui console
import frappe
print(frappe.get_hooks('override_doctype_class').get('eTims Job Queue'))
print(frappe.get_hooks('doc_events').get('Sales Invoice'))
print([f.fieldname for f in frappe.get_meta('eTims Job Queue').fields])
```

Audit matrix:

- (a) Navari workspace/settings: retain
- (b) Job Queue: extend
- (c) `process_request()` building Slade URL: bypass for CHUI provider
- (d) `run_queue()` / `process_job_request()`: route CHUI jobs to the adapter
- (e) Sales Invoice hook, hourly/daily auto-submit, ledger schedulers, QR/print handlers: classify individually

Never turn off all Navari jobs indiscriminately—some support the UI or non-CHUI features.

Exit criteria: every outbound Slade360 code path is documented and CHUI jobs can be positively identified.

### Step 3 — Prepare two controlled code branches and the ownership contract

Use two apps: a minimal maintained fork of `kenya_compliance_via_slade` for dispatch/UI glue, and `company_customizations` for fiscal/business functionality. Do not copy the entire Navari app into CHUI. Start branches only after preserving local changes:

```bash
cd ~/frappe-bench/apps/kenya_compliance_via_slade
# In the clean project repository / approved fork:
git switch -c feature/chui-oscu-provider

cd ~/frappe-bench/apps/company_customizations
git switch -c feature/chui-etims-direct-oscu
```

Proposed internal contract:

| Contract | Producer → Consumer | Requirement |
| --- | --- | --- |
| `submission_id` | Navari bridge → CHUI service | Required stable DocType name; not raw parcel payload |
| `provider=CHUI_OSCU` | Navari job factory → queue worker | Explicit routing, no fallback to Slade |
| `correlation_id` | CHUI ingestion → every attempt | Consistent cross-app tracing |
| normalized state + KRA references | CHUI service → Navari ledger | No KRA-specific parsing in Navari |
| `source_event_id` + `business_key` | CHUI payment → CHUI Submission | Unique, immutable business dedupe |

Exit criteria: code owners, dependency direction, and a single approved submission service interface.

### Step 4 — Create the CHUI configuration and domain records

Add managed DocTypes inside `company_customizations`:

- CHUI eTIMS Settings: enabled flag (initially off), environment (sandbox / production), company/branch, active provider (`CHUI_OSCU`), OSCU device identity, registered KRA PIN, sandbox/prod API base URL, request timeout, and safely stored communication key/password. Only authorized roles may edit settings.
- CHUI eTIMS Submission: company, source system, parcel ID, payment event/reference, sale type, immutable canonical fiscal JSON, amounts, hash, business key, state, queue job ID, KRA identifiers, last error, correlation ID, and timestamps.
- CHUI eTIMS Attempt: append-only attempt number, submission link, worker reference, initiated by, state transitions, redacted request/response fingerprints, result classification, and timestamps.

Enforce a database `UNIQUE` index on the immutable `business_key`; validate uniqueness in database migrations/patches rather than relying on application-level lookups alone. Avoid storing unmasked credentials or full personal data in job queues or logs. The source sale snapshot is immutable after initial validation; correction is a controlled state transition, not silent editing after fiscal submission.

Proposed business key: `company | source_system | payment_event_id | sale_type`. Do not use only `parcel_id`, as a parcel may have multiple distinct CHUI-owned charge events. Define reauthorizations, partial captures, and reversals with Accounting before finalizing key semantics.

Deliverable: migrated Dev DocTypes + role permissions + uniqueness concurrency test. Run migration only after deploying these schema changes to the test site:

```bash
bench --site speedychui migrate
bench --site speedychui clear-cache
```

### Step 5 — Build the paid-parcel ingestion and validation service

Choose a trusted and authenticated source: a CHUI Backoffice paid-event API, signed webhook + server-side verification, or approved read-only database integration. The service must verify that money is actually received/settled, rather than blindly trusting a UI status string. Implement an outbox or periodic recovery poll so events are not lost during outages.

Processing order: authenticate event → fetch authoritative paid state → normalize revenue lines → validate company/branch/customer and tax classification → freeze snapshot → atomically claim unique key → enqueue after transaction commit. Only invoice CHUI-owned delivery/COD service fees that Accounting approves; do not treat a merchant's pass-through COD principal as CHUI revenue.

Example illustrative schema, not a KRA payload:

```json
{
  "source_system": "chui_backoffice",
  "parcel_id": "EXAMPLE-PARCEL-1",
  "payment_event_id": "EXAMPLE-PAYMENT-1",
  "company": "<ERPNext Company>",
  "paid_at": "<ISO-8601 timestamp>",
  "currency": "KES",
  "lines": [{"service_code": "<approved code>", "amount": "<decimal>", "tax_code": "<approved KRA code>"}]
}
```

Exit criteria: a valid paid event produces exactly one CHUI Submission; an unpaid event produces none; repeat/concurrent events reuse the existing record.

### Step 6 — Implement provider-aware Navari job creation and worker dispatch

This is the thin bridge. A CHUI job must not inherit Slade-built URL, route path, headers, or authentication. Add an explicit provider field to the queue (or an equally robust discriminator) and a CHUI-specific job factory. Restrict `reference_doctype` to CHUI eTIMS Submission and `reference_docname` to the stable submission ID.

Pseudo-implementation (adapt to the installed Navari queue API):

```python
# Navari fork: conceptual dispatch branch only
# This is NOT a drop-in replacement for CustomETimsJobQueue.run_queue.

def dispatch_provider_job(job):
    if job.provider == "CHUI_OSCU":
        if job.reference_doctype != "CHUI eTIMS Submission":
            raise ValueError("Unexpected CHUI job reference")
        handler = frappe.get_attr(
            "company_customizations.etims.service.submit_or_reconcile"
        )
        return handler(job.reference_docname)
    # Non-CHUI behavior must be explicitly scoped and reviewed.
    return execute_original_provider(job)
```

Implement the queue state mapping in one place. The CHUI service owns fiscal acceptance/uncertainty; the Navari job status is an operational projection. Do not set the job to `Completed` merely because an HTTP call returned 200. Use controlled `frappe.get_attr()` server-side imports and server-side permissions; do not call a public API endpoint to execute worker code.

Critical: Navari's public `process_request()` builds a Slade route at job creation, while the queue executes it later. Therefore both code paths require CHUI-aware behavior. Verify no existing Sales Invoice `on_submit` handler or background auto-submit scheduler can emit the same CHUI transaction to Slade.

Exit criteria: a manual UI action creates one `CHUI_OSCU` job; the worker invokes only `company_customizations`; no network call to Slade is possible from the CHUI route.

### Step 7 — Reuse Navari's operational UI and ledger through a result bridge

Keep the existing Navari workspace and as many settings/list/report views as compatible. Add a CHUI-specific provider selector, a linked source submission reference, status and receipt fields, and the authorized actions Submit, Retry Safe Failure, and Reconcile Unknown. Inspect whether the Navari ledger requires an ERPNext Sales Invoice; if so, extend the ledger projection or introduce a linked view, rather than creating fabricated Sales Invoices.

Recommended rules: Confirmed is read-only; Unknown only permits reconciliation (not blind resend); Validation Failed allows corrected source data under audit; manual retries call the same CHUI service as automatic jobs. Preserve the receipt QR/print template only if it can correctly render official KRA data from OSCU.

Exit criteria: manual UI → Navari queue → CHUI mock adapter → Navari ledger, with no external network dependency. Complete this before the real OSCU client.

### Step 8 — Complete KRA OSCU sandbox registration and device initialization

KRA's OSCU/VSCU onboarding guide (version 1.1, April 2023) describes sandbox sign-up at https://etims-sbx.kra.go.ke, registration/service request for OSCU, approval, and device activation. It identifies the sandbox base https://etims-api-sbx.kra.go.ke and production base https://etims-api.kra.go.ke, with activation example path `/selectInitOsdcInfo`. Confirm current endpoint and required fields in the approved OSCU API specification before coding against them.

Actions:

1. confirm whether CHUI is an approved self-integrator or will require certification;
2. finish sandbox registration and request/approval;
3. capture authorized company PIN, branch office ID, equipment/device identifiers, and communication key through restricted configuration;
4. write a dedicated `initialize_device()` / `verify_device()` path;
5. log activation results without exposing secrets.

Do not reuse Slade360 access tokens as OSCU credentials.

Exit criteria: device approved/initialized in sandbox; authenticated verification succeeds and credentials are stored securely.

### Step 9 — Implement the direct OSCU adapter

Create the proposed package (adjust namespace to the actual Python package root):

```text
company_customizations/
  etims/
    service.py          # state machine / orchestrator
    validation.py       # CHUI business and tax checks
    idempotency.py      # unique business key and concurrency
    mapper.py           # frozen CHUI sale -> approved OSCU schema
    oscu_client.py      # TLS, device credentials, timeouts
    responses.py        # normalized accept/reject/unknown
    reconciliation.py   # external status and manual evidence
    projection.py       # write result into Navari UI/ledger
    tests/
```

Required adapter methods: `initialize_device`, `verify_device`, `fetch_codes`, `ensure_item_mapping`, `submit_sale`, `normalize_response`, and `reconcile_submission` (if supported by the current KRA specification; otherwise define a controlled manual procedure). Navari's older direct-OSCU repository documents sale endpoint `TrnsSalesSaveWrReq`, but is a reference implementation, not the acceptance authority for today's request format.

Client rules: one HTTP abstraction; explicit sandbox/prod endpoints; TLS certificate validation; bounded timeouts; sanitized request logs; no credential strings in URL/query or traceback; parse KRA's business-level success code and fiscal identifiers, not just HTTP status. Use `Decimal` for currency arithmetic and consistent tax rounding.

Exit criteria: one valid service-sale payload accepted in KRA sandbox with official response persisted against the CHUI submission.

### Step 10 — Implement safe result handling, retries, and reconciliation

Use an explicit state machine:

```text
Draft -> Validated -> Queued -> Processing
  -> Confirmed                  (KRA accepted)
  -> Rejected                   (definitive business refusal)
  -> Retryable Failure          (proven pre-dispatch / safe condition)
  -> Unknown / Needs Review     (network or acknowledgement ambiguous)
```

Enforce state transitions in application code and database constraints as appropriate. On a successful OSCU response, store exact KRA reference, device, and receipt metadata before updating the Navari ledger. If ledger projection fails, repair the projection without re-submitting. If a timeout occurred after the request may have reached KRA, stop automatic retries and reconcile from official KRA records or a supported official lookup; if no reliable programmatic query exists, use an authorized manual check.

Add a scheduled outbox/queue recovery task and a separate projection-repair task. Bound retries for known safe failures and add circuit-breaker behavior. Do not let the Navari queue terminal-state dedupe replace the permanent unique CHUI business key.

Exit criteria: crashes, duplicates, retries, and ambiguous network outcomes do not generate a second fiscal sale.

### Step 11 — Test in layers and run UAT

Recommended order:

1. Unit tests: canonical payload mapping, `Decimal` totals, B2C/B2B validation, unique keys, allowed state transitions, response classification.
2. Integration tests (mock): manual Navari button → provider job → CHUI handler → mocked KRA response → ledger projection; enforce zero Slade360 requests.
3. Sandbox tests: device verification, valid sale, invalid tax code, rejected sale, transient failure, official receipt visibility.
4. Concurrency/recovery: duplicate webhook, two workers on same business key, worker crash before/after dispatch, ambiguous timeout, retry on confirmed record, schema migration restart.
5. Permission tests: unauthorized user cannot change OSCU credentials, submit, force retry, or reconcile; audit entries are immutable and secrets do not appear in logs.

Once tests exist, run them on the test site:

```bash
cd ~/frappe-bench
bench --site speedychui run-tests --app company_customizations
bench --site speedychui run-tests --app kenya_compliance_via_slade
bench doctor
```

Some upstream Navari tests may expect Slade credentials or an isolated environment; adapt fixtures and run the relevant suites rather than sending live requests from tests. If the test site's scheduler is disabled, explicitly document whether tests used manual queue execution or an approved isolated scheduler; do not enable production jobs to make a test pass.

UAT sign-off: Engineering verifies routing/idempotency/recovery; Accounting validates posted service amounts, taxable lines, receipt identifiers, and manual correction rules; Security verifies keys and roles.

### Step 12 — Controlled production go-live and rollback

Go-live gate: completed KRA approval/certification as applicable; Finance sign-off; production device registration; passed sandbox/UAT tests; source/queue observability; reviewed code branches; valid backup/rollback; tested disabling flag; and no CHUI-origin path to Slade360.

Deployment sequence:

1. Merge/pin Navari fork and CHUI app commit versions; deploy both together to a staging replica.
2. Run migrations if schema has changed; smoke-test existing ERPNext/stock/purchase workflows for regressions.
3. Provision production OSCU settings using restricted secrets; leave `CHUI_OSCU_ENABLED=false`.
4. Enable for a small, controlled group of new paid transactions, observe logs and reconcile actual KRA receipts.
5. Verify job volumes, latency, queue backlog, unconfirmed/unknown status, and count/value reconciliation daily during the initial rollout.
6. Broaden rollout after Finance confirms correct invoices and no duplicate submissions.

Rollback: turn off `CHUI_OSCU_ENABLED`, pause new CHUI dispatch, and keep the ledger/audit data intact. Do not replay unknown records or auto-switch back to Slade. Reconcile accepted and uncertain transactions before any restart of fiscal submissions. Reverting schema or code must follow a version-matched restoration plan, not an ad hoc database deletion.

### Step 13 — Release checklist and decisions requiring sign-off

| Checkpoint | Acceptance evidence | Owner |
| --- | --- | --- |
| App compatibility | Exact installed 0.8.2 commit, hooks/queue paths, zero ambiguous Slade routes | ERP engineering |
| Revenue policy | CHUI service line mappings, tax point, COD principal exclusion decision | Accounting |
| Document ownership | Decision on ERPNext Sales Invoice creation and Navari ledger projection | ERP + Accounting |
| Sandbox setup | KRA OSCU approval, device activation, verified authorized endpoint | KRA liaison / Engineering |
| Idempotency | Persistent unique key + concurrent/retry/timeout tests | Engineering |
| UI re-use | Manual/automatic path unified, receipts displayed, roles enforced | ERP engineering |
| Operational readiness | Monitoring, reconciliation SOP, secrets, rollback and backups | Operations / Security |
| Production approval | Sign-off, rollout limits, cutover owner and incident escalation | Technical lead + Finance |

### Step 14 — Recommended first engineering session

Complete Steps 1 and 2 first, then create a minimal `CHUI_OSCU` queue job that points to a mock `submit_or_reconcile()` function. Treat the first demonstration as successful only when a Navari operator can initiate a transaction, the queue invokes CHUI code, the result is visible in Navari, and network inspection confirms zero Slade360 calls. That proves the architectural seam before adding KRA credentials or tax payloads.

#### Source verification notes for this execution guide

- Public Navari `hooks.py` registers the eTims Job Queue class override, Sales Invoice hooks, and submission/ledger schedules. Source: https://github.com/navariltd/kenya-compliance-via-slade/blob/develop/kenya_compliance_via_slade/hooks.py
- Public Navari `apis/process_request.py` constructs a VSCU Slade 360 route in the job-creation path. Source: https://github.com/navariltd/kenya-compliance-via-slade/blob/develop/kenya_compliance_via_slade/kenya_compliance_via_slade/apis/process_request.py
- Public Navari queue class routes execution through `process_job_request()` and documents release of job dedupe keys at terminal states. Source: https://github.com/navariltd/kenya-compliance-via-slade/blob/develop/kenya_compliance_via_slade/kenya_compliance_via_slade/overrides/server/etims_job_queue.py
- KRA OSCU/VSCU registration and activation: https://www.kra.go.ke/images/publications/OSCU_VSCU_Step-by-Step_Guide-on-how-to-sign-up.pdf (April 2023; confirm current procedure)
- KRA system-to-system integration: https://www.kra.go.ke/business/etims-electronic-tax-invoice-management-system/learn-about-etims/etims-system-to-system-integration
- KRA indicates that credit notes can only be generated from the solution that issued the original invoice; keep this in the release-1 manual correction SOP. Source: https://www.kra.go.ke/business/etims-electronic-tax-invoice-management-system/learn-about-etims/types-of-etims-solutions
- Frappe hook extension guidance: https://docs.frappe.io/framework/user/en/python-api/hooks
