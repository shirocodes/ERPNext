import frappe

from frappe.query_builder import DocType
from frappe.query_builder.terms import Criterion
from erpnext.controllers.queries import build_qb_match_conditions


APPROVED_PURCHASE_INVOICE_ACCOUNT_TYPES = [
    "Expense",
    "Expense Account",
    "Cost of Sales",
    "Fixed Asset",
    "Intangible Asset",
    "Other Asset",
    "Prepaid Expense",
    "Accrued Expense",
    "Accrued Income",
    "Accumulated Depreciation",
    "Bank",
    "Contra Asset",
    "Contra Revenue",
    "Deferred Revenue",
    "Equity",
    "Gain/(Loss)",
    "Inventory",
    "Investment",
    "Long-term Liability",
    "Payroll Liabilities",
    "Provision",
    "Receivable",
    "Revenue",
    "Short-term Liability",
    "Tax",
    "Tax Payable",
]


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_purchase_invoice_expense_account(
    doctype, txt, searchfield, start, page_len, filters
):
    if not filters:
        filters = {}

    dt = "Account"
    acc = DocType(dt)

    condition = [
        acc.account_type.isin(APPROVED_PURCHASE_INVOICE_ACCOUNT_TYPES),
        acc.is_group.eq(0),
        acc.disabled.eq(0),
    ]

    if txt:
        condition.append(acc.name.like(f"%{txt}%"))

    if filters.get("company"):
        condition.append(acc.company.eq(filters.get("company")))

    user_perms = build_qb_match_conditions(dt)
    condition.extend(user_perms)

    return (
        frappe.qb.from_(acc)
        .select(acc.name)
        .where(Criterion.all(condition))
        .run()
    )
