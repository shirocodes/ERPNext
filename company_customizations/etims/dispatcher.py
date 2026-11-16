
"""CHUI OSCU job dispatcher — mock phase."""

import frappe

CHUI_ROUTE = "ChuiOscuSalesSubmit"


def process_job(job_name: str) -> dict:
    if not frappe.conf.get("chui_etims_mock_enabled"):
        frappe.throw("CHUI eTIMS mock mode is disabled")

    job = frappe.get_doc("eTims Job Queue", job_name)

    if job.route_key != CHUI_ROUTE:
        frappe.throw("Unsupported CHUI eTIMS route")

    if job.reference_doctype != "CHUI eTIMS Submission":
        frappe.throw("Invalid CHUI submission reference")

    payload = frappe.parse_json(job.request_data)

    if payload.get("test_mode") is not True:
        frappe.throw("Only mock jobs are allowed")

    submission = frappe.get_doc(
        "CHUI eTIMS Submission",
        job.reference_docname,
    )

    if submission.submission_status == "Mock Completed":
        return {"status": "mock_success", "job_name": job_name}

    submission.db_set("submission_status", "Processing")

    response = {
        "mode": "mock",
        "status": "mock_success",
        "queue_job": job_name,
        "message": "CHUI OSCU mock execution successful",
    }

    submission.db_set({
        "submission_status": "Mock Completed",
        "kra_response": frappe.as_json(response),
    })

    return response
