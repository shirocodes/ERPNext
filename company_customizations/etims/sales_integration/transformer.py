from decimal import Decimal, ROUND_HALF_UP


PAID_STATUSES = {"PAID", "SUCCESS", "COMPLETED", "SUCCESSFUL"}
CUSTOMER_TYPES = {"C2C", "B2C"}
PRECISION = Decimal("0.01")
AMOUNT_TOLERANCE = Decimal("0.01")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

class ValidationError(ValueError):
    pass


def money(value):
    """Normalize monetary values to two decimal places."""

    if value is None:
        raise ValidationError("Missing monetary value")

    amount = Decimal(str(value))

    if not amount.is_finite():
        raise ValidationError("Invalid monetary value")

    return amount.quantize(PRECISION, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Customer Validation
# ---------------------------------------------------------------------------

def validate_customer(customer, service):
    customer_type = customer.get("customer_type")

    if customer_type not in CUSTOMER_TYPES:
        raise ValidationError("Unsupported customer type")

    if customer_type != service.get("payBy"):
        raise ValidationError("Customer category mismatch")

    if not customer.get("customer_id"):
        raise ValidationError("Missing customer ID")

    if not customer.get("customer_name"):
        raise ValidationError("Missing customer name")

    return {
        **customer,
        "external_customer_id": (
            f"{customer_type}:{customer['customer_id']}"
        ),
        "kra_pin": customer.get("kra_pin") or None,
    }


# ---------------------------------------------------------------------------
# Payment Validation
# ---------------------------------------------------------------------------

def validate_payment(payment):
    if payment.get("paymentType") != "SEND":
        raise ValidationError("Unsupported payment type")

    if payment.get("payType") != "PAYMENT":
        raise ValidationError("Not a sale payment")

    if payment.get("status") not in PAID_STATUSES:
        raise ValidationError("Payment not confirmed")

    transaction_id = payment.get("mpesaTransactionId")

    if not transaction_id:
        raise ValidationError("Missing transaction reference")

    if money(payment.get("amount")) <= 0:
        raise ValidationError("Invalid payment amount")

    return transaction_id


# ---------------------------------------------------------------------------
# Financial Validation
# ---------------------------------------------------------------------------

def validate_amounts(service, payment):
    service_currency = service.get("currency")
    payment_currency = payment.get("currency")

    if service_currency != payment_currency:
        raise ValidationError("Service and payment currency mismatch")

    if service_currency != "KES":
        raise ValidationError("Unsupported currency")

    gross = money(payment.get("amount"))
    source_gross = money(service.get("grossPrice"))

    if abs(gross - source_gross) > AMOUNT_TOLERANCE:
        raise ValidationError("Payment and service amount mismatch")

    vat_rate = Decimal(str(service["vat"]))

    if not vat_rate.is_finite() or not 0 <= vat_rate <= 100:
        raise ValidationError("Invalid VAT rate")

    net = money(gross / (1 + vat_rate / 100))
    vat_amount = money(gross - net)

    if abs(net - money(service.get("netPrice"))) > AMOUNT_TOLERANCE:
        raise ValidationError("Service net amount mismatch")

    return {
        "currency": service_currency,
        "gross_amount": str(gross),
        "net_amount": str(net),
        "vat_rate": str(vat_rate),
        "vat_amount": str(vat_amount),
    }


# ---------------------------------------------------------------------------
# Transaction Transformation
# ---------------------------------------------------------------------------

def transform_transaction(record):
    parcel = record["parcel"]
    services = record["services"]
    payments = record["payments"]

    if str(record["parcel_id"]) != str(parcel.get("id")):
        raise ValidationError("Parcel ID mismatch")

    if parcel.get("isDeleted"):
        raise ValidationError("Deleted parcel")

    if len(services) != 1:
        raise ValidationError("Expected exactly one SEND service")

    if len(payments) != 1:
        raise ValidationError("Expected exactly one paid SEND payment")

    service = services[0]
    payment = payments[0]

    if service.get("serviceType") != "SEND":
        raise ValidationError("Unsupported service type")

    if service.get("isDeleted"):
        raise ValidationError("Deleted service")

    if service.get("invoicedAt"):
        raise ValidationError("Service already marked as invoiced; review required")

    customer = validate_customer(record["customer"], service)
    transaction_id = validate_payment(payment)
    amounts = validate_amounts(service, payment)

    parcel_id = record["parcel_id"]

    return {
        "parcel_id": parcel_id,
        "parcel_number": parcel.get("parcelNumber"),
        "transaction_id": transaction_id,
        "idempotency_key": f"{parcel_id}:{transaction_id}",

        "customer": customer,
        "service_type": "SEND",
        "payment_channel": payment.get("paymentChannel"),
        "payment_status": "PAID",
        "payment_date": payment.get("mpesaTransactionDate"),

        "is_postpaid": parcel.get("isPostPaid", False),

        **amounts,

        "validation_status": "Validated",
        "extracted_at": record.get("extracted_at"),
    }


# ---------------------------------------------------------------------------
# Batch Transformation
# ---------------------------------------------------------------------------

def run_transformation(records):
    result = {
        "validated": [],
        "rejected": [],
    }

    seen = set()

    for record in records:
        try:
            transaction = transform_transaction(record)
            key = transaction["idempotency_key"]

            if key in seen:
                raise ValidationError("Duplicate transaction in batch")

            seen.add(key)
            result["validated"].append(transaction)

        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            result["rejected"].append({
                "parcel_id": record.get("parcel_id"),
                "reason": str(exc),
            })

    result["summary"] = {
        "received": len(records),
        "validated": len(result["validated"]),
        "rejected": len(result["rejected"]),
    }

    return result