
from unittest.mock import patch
from types import SimpleNamespace

import frappe
from frappe.tests.utils import FrappeTestCase

from company_customizations.approvals.guard import (
    authorized_deletion,
    validate_deletion,
)


class TestDeletionGuard(FrappeTestCase):

    def setUp(self):
        super().setUp()

        self.doc = SimpleNamespace(
            doctype="Lead",
            name="TEST-LEAD-001",
        )

    @patch(
        "company_customizations.approvals.guard.get_deletion_policy",
        return_value=None,
    )
    def test_unprotected_document_allowed(self, mock_policy):
        validate_deletion(self.doc)

    @patch(
        "company_customizations.approvals.guard.get_deletion_policy",
        return_value="TEST-POLICY",
    )
    def test_protected_document_blocked(self, mock_policy):
        with self.assertRaises(frappe.PermissionError):
            validate_deletion(self.doc)

    @patch(
        "company_customizations.approvals.guard.get_deletion_policy",
        return_value="TEST-POLICY",
    )
    def test_wrong_document_blocked(self, mock_policy):
        with authorized_deletion(
            request_name="APR-TEST-001",
            doctype="Lead",
            docname="OTHER-LEAD",
            executor=frappe.session.user,
            policy_name="TEST-POLICY",
        ):
            with self.assertRaises(frappe.PermissionError):
                validate_deletion(self.doc)

    @patch(
        "company_customizations.approvals.guard.get_deletion_policy",
        return_value="TEST-POLICY",
    )
    def test_wrong_executor_blocked(self, mock_policy):
        with authorized_deletion(
            request_name="APR-TEST-001",
            doctype="Lead",
            docname=self.doc.name,
            executor="another-user@example.com",
            policy_name="TEST-POLICY",
        ):
            with self.assertRaises(frappe.PermissionError):
                validate_deletion(self.doc)

    @patch(
        "company_customizations.approvals.guard.get_deletion_policy",
        return_value="TEST-POLICY",
    )
    @patch(
        "company_customizations.approvals.guard.frappe.get_doc"
    )
    def test_approved_request_allows_exact_document(
        self,
        mock_get_doc,
        mock_policy,
    ):
        user = frappe.session.user

        mock_get_doc.return_value = SimpleNamespace(
            workflow_state="Approved",
            execution_status="Not Started",
            assigned_approver=user,
            approval_policy="TEST-POLICY",
            reference_doctype="Lead",
            reference_name=self.doc.name,
            operation="Delete Document",
        )

        with authorized_deletion(
            request_name="APR-TEST-001",
            doctype=self.doc.doctype,
            docname=self.doc.name,
            executor=user,
            policy_name="TEST-POLICY",
        ):
            validate_deletion(self.doc)

    @patch(
        "company_customizations.approvals.guard.get_deletion_policy",
        return_value="TEST-POLICY",
    )
    def test_authorization_context_is_cleared(self, mock_policy):
        with authorized_deletion(
            request_name="APR-TEST-001",
            doctype=self.doc.doctype,
            docname=self.doc.name,
            executor=frappe.session.user,
            policy_name="TEST-POLICY",
        ):
            pass

        with self.assertRaises(frappe.PermissionError):
            validate_deletion(self.doc)

