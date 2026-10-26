# Copyright (c) 2026, Sammy and contributors
# For license information, please see license.txt

# import frappe

import frappe
from frappe import _
from frappe.model.document import Document


SUPPORTED_OPERATIONS = {"Delete Document"}

PROTECTED_DOCTYPES = {
    "Approval Policy",
    "Approval Request",
    "Approval Decision",
    "Approval Execution Log",
}

# Stage 1B: Disable activation until the deletion guard is ready.
APPROVAL_ENGINE_READY = True


class ApprovalPolicy(Document):

    def validate(self):
        self.validate_operation()
        self.validate_target_doctype()
        self.validate_approver()
        self.validate_unique_active_policy()
        self.validate_activation()

    def validate_operation(self):
        if self.operation not in SUPPORTED_OPERATIONS:
            frappe.throw(
                _("Unsupported approval operation: {0}").format(
                    frappe.bold(self.operation)
                )
            )

    def validate_target_doctype(self):
        if self.target_doctype in PROTECTED_DOCTYPES:
            frappe.throw(
                _("Approval policies cannot target internal approval records.")
            )

        if not frappe.db.exists("DocType", self.target_doctype):
            frappe.throw(_("The selected DocType does not exist."))

        meta = frappe.get_meta(self.target_doctype)

        if meta.issingle or meta.istable:
            frappe.throw(
                _("Child Table and Single DocTypes are not supported.")
            )

        if meta.is_virtual:
            frappe.throw(
                _("Virtual DocTypes are not supported.")
            )

    def validate_approver(self):
        enabled = frappe.db.get_value(
            "User",
            self.approver_user,
            "enabled"
        )

        if not enabled:
            frappe.throw(
                _("The assigned approver must be an enabled ERPNext user.")
            )

        if self.approver_user == "Guest":
            frappe.throw(_("Guest cannot be an approver."))

    def validate_unique_active_policy(self):
        if not self.is_active:
            return

        filters = {
            "target_doctype": self.target_doctype,
            "operation": self.operation,
            "is_active": 1,
        }

        existing = frappe.get_all(
            "Approval Policy",
            filters=filters,
            fields=["name"],
            limit_page_length=2
        )

        for policy in existing:
            if policy.name != self.name:
                frappe.throw(
                    _("An active approval policy already exists for {0}: {1}").format(
                        self.target_doctype,
                        policy.name
                    )
                )

    def validate_activation(self):
        if self.is_active and not APPROVAL_ENGINE_READY:
            frappe.throw(
                _("Approval policy activation is disabled until "
                  "the deletion enforcement engine is implemented.")
            )

