import frappe

from company_customizations.approvals import requests
from company_customizations.approvals.executor import (
    execute_approved_deletion as execute_deletion_service,
)

@frappe.whitelist(methods=["POST"])
def create_request(policy_name, reference_name, reason):
    return requests.create_request(
        policy_name,
        reference_name,
        reason
    )


@frappe.whitelist(methods=["POST"])
def submit_request(request_name):
    return requests.submit_request(request_name)


@frappe.whitelist(methods=["POST"])
def approve_request(request_name, comments=None):
    return requests.decide_request(
        request_name,
        "Approved",
        comments
    )


@frappe.whitelist(methods=["POST"])
def reject_request(request_name, comments):
    return requests.decide_request(
        request_name,
        "Rejected",
        comments
    )


@frappe.whitelist(methods=["POST"])
def revise_request(request_name, new_reason):
    return requests.revise_request(
        request_name,
        new_reason
    )

@frappe.whitelist(methods=["POST"])
def execute_approved_deletion(request_name):
    return execute_deletion_service(request_name)


@frappe.whitelist(methods=["GET"])
def get_document_approval_context(doctype, docname):
    """
    Read-only context for actions displayed on document forms.
    Does not authorize an approval or execute an operation.
    """
    from company_customizations.approvals.guard import (
        get_deletion_policy,
    )

    if not doctype or not docname:
        frappe.throw(_("Document type and name are required."))

    if not frappe.db.exists(doctype, docname):
        frappe.throw(_("Document does not exist."))

    if not frappe.has_permission(
        doctype,
        ptype="read",
        doc=docname,
    ):
        frappe.throw(
            _("Not permitted to read this document."),
            frappe.PermissionError,
        )

    policy_name = get_deletion_policy(doctype)

    if not policy_name:
        return {
            "has_policy": False,
            "can_request": False,
        }

    policy = frappe.get_doc(
        "Approval Policy",
        policy_name,
    )

    user = frappe.session.user

    if (
        policy.operation != "Delete Document"
        or not policy.is_active
    ):
        return {
            "has_policy": False,
            "can_request": False,
        }

    # A manager cannot request approval from themselves.
    can_request = user != policy.approver_user

    # Find an existing request belonging to this requester.
    existing = frappe.get_all(
        "Approval Request",
        filters={
            "approval_policy": policy.name,
            "reference_doctype": doctype,
            "reference_name": docname,
            "requested_by": user,
            "workflow_state": [
                "in",
                ["Draft", "Pending Approval", "Approved"],
            ],
        },
        fields=["name", "workflow_state"],
        order_by="creation desc",
        limit_page_length=1,
    )

    current_request = existing[0] if existing else None

    if current_request:
        can_request = False

    # Latest approval request visible to this user.
    # Used to display the approval status in the form header.
    visible_requests = frappe.get_list(
            "Approval Request",
            filters={
                    "approval_policy": policy.name,
                    "reference_doctype": doctype,
                    "reference_name": docname,
                    "operation": "Delete Document",
            },
            fields=[
                    "name",
                    "workflow_state",
                    "requested_by",
                    "assigned_approver",
                    "creation",
            ],
            order_by="creation desc",
            limit_page_length=1,
    )

    latest_request = (
            visible_requests[0]
            if visible_requests
            else None
    )

    approval_status = (
            latest_request.workflow_state
            if latest_request
            else None
    )

    return {
            "has_policy": True,
            "policy_name": policy.name,
            "operation": policy.operation,
            "require_reason": bool(policy.require_reason),
            "can_request": can_request,
            "current_request": current_request,
            "approval_status": approval_status,
    }
