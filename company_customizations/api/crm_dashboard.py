
import frappe
from frappe.utils import now_datetime


PIPELINE_STATUS_FIELDS = {
    "ict_assessment": "ICT Team Assessment",
    "sandbox": "Sandbox Testing",
    "marketing_ops_training": "Marketing Team Assessment",
    "sign_off": "Production Ready",
}


REQUIRED_LEAD_FIELDS = [
    "custom_integration_required",
    "custom_does_the_merchant_have_an_online_presence",
    "custom_ecommerce_platform_confirmed",
    "custom_integration_status",
    "custom_ict_approval_status",
    "custom_type_of_integration",
    "custom_daily_deliveries_nairobi_area",
    "custom_expected_monthly_deliveries",
]


def _as_number(value):
    """Convert a value to a number, treating empty values as zero."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0


def _is_sales_assessment_qualified(lead):
    """
    Sales Assessment:
    Integration Required = NO
    AND (Online Presence = YES OR E-commerce Platform = YES)
    """
    return (
        lead.get("custom_integration_required") == "NO"
        and (
            lead.get("custom_does_the_merchant_have_an_online_presence") == "YES"
            or lead.get("custom_ecommerce_platform_confirmed") == "YES"
        )
    )


def _is_sent_back_to_sales(lead):
    """
    Exception:
    Returned to Sales Requirements Gathering
    because ICT rejected or requested clarification.
    """
    return (
        lead.get("custom_integration_status") == "Sales Requirements Gathering"
        and lead.get("custom_ict_approval_status")
        in ("Rejected", "Requires Clarification")
    )


@frappe.whitelist()
def get_dashboard_data():
    """Return permission-aware CRM dashboard aggregates."""

    if not frappe.has_permission("Lead", "read"):
        frappe.throw(
            "You do not have permission to view Lead records.",
            frappe.PermissionError,
        )

    # Verify that all required custom fields exist.
    meta = frappe.get_meta("Lead")

    missing_fields = [
        fieldname
        for fieldname in REQUIRED_LEAD_FIELDS
        if not meta.has_field(fieldname)
    ]

    if missing_fields:
        frappe.throw(
            "The CRM dashboard cannot run because these Lead fields are missing: "
            + ", ".join(missing_fields)
        )

    fields = ["name"] + REQUIRED_LEAD_FIELDS

    # Retrieve Leads while respecting the current user's permissions.
    leads = frappe.get_list(
        "Lead",
        fields=fields,
        filters={"docstatus": ["<", 2]},
        limit_page_length=100000,
        order_by="name asc",
    )

    # Pipeline totals.
    pipeline = {
        "total_leads": len(leads),
        "sales_assessment": 0,
        "ict_assessment": 0,
        "sandbox": 0,
        "marketing_ops_training": 0,
        "sign_off": 0,
        "live": None,
    }

    sent_back_to_sales = 0

    # Integration type breakdown.
    integration_type_counts = {}
    integration_type_blank_count = 0

    # Delivery metrics.
    daily_deliveries_total = 0
    daily_deliveries_populated_count = 0

    expected_monthly_deliveries_total = 0
    expected_monthly_deliveries_populated_count = 0

    # Daily delivery totals by pipeline stage.
    pipeline_delivery_metrics = {
       "total_leads": {
           "total": 0,
           "populated_lead_count": 0,
       },
       "sales_assessment": {
           "total": 0,
           "populated_lead_count": 0,
       },
       "ict_assessment": {
           "total": 0,
           "populated_lead_count": 0,
       },
       "sandbox": {
          "total": 0,
          "populated_lead_count": 0,
       },
       "marketing_ops_training": {
          "total": 0,
          "populated_lead_count": 0,
       },
       "sign_off": {
          "total": 0,
          "populated_lead_count": 0,
       },
    }
    # Process the retrieved Lead records.
    for lead in leads:

        # Get daily delivery value
        daily_value = _as_number(
            lead.get("custom_daily_deliveries_nairobi_area")
        )

       # Stage 1: All Leads.
        stage = pipeline_delivery_metrics["total_leads"]

        if daily_value > 0:
            stage["total"] += daily_value
            stage["populated_lead_count"] += 1
        # Sales qualification.
        if _is_sales_assessment_qualified(lead):
            pipeline["sales_assessment"] += 1
            stage = pipeline_delivery_metrics["sales_assessment"]

            if daily_value > 0:
                stage["total"] += daily_value
                stage["populated_lead_count"] += 1
        # ICT, Sandbox, Marketing/Ops and Sign-off stages.
        for key, status in PIPELINE_STATUS_FIELDS.items():
            if lead.get("custom_integration_status") == status:
                pipeline[key] += 1

                stage = pipeline_delivery_metrics[key]

                if daily_value > 0:
                    stage["total"] += daily_value
                    stage["populated_lead_count"] += 1
        # Exception: Sent Back to Sales.
        if _is_sent_back_to_sales(lead):
            sent_back_to_sales += 1

        # Integration type breakdown.
        integration_type = lead.get("custom_type_of_integration")

        if integration_type:
            integration_type_counts[integration_type] = (
                integration_type_counts.get(integration_type, 0) + 1
            )
        else:
            integration_type_blank_count += 1

        # Daily deliveries.
        daily_value = lead.get("custom_daily_deliveries_nairobi_area")

        if _as_number(daily_value) > 0:
            daily_deliveries_total += _as_number(daily_value)
            daily_deliveries_populated_count += 1

        # Expected monthly deliveries.
        monthly_value = lead.get("custom_expected_monthly_deliveries")

        if _as_number(monthly_value) > 0:
            expected_monthly_deliveries_total += _as_number(monthly_value)
            expected_monthly_deliveries_populated_count += 1

    # Return dashboard data.
    return {
        "generated_at": now_datetime().isoformat(),

        "pipeline": pipeline,
        "pipeline_delivery_metrics": pipeline_delivery_metrics,

        "exceptions": {
            "sent_back_to_sales": sent_back_to_sales,
        },

        "integration_types": {
            "counts": integration_type_counts,
            "blank_count": integration_type_blank_count,
        },

        "delivery_metrics": {
            "daily_deliveries_nairobi_area": {
                "total": daily_deliveries_total,
                "populated_lead_count": daily_deliveries_populated_count,
            },
            "expected_monthly_deliveries": {
                "total": expected_monthly_deliveries_total,
                "populated_lead_count": expected_monthly_deliveries_populated_count,
            },
        },

        "record_scope": {
            "doctype": "Lead",
            "filter": "docstatus < 2",
            "permission_aware": True,
        },
    }



@frappe.whitelist()
def get_pipeline_leads(stage, start=0, page_length=20):
    """
    Return a permission-aware, paginated list of Leads
    belonging to a selected integration pipeline stage.

    Read-only endpoint. No database writes.
    """

    # Verify Lead read permission.
    if not frappe.has_permission("Lead", "read"):
        frappe.throw(
            "You do not have permission to view Lead records.",
            frappe.PermissionError,
        )

    # Supported pipeline stages.
    valid_stages = {
        "sales_assessment",
        "ict_assessment",
        "sandbox",
        "marketing_ops_training",
        "sign_off",
    }

    if stage not in valid_stages:
        frappe.throw("Invalid integration pipeline stage.")

    # Validate pagination parameters.
    try:
        start = max(int(start), 0)
        page_length = int(page_length)
    except (TypeError, ValueError):
        frappe.throw("Invalid pagination parameters.")

    # Limit page size to protect server performance.
    page_length = min(max(page_length, 1), 100)

    # Base filters.
    filters = {
        "docstatus": ["<", 2],
    }

    or_filters = None

    # Apply the exact existing pipeline classification rules.
    if stage == "sales_assessment":

        filters["custom_integration_required"] = "NO"

        or_filters = [
            {
                "custom_does_the_merchant_have_an_online_presence": "YES"
            },
            {
                "custom_ecommerce_platform_confirmed": "YES"
            },
        ]

    else:

        filters["custom_integration_status"] = (
            PIPELINE_STATUS_FIELDS[stage]
        )

    # Fields required by the drill-down panel.
    requested_fields = [
        "name",
        "lead_name",
        "company_name",
        "status",
        "custom_type_of_integration",
        "custom_ict_approval_status",
        "custom_daily_deliveries_nairobi_area",
        "custom_expected_monthly_deliveries",
    ]

    # Include only fields available on the Lead DocType.
    meta = frappe.get_meta("Lead")

    fields = [
        fieldname
        for fieldname in requested_fields
        if fieldname == "name" or meta.has_field(fieldname)
    ]

    # Fetch one extra record to determine whether another page exists.
    leads = frappe.get_list(
        "Lead",
        fields=fields,
        filters=filters,
        or_filters=or_filters,
        order_by="modified desc",
        limit_start=start,
        limit_page_length=page_length + 1,
    )

    has_more = len(leads) > page_length

    # Remove the extra record used for pagination detection.
    leads = leads[:page_length]

    return {
        "stage": stage,
        "records": leads,
        "pagination": {
            "start": start,
            "page_length": page_length,
            "returned_count": len(leads),
            "has_more": has_more,
            "next_start": (
                start + page_length if has_more else None
            ),
            "previous_start": (
                max(start - page_length, 0) if start > 0 else None
            ),
        },
        "record_scope": {
            "doctype": "Lead",
            "filter": "docstatus < 2",
            "permission_aware": True,
        },
    }
