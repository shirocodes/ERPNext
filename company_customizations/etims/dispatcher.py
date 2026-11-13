# company_customizations/company_customizations/etims/dispatcher.py

import frappe

CHUI_ROUTE = "ChuiOscuSalesSubmit"


def process_job(job_name: str) -> dict:
    """Process a CHUI OSCU job (mock implementation)."""

    job = frappe.get_doc("eTims Job Queue", job_name)

    if job.route_key != CHUI_ROUTE:
        frappe.throw("Unsupported CHUI eTIMS route")

    # Temporary mock response.
    # No external KRA API calls.
    return {
        "mode": "mock",
        "status": "mock_success",
        "job_name": job_name,
    }
