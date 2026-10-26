# Copyright (c) 2026, Sammy and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document


class ApprovalDecision(Document):

    def before_insert(self):
        if not getattr(
            frappe.flags, "approval_service_operation", False
        ):
            frappe.throw(
                _("Decisions must be created through the approval service."),
                frappe.PermissionError
            )

    def validate(self):
        if not getattr(
            frappe.flags, "approval_service_operation", False
        ):
            frappe.throw(
                _("Unauthorized decision operation."),
                frappe.PermissionError
            )

        if self.decision not in ("Approved", "Rejected"):
            frappe.throw(_("Invalid approval decision."))

        if self.decision == "Rejected" and not (
            self.decision_comments or ""
        ).strip():
            frappe.throw(_("Rejection comments are required."))

        if not self.is_new():
            frappe.throw(
                _("Approval decisions cannot be modified.")
            )

    def on_trash(self):
        frappe.throw(
            _("Approval decision history cannot be deleted."),
            frappe.PermissionError
        )
