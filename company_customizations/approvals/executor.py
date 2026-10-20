import frappe
from frappe import _
from frappe.utils import now_datetime

from company_customizations.approvals.guard import (
    authorized_deletion,
    get_deletion_policy,
)
from company_customizations.approvals.requests import (
    current_user,
    lock_request,
    save_request,
        trusted_operation
)


def execute_approved_deletion(request_name):
    manager = current_user()

    # Locks this request until the current transaction completes.
    request = lock_request(request_name)

    if request.workflow_state != "Approved":
        frappe.throw(
            _("Only approved requests can be executed.")
        )

    if request.execution_status == "Completed":
        frappe.throw(
            _("This request has already been executed.")
        )

    if request.assigned_approver != manager:
        frappe.throw(
            _("Only the assigned manager can execute deletion."),
            frappe.PermissionError,
        )

    if request.requested_by == manager:
        frappe.throw(
            _("Self-approval is not permitted."),
            frappe.PermissionError,
        )

    decision_exists = frappe.db.exists(
            "Approval Decision",
            {
                    "approval_request": request.name,
                    "review_cycle": request.review_cycle,
                    "decision": "Approved",
                    "decided_by": manager,
            },
    )

    if not decision_exists:
            frappe.throw(
                    _("No valid manager approval decision exists for this request."),
                    frappe.PermissionError,
            )

    if request.operation != "Delete Document":
        frappe.throw(_("Unsupported approval operation."))

    doctype = request.reference_doctype
    docname = request.reference_name

    policy_name = get_deletion_policy(doctype)

    if not policy_name or policy_name != request.approval_policy:
        frappe.throw(
            _("The original deletion policy is no longer active.")
        )

    if not frappe.db.exists(doctype, docname):
        frappe.throw(
            _("The target document no longer exists.")
        )
    # MVP: manager must also have ordinary Delete permission.
    if not frappe.has_permission(
        doctype,
        ptype="delete",
        doc=docname,
        user=manager,
    ):
        frappe.throw(
            _("You do not have Delete permission for this document."),
            frappe.PermissionError,
        )

    with authorized_deletion(
        request_name=request.name,
        doctype=doctype,
        docname=docname,
        executor=manager,
        policy_name=policy_name,
    ):
        # Normal Frappe deletion:
        # no ignore_permissions, force or raw SQL.
        frappe.delete_doc(doctype, docname)

    request.workflow_state = "Completed"
    request.execution_status = "Completed"
    request.executed_by = manager
    request.executed_on = now_datetime()

    save_request(request)

    with trusted_operation():
        frappe.get_doc({
                "doctype": "Approval Execution Log",
                "approval_request": request.name,
                "operation": "Delete Document",
                "executed_by": manager,
                "execution_time": now_datetime(),
                "status": "Success",
                "target_doctype": doctype,
                "target_name": docname,
        }).insert(ignore_permissions=True)

    return {
        "request": request.name,
        "status": "Completed",
        "deleted_doctype": doctype,
        "deleted_document": docname,
    }
