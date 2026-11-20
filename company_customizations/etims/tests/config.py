"""Edit only these settings to match the development bench."""
EXPECTED_BRANCHES = {
    "company_customizations": "dennis/etims-oscu-adapter",
    "kenya_compliance_via_slade": "feature/custom-oscu-provider",
    "csf_ke": "fix/chui-etims-queue-schema",
}
PARCEL_DOCTYPE = "Chui Parcels"
PARCEL_IDS = {1949: "249.00", 1955: "249.00", 2002: "248.99"}
EMPTY_PAYMENT_IDS = (2877, 2878, 2879, 2880, 2881)
MOCK_SUBMISSION = "eo98k369r2"
MOCK_JOB = "eo9km9gqvi"
# Optional dotted path to a zero-argument factory returning the existing extractor.
# It must expose read-only api_get(path), returning a raw dict or {data,error}.
EXTRACTOR_FACTORY = ""
# Optional dotted path to a zero-argument function returning a READ-ONLY batch
# summary (discovered, extracted, pending, failed: counts or collections).
# Only configure after checking that the function performs no writes/submissions.
EXTRACT_BATCH = ""
# Exact persisted settings containing the VERIFIED sandbox base URL; no API calls.
SANDBOX_DOCTYPE = ""
SANDBOX_URL_FIELD = ""
EXPECTED_SANDBOX_HOST = ""
