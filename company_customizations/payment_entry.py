import frappe
from frappe.utils import flt

from erpnext.accounts.doctype.payment_entry.payment_entry import (
    get_payment_entry as core_get_payment_entry,
)


@frappe.whitelist()
def get_payment_entry(
    dt,
    dn,
    party_amount=None,
    bank_account=None,
    bank_amount=None,
    party_type=None,
    payment_type=None,
    reference_date=None,
    ignore_permissions=False,
    created_from_payment_request=False,
):
    # Let ERPNext core construct the Payment Entry first.
    pe = core_get_payment_entry(
        dt=dt,
        dn=dn,
        party_amount=party_amount,
        bank_account=bank_account,
        bank_amount=bank_amount,
        party_type=party_type,
        payment_type=payment_type,
        reference_date=reference_date,
        ignore_permissions=ignore_permissions,
        created_from_payment_request=created_from_payment_request,
    )

    # Narrow workaround for the v15 multicurrency fallback bug:
    #
    # Purchase/Sales Invoice is in a foreign currency, while the
    # party account is in company currency and no bank account was
    # supplied during Payment Entry creation.
    #
    # Core currently does:
    #     received_amount = paid_amount * doc.conversion_rate
    # followed by a Pay swap, which produces:
    #     paid_amount = outstanding * conversion_rate
    #
    # For Pay, the correct party amount is:
    #     outstanding / conversion_rate

    if dt in ("Purchase Invoice", "Sales Invoice") and pe.payment_type == "Pay":
       doc = frappe.get_doc(dt, dn)
       company_currency = frappe.get_cached_value("Company", doc.get("company"), "default_currency",)

       if (
            not bank_account
            and doc.get("currency") != company_currency
            and doc.get("party_account_currency") == company_currency
            and flt(doc.get("conversion_rate"))
            and flt(pe.received_amount)
            and flt(pe.paid_amount)
            == flt(pe.received_amount) * flt(doc.get("conversion_rate"))
        ):
            pe.paid_amount = flt(
                flt(pe.received_amount) / flt(doc.get("conversion_rate")),
                pe.precision("paid_amount"),
            )

    return pe
