
"""CHUI eTIMS submission creation — mock phase."""

import hashlib

import frappe

from kenya_compliance_via_slade.kenya_compliance_via_slade.queue.identity import (
    build_request_id,
)
from kenya_compliance_via_slade.kenya_compliance_via_slade.queue.job_store import (
    enqueue_job,
)

DOCTYPE = "CHUI eTIMS Submission"
ROUTE = "ChuiOscuSalesSubmit"


def create_mock_submission(parcel_id, transaction_id, company):
    """Create or reuse a mock submission for one test sale."""

    if not frappe.conf.get("chui_etims_mock_enabled"):
        frappe.throw("CHUI eTIMS mock mode is disabled")

    if not all([parcel_id, transaction_id, company]):
        frappe.throw("Parcel, transaction and company are required")

    # Mock assumption: transaction_id identifies one taxable sale.
    raw_key = f"CHUI|{company}|{parcel_id}|{transaction_id}"
    key = hashlib.sha256(raw_key.encode()).hexdigest()

    existing = frappe.db.get_value(
        DOCTYPE, {"idempotency_key": key}, "name"
    )

    if existing:
        return existing

    frappe.db.savepoint("chui_submission_insert")

    try:
        submission = frappe.get_doc({
            "doctype": DOCTYPE,
            "parcel_id": parcel_id,
            "transaction_id": transaction_id,
            "idempotency_key": key,
            "payment_status": "MOCK_PAID",
            "submission_status": "Pending",
        })
        submission.insert(ignore_permissions=True)

    except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
        frappe.db.rollback(save_point="chui_submission_insert")
        existing = frappe.db.get_value(
            DOCTYPE, {"idempotency_key": key}, "name"
        )
        if existing:
            return existing
        raise

    payload = {
        "document_name": submission.name,
        "company": company,
        "parcel_id": parcel_id,
        "transaction_id": transaction_id,
        "test_mode": True,
    }

    request_id = build_request_id(
        route_key=ROUTE,
        request_method="POST",
        company=company,
        settings_name=None,
        reference_doctype=DOCTYPE,
        reference_docname=submission.name,
        request_data=payload,
        page=1,
    )

    queue_name = enqueue_job({
        "route_key": ROUTE,
        "request_method": "POST",
        "status": "Pending",
        "company": company,
        "reference_doctype": DOCTYPE,
        "reference_docname": submission.name,
        "request_data": frappe.as_json(payload),
        "request_id": request_id,
        "dedupe_key": request_id,
    })

    frappe.db.set_value(
        DOCTYPE,
        submission.name,
        {
            "queue_job": queue_name,
            "submission_status": "Queued",
        },
    )

    return submission.name
