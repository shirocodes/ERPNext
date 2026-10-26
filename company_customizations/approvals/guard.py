
from contextlib import contextmanager
from contextvars import ContextVar

import frappe
from frappe import _


INTERNAL_DOCTYPES = {
    "Approval Policy",
    "Approval Request",
    "Approval Decision",
    "Approval Execution Log",
}

_execution_context = ContextVar(
    "approval_deletion_context",
    default=None,
)


def get_deletion_policy(doctype):
    if doctype in INTERNAL_DOCTYPES:
        return None

    policies = frappe.get_all(
        "Approval Policy",
        filters={
            "target_doctype": doctype,
            "operation": "Delete Document",
            "is_active": 1,
        },
        pluck="name",
        limit_page_length=2,
    )

    if len(policies) > 1:
        frappe.throw(
            _("Multiple active deletion policies for {0}").format(
                doctype
            )
        )

    return policies[0] if policies else None


@contextmanager
def authorized_deletion(
    request_name,
    doctype,
    docname,
    executor,
    policy_name,
):
    # Internal use only. Never expose through a whitelisted API.
    token = _execution_context.set({
        "request": request_name,
        "doctype": doctype,
        "docname": docname,
        "executor": executor,
        "policy": policy_name,
    })

    try:
        yield
    finally:
        _execution_context.reset(token)


def validate_deletion(doc, method=None):
    policy_name = get_deletion_policy(doc.doctype)

    if not policy_name:
        return

    context = _execution_context.get()

    if context:
        valid_context = (
            context["doctype"] == doc.doctype
            and context["docname"] == doc.name
            and context["executor"] == frappe.session.user
            and context["policy"] == policy_name
        )

        if valid_context:
            request = frappe.get_doc(
                "Approval Request",
                context["request"],
            )

            valid_request = (
                request.workflow_state == "Approved"
                and request.execution_status != "Completed"
                and request.assigned_approver == frappe.session.user
                and request.approval_policy == policy_name
                and request.reference_doctype == doc.doctype
                and request.reference_name == doc.name
                and request.operation == "Delete Document"
            )

            if valid_request:
                return

    frappe.throw(
        _(
            "Deletion of {0} {1} requires manager approval. "
            "Please create an Approval Request."
        ).format(
            frappe.bold(doc.doctype),
            frappe.bold(doc.name),
        ),
        frappe.PermissionError,
    )
