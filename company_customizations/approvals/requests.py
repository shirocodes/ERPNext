
from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import now_datetime
from company_customizations.approvals.permissions import (
    can_access_request,
)


def get_request(request_name):
    user = current_user()

    doc = frappe.get_doc(
        "Approval Request", request_name
    )

    if not can_access_request(doc, user):
        frappe.throw(
            _("You are not authorized to view this request."),
            frappe.PermissionError
        )

    return doc

@contextmanager
def trusted_operation():
    previous = getattr(
        frappe.flags, "approval_service_operation", False
    )

    frappe.flags.approval_service_operation = True

    try:
        yield
    finally:
        frappe.flags.approval_service_operation = previous


def current_user():
    user = frappe.session.user

    if not user or user == "Guest":
        frappe.throw(
            _("Please sign in to perform this action."),
            frappe.PermissionError
        )

    return user


def get_policy(policy_name):
    policy = frappe.get_doc(
        "Approval Policy", policy_name
    )

    if policy.operation != "Delete Document":
        frappe.throw(_("Unsupported approval operation."))

    if not policy.is_active:
        frappe.throw(
            _("This approval policy is not active.")
        )

    return policy


def validate_target(policy, reference_name):
    doctype = policy.target_doctype

    if not frappe.db.exists(doctype, reference_name):
        frappe.throw(
            _("The target document does not exist.")
        )

    if not frappe.has_permission(
        doctype,
        "read",
        doc=reference_name
    ):
        frappe.throw(
            _("You cannot access the target document."),
            frappe.PermissionError
        )


def lock_request(request_name):
    rows = frappe.db.sql(
        """
        SELECT name
        FROM `tabApproval Request`
        WHERE name = %s
        FOR UPDATE
        """,
        (request_name,),
        as_dict=True
    )

    if not rows:
        frappe.throw(_("Approval Request not found."))

    return frappe.get_doc(
        "Approval Request", request_name
    )


def save_request(doc):
    with trusted_operation():
        doc.save(ignore_permissions=True)


def create_request(
    policy_name,
    reference_name,
    reason
):
    user = current_user()
    policy = get_policy(policy_name)

    reason = (reason or "").strip()

    if not reason:
        frappe.throw(_("Reason is required."))

    validate_target(policy, reference_name)

    doctype = policy.target_doctype

    # Reject duplicate unfinished requests.
    existing = frappe.get_all(
        "Approval Request",
        filters={
            "reference_doctype": doctype,
            "reference_name": reference_name,
            "operation": "Delete Document",
            "workflow_state": [
                "in",
                ["Draft", "Pending Approval", "Approved"]
            ],
        },
        pluck="name",
        limit_page_length=1
    )

    if existing:
        frappe.throw(
            _("An unfinished approval request already exists: {0}").format(
                existing[0]
            )
        )

    doc = frappe.get_doc({
        "doctype": "Approval Request",
        "approval_policy": policy.name,
        "reference_doctype": doctype,
        "reference_name": reference_name,
        "reference_label": reference_name,
        "operation": "Delete Document",
        "requested_by": user,
        "reason": reason,
        "workflow_state": "Draft",
        "review_cycle": 0,
        "execution_status": "Not Started",
    })

    with trusted_operation():
        doc.insert(ignore_permissions=True)

    return doc.name



def submit_request(request_name):
    user = current_user()
    doc = lock_request(request_name)

    if doc.requested_by != user:
        frappe.throw(
            _("Only the requester can submit this request."),
            frappe.PermissionError
        )

    if doc.workflow_state != "Draft":
        frappe.throw(
            _("Only draft requests can be submitted.")
        )

    policy = get_policy(doc.approval_policy)

    if (
        doc.reference_doctype != policy.target_doctype
        or doc.operation != policy.operation
    ):
        frappe.throw(
            _("The request does not match its policy.")
        )

    validate_target(policy, doc.reference_name)

    # Preserve the previous approver on resubmission.
    approver = doc.assigned_approver or policy.approver_user

    if not frappe.db.get_value(
        "User", approver, "enabled"
    ):
        frappe.throw(
            _("Configured approver is disabled.")
        )

    if approver == user:
        frappe.throw(
            _("You cannot approve your own request."),
            frappe.PermissionError
        )

    doc.assigned_approver = approver
    doc.review_cycle = (doc.review_cycle or 0) + 1
    doc.workflow_state = "Pending Approval"

    save_request(doc)

    return doc.name

def record_decision(doc, decision, comments, user):
    with trusted_operation():
        frappe.get_doc({
            "doctype": "Approval Decision",
            "approval_request": doc.name,
            "review_cycle": doc.review_cycle,
            "decision": decision,
            "decided_by": user,
            "decision_comments": comments,
            "decided_on": now_datetime(),
        }).insert(ignore_permissions=True)


def decide_request(
    request_name,
    decision,
    comments=None
):
    user = current_user()
    doc = lock_request(request_name)

    if doc.workflow_state != "Pending Approval":
        frappe.throw(
            _("This request is not pending approval.")
        )

    if doc.assigned_approver != user:
        frappe.throw(
            _("Only the assigned manager may decide this request."),
            frappe.PermissionError
        )

    if doc.requested_by == user:
        frappe.throw(
            _("Self-approval is not permitted."),
            frappe.PermissionError
        )

    if decision not in ("Approved", "Rejected"):
        frappe.throw(_("Invalid decision."))

    comments = (comments or "").strip()

    if decision == "Rejected" and not comments:
        frappe.throw(_("Rejection comments are required."))

    record_decision(doc, decision, comments, user)

    doc.workflow_state = decision
    save_request(doc)

    return doc.name


def revise_request(request_name, new_reason):
    user = current_user()
    doc = lock_request(request_name)

    if doc.requested_by != user:
        frappe.throw(
            _("Only the requester can revise this request."),
            frappe.PermissionError
        )

    if doc.workflow_state != "Rejected":
        frappe.throw(
            _("Only rejected requests can be revised.")
        )

    policy = get_policy(doc.approval_policy)

    if not policy.allow_resubmission:
        frappe.throw(
            _("This policy does not allow resubmission.")
        )

    new_reason = (new_reason or "").strip()

    if not new_reason:
        frappe.throw(_("A revised reason is required."))

    doc.reason = new_reason
    doc.workflow_state = "Draft"
    #doc.assigned_approver = None

    save_request(doc)

    return doc.name
