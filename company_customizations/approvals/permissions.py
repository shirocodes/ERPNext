
import frappe


def is_approval_admin(user):
    return "Approval Administrator" in frappe.get_roles(user)


def can_access_request(doc, user):
    if not user or user == "Guest":
        return False

    if is_approval_admin(user):
        return True

    return user in (
        doc.requested_by,
        doc.assigned_approver,
    )


def has_approval_request_permission(
    doc, user=None, permission_type=None
):
    user = user or frappe.session.user

    if permission_type not in ("read", "select"):
        # Lifecycle modifications go through controlled APIs.
        if permission_type in (
            "write", "delete", "submit", "cancel"
        ):
            return False

        return None

    return can_access_request(doc, user)


def approval_request_query_conditions(user=None):
    user = user or frappe.session.user

    if not user or user == "Guest":
        return "1=0"

    if is_approval_admin(user):
        return None

    escaped_user = frappe.db.escape(user)

    return (
        f"(`tabApproval Request`.`requested_by` = {escaped_user}"
        f" OR `tabApproval Request`.`assigned_approver` = {escaped_user})"
    )
