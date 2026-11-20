import frappe

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from frappe.integrations.utils import make_get_request

PAGE_SIZE = 50
PAID_STATUSES = {"PAID", "SUCCESS", "COMPLETED", "SUCCESSFUL"}
EAT = timezone(timedelta(hours=3))


# ---------------------------------------------------------------------------
# API Client
# ---------------------------------------------------------------------------

def api_get(path, params=None):
    config = frappe.get_site_config()

    base_url = config.get("backoffice_api_url")
    api_key = config.get("backoffice_api_key")

    if not base_url or not api_key:
        raise ValueError("Missing Backoffice API configuration")

    url = base_url.rstrip("/") + path

    if params:
        url += "?" + urlencode(params)

    return make_get_request(
        url,
        headers={
            "X-Api-Key": api_key,
            "Accept": "application/json",
        },
    )


# ---------------------------------------------------------------------------
# Extraction Window
# ---------------------------------------------------------------------------

def get_window(mode, start=None, end=None):
    now = datetime.now(EAT)

    if mode == "daily":
        start = now.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end = now

    elif mode in ("incremental", "backfill"):
        if not start or not end:
            raise ValueError("Start and end dates are required")

    elif mode == "full":
        return {}

    else:
        raise ValueError(f"Invalid extraction mode: {mode}")

    start = datetime.fromisoformat(str(start))
    end = datetime.fromisoformat(str(end))

    if not start.tzinfo or not end.tzinfo:
        raise ValueError("Extraction dates must include a timezone")

    if start >= end:
        raise ValueError("Invalid extraction window")

    return {
        "createdAtFrom": start.astimezone(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%S"),

        "createdAtTo": end.astimezone(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%S"),
    }


# ---------------------------------------------------------------------------
# Parcel Discovery
# ---------------------------------------------------------------------------

def fetch_parcels(window):
    page = 0

    while True:
        params = {
            **window,
            "page": page,
            "size": PAGE_SIZE,
            "sort": "id,asc",
            "isOldRecordsIncluded": "true",
        }

        response = api_get("/parcel", params)

        if not isinstance(response, dict) or "content" not in response:
            raise ValueError("Invalid parcel listing response")

        items = response["content"]

        if not items:
            break

        yield from items

        page += 1
        total_pages = response.get("page", {}).get("totalPages")

        if total_pages is not None and page >= total_pages:
            break


# ---------------------------------------------------------------------------
# Payment and Service Extraction
# ---------------------------------------------------------------------------

def get_paid_send_payments(charges):
    return [
        payment
        for payment in charges.get("payments", [])
        if payment.get("paymentType") == "SEND"
        and (payment.get("status") or "").upper() in PAID_STATUSES
    ]


def get_send_services(charges):
    return [
        service
        for service in charges.get("services", [])
        if service.get("serviceType") == "SEND"
    ]


def extract_parcel(parcel_id):
    charges = api_get(f"/parcel/charges/{parcel_id}")

    if not isinstance(charges, dict) or "payments" not in charges:
        raise ValueError("Invalid charges response")

    payments = get_paid_send_payments(charges)

    if not payments:
        return None

    services = get_send_services(charges)
    parcel = api_get(f"/parcel/{parcel_id}")

    if len(services) != 1:
        raise ValueError("Expected exactly one SEND service")

    customer = extract_customer(parcel, services[0])

    if not isinstance(parcel, dict) or not parcel.get("id"):
        raise ValueError("Invalid parcel details")

    return {
        "parcel_id": parcel_id,
        "parcel": parcel,
        "customer": customer,
        "services": services,
        "payments": payments,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }

# 
# Customer Details Extraction
#
# ---------------------------------------------------------------------------
# Customer Extraction
# ---------------------------------------------------------------------------

def extract_customer(parcel, service):
    """Retrieve billing customer details from the CHUI backend."""

    customer_type = (service.get("payBy") or "").upper()
    customer_id = parcel.get("senderId")

    if not customer_id:
        raise ValueError("Missing sender ID")

    if customer_type == "C2C":
        data = api_get(f"/customer/{customer_id}")

    elif customer_type == "B2C":
        data = api_get(f"/company/{customer_id}")

    else:
        raise ValueError(f"Unsupported customer type: {customer_type}")

    if not isinstance(data, dict) or not data.get("id"):
        raise ValueError(f"Invalid customer response: {customer_id}")

    if str(data["id"]) != str(customer_id):
        raise ValueError("Customer ID mismatch")

    invoice_data = data.get("invoiceData") or {}

    full_name = " ".join(
        name for name in [
            data.get("givenName"),
            data.get("surname"),
        ] if name
    )

    return {
        "customer_id": data["id"],
        "customer_type": customer_type,
        "customer_name": data.get("companyName") or full_name,
        "email": data.get("email"),
        "phone": data.get("phoneNumber"),
        "country": data.get("country"),
        "status": data.get("status"),
        "kra_pin": invoice_data.get("taxNumber"),
        "invoice_email": (
            invoice_data.get("invoiceEmail") or data.get("email")
        ),
        "invoice_address": invoice_data.get("invoiceAddress") or {},
        "registration_number": invoice_data.get("regNumber"),
        "invoicing_frequency": invoice_data.get("invoicingFrequency"),
        "is_postpaid": data.get("isPostPaid", False),
    }

# ---------------------------------------------------------------------------
# Extraction Pipeline
# ---------------------------------------------------------------------------

def run_extraction(mode="daily", start=None, end=None):
    window = get_window(mode, start, end)

    result = {
        "mode": mode,
        "window": window,
        "discovered": 0,
        "extracted": [],
        "pending": [],
        "failed": [],
        "discovery_error": None,
    }

    seen = set()

    try:
        for item in fetch_parcels(window):
            parcel_id = item.get("id")

            if not parcel_id:
                raise ValueError("Parcel listing contains a missing ID")

            if parcel_id in seen:
                continue

            seen.add(parcel_id)
            result["discovered"] += 1

            try:
                record = extract_parcel(parcel_id)

                if record is None:
                    result["pending"].append(parcel_id)
                else:
                    result["extracted"].append(record)

            except Exception as exc:
                result["failed"].append({
                    "parcel_id": parcel_id,
                    "error": str(exc),
                })

    except Exception as exc:
        result["discovery_error"] = str(exc)

    result["summary"] = {
        "discovered": result["discovered"],
        "extracted": len(result["extracted"]),
        "pending": len(result["pending"]),
        "failed": len(result["failed"]),
        "complete": (
            not result["failed"]
            and not result["discovery_error"]
        ),
    }

    return result