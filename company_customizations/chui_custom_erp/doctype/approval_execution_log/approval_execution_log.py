
import frappe
from frappe import _
from frappe.model.document import Document


class ApprovalExecutionLog(Document):

    def before_insert(self):
        if not getattr(
            frappe.flags, "approval_service_operation", False
        ):
            frappe.throw(
                _("Execution logs must be created by the approval service."),
                frappe.PermissionError,
            )

    def validate(self):
        if not self.is_new():
            frappe.throw(
                _("Execution logs cannot be modified."),
                frappe.PermissionError,
            )

        if not getattr(
            frappe.flags, "approval_service_operation", False
        ):
            frappe.throw(
                _("Unauthorized execution log operation."),
                frappe.PermissionError,
            )

    def on_trash(self):
        frappe.throw(
            _("Execution logs cannot be deleted."),
            frappe.PermissionError,
        )

