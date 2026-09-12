from datetime import date

import frappe
from frappe.query_builder.custom import ConstantColumn
from frappe.utils import cint

from erpnext.accounts.doctype.bank_reconciliation_tool.bank_reconciliation_tool import (
    get_matching_queries as core_get_matching_queries,
    subtract_allocations,
)


@frappe.whitelist()
def get_linked_payments(
    bank_transaction_name: str,
    document_types: str | list[str] | None = None,
    from_date: str | date | None = None,
    to_date: str | date | None = None,
    filter_by_reference_date: bool | None = None,
    from_reference_date: bool | None = None,
    to_reference_date: str | None = None,
):
    """
    Custom Bank Reconciliation matching.

    Fix:
    Payment Entry amounts were being compared/returned using the
    wrong currency basis (source-account currency for comparison,
    company base currency for display) instead of the bank
    account's own currency, causing mismatched "Remaining" amounts
    in the reconciliation dialog. This override selects the
    amount/currency pair belonging to the bank account's side of
    the entry (paid_to for Receive, paid_from for Pay) consistently
    for both filtering and the returned value.
    """

    # Normalize document_types
    if isinstance(document_types, str):
        try:
            document_types = frappe.parse_json(document_types)
        except Exception:
            document_types = [document_types]

    document_types = document_types or []

    transaction = frappe.get_doc("Bank Transaction", bank_transaction_name)

    bank_account = frappe.db.get_value(
        "Bank Account",
        transaction.bank_account,
        ["account", "company"],
        as_dict=True,
    )

    gl_account = bank_account.account
    company = bank_account.company

    exact_match = "exact_match" in document_types

    common_filters = frappe._dict(
        {
            "amount": transaction.unallocated_amount,
            "payment_type": (
                "Receive"
                if transaction.deposit > 0.0
                else "Pay"
            ),
            "reference_no": transaction.reference_number,
            "party_type": transaction.party_type,
            "party": transaction.party,
            "bank_account": gl_account,
        }
    )

    queries = []

    # ---------------------------------------------------------
    # Keep ERPNext's standard matching for everything except
    # Payment Entry.
    # ---------------------------------------------------------

    other_document_types = [
        dt for dt in document_types
        if dt != "payment_entry"
    ]

    if other_document_types:
        # account_from_to is required by the core function to know
        # which side of Payment Entry / GL matching to filter on.
        # This was previously omitted, which shifted every
        # subsequent positional argument by one slot and silently
        # dropped common_filters -> None, causing:
        #   AttributeError: 'NoneType' object has no attribute 'bank_account'
        # inside get_je_matching_query / get_pi_matching_query /
        # get_si_matching_query. Passing everything as keyword
        # arguments here makes this class of bug impossible to
        # reintroduce silently.
        account_from_to = (
            "paid_to"
            if transaction.deposit > 0.0
            else "paid_from"
        )

        queries.extend(
            core_get_matching_queries(
                bank_account=gl_account,
                company=company,
                transaction=transaction,
                document_types=other_document_types,
                exact_match=exact_match,
                account_from_to=account_from_to,
                from_date=from_date,
                to_date=to_date,
                filter_by_reference_date=filter_by_reference_date,
                from_reference_date=from_reference_date,
                to_reference_date=to_reference_date,
                common_filters=common_filters,
            )
        )

    # ---------------------------------------------------------
    # Custom Payment Entry matching
    # ---------------------------------------------------------

    if "payment_entry" in document_types:
        queries.append(
            get_currency_aware_pe_matching_query(
                exact_match=exact_match,
                transaction=transaction,
                from_date=from_date,
                to_date=to_date,
                filter_by_reference_date=filter_by_reference_date,
                from_reference_date=from_reference_date,
                to_reference_date=to_reference_date,
                common_filters=common_filters,
            )
        )

    # ---------------------------------------------------------
    # Run all queries
    # ---------------------------------------------------------

    matching_vouchers = []

    for query in queries:
        matching_vouchers.extend(
            query.run(as_dict=True)
        )

    if matching_vouchers:
        matching_vouchers = sorted(
            matching_vouchers,
            key=lambda x: x["rank"],
            reverse=True,
        )

    # Subtract amounts already allocated to other
    # Bank Transactions.
    return subtract_allocations(
        gl_account,
        matching_vouchers,
    )


def get_currency_aware_pe_matching_query(
    exact_match,
    transaction,
    from_date,
    to_date,
    filter_by_reference_date,
    from_reference_date,
    to_reference_date,
    common_filters,
):
    """
    Payment Entry matching using the amount in the
    bank account currency.

    Pay:
        paid_amount_after_tax
        paid_from_account_currency

    Receive:
        received_amount_after_tax
        paid_to_account_currency
    """

    is_receive = transaction.deposit > 0.0

    account_from_to = (
        "paid_to"
        if is_receive
        else "paid_from"
    )

    payment_type = (
        "Receive"
        if is_receive
        else "Pay"
    )

    # IMPORTANT:
    # Use the amount belonging to the bank account currency.
    amount_field = (
        "received_amount_after_tax"
        if is_receive
        else "paid_amount_after_tax"
    )

    currency_field = (
        "paid_to_account_currency"
        if is_receive
        else "paid_from_account_currency"
    )

    pe = frappe.qb.DocType("Payment Entry")

    ref_condition = (
        pe.reference_no == transaction.reference_number
    )

    ref_rank = (
        frappe.qb.terms.Case()
        .when(ref_condition, 1)
        .else_(0)
    )

    # Compare bank transaction amount against the
    # Payment Entry amount in the SAME currency.
    pe_amount = getattr(pe, amount_field)

    amount_equality = (
        pe_amount == transaction.unallocated_amount
    )

    amount_rank = (
        frappe.qb.terms.Case()
        .when(amount_equality, 1)
        .else_(0)
    )

    amount_condition = (
        amount_equality
        if exact_match
        else pe_amount > 0.0
    )

    party_condition = (
        (pe.party_type == transaction.party_type)
        & (pe.party == transaction.party)
        & pe.party.isnotnull()
    )

    party_rank = (
        frappe.qb.terms.Case()
        .when(party_condition, 1)
        .else_(0)
    )

    filter_by_date = pe.posting_date.between(
        from_date,
        to_date,
    )

    if cint(filter_by_reference_date):
        filter_by_date = pe.reference_date.between(
            from_reference_date,
            to_reference_date,
        )

    query = (
        frappe.qb.from_(pe)
        .select(
            (
                ref_rank
                + amount_rank
                + party_rank
                + 1
            ).as_("rank"),

            ConstantColumn("Payment Entry").as_(
                "doctype"
            ),

            pe.name,

            # THIS IS THE IMPORTANT FIX
            pe_amount.as_("paid_amount"),

            pe.reference_no,
            pe.reference_date,
            pe.party,
            pe.party_type,
            pe.posting_date,

            # Currency belonging to the bank account
            getattr(pe, currency_field).as_("currency"),
        )
        .where(pe.docstatus == 1)
        .where(
            pe.payment_type.isin(
                [payment_type, "Internal Transfer"]
            )
        )
        .where(pe.clearance_date.isnull())

        # Bank account must be the account being reconciled
        .where(
            getattr(pe, account_from_to)
            == common_filters.bank_account
        )

        .where(amount_condition)
        .where(filter_by_date)
        .orderby(
            pe.reference_date
            if cint(filter_by_reference_date)
            else pe.posting_date
        )
    )

    # Preserve ERPNext's auto-reconciliation behaviour.
    if frappe.flags.auto_reconcile_vouchers is True:
        query = query.where(ref_condition)

    return query
