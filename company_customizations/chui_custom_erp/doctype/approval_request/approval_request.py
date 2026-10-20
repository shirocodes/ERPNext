# Copyright (c) 2026, Sammy and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document


class ApprovalRequest(Document):

    def on_trash(self):
            frappe.throw(
                    _("Approval Request records cannot be deleted."),
                    frappe.PermissionError
            )

    def before_insert(self):
        if not self._is_trusted_operation():
            frappe.throw(
                _("Approval Requests must be created using the approval service."),
                frappe.PermissionError
            )

    def validate(self):
        if not self._is_trusted_operation():
            frappe.throw(
                _("Approval Requests must be modified using the approval service."),
                frappe.PermissionError
            )

        self.validate_required_information()
        self.validate_status()

    def validate_required_information(self):
        if not self.approval_policy:
            frappe.throw(_("Approval Policy is required."))

        if not self.reference_doctype or not self.reference_name:
            frappe.throw(_("A target document is required."))

        if not self.requested_by:
            frappe.throw(_("Requester is required."))

        if not (self.reason or "").strip():
            frappe.throw(_("Request justification is required."))

    def validate_status(self):
        valid_states = {
            "Draft",
            "Pending Approval",
            "Approved",
            "Rejected",
            "Completed",
        }

        if self.workflow_state not in valid_states:
            frappe.throw(_("Invalid approval state."))

    @staticmethod
    def _is_trusted_operation():
        return bool(
            getattr(frappe.flags, "approval_service_operation", False)
        )
