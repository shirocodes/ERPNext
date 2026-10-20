from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from company_customizations.approvals import executor


MODULE = "company_customizations.approvals.executor"


class TestDeletionExecutor(FrappeTestCase):

    def setUp(self):
        super().setUp()

        self.manager = "manager@example.com"
        self.requester = "requester@example.com"

        self.request = SimpleNamespace(
            name="APR-TEST-00001",
            workflow_state="Approved",
            execution_status="Not Started",
            assigned_approver=self.manager,
            requested_by=self.requester,
            operation="Delete Document",
            approval_policy="TEST-POLICY",
            reference_doctype="Lead",
            reference_name="TEST-LEAD-001",
            executed_by=None,
            executed_on=None,
                        review_cycle=1
        )

        self.patches = [
            patch(
                f"{MODULE}.current_user",
                return_value=self.manager,
            ),
            patch(
                f"{MODULE}.lock_request",
                return_value=self.request,
            ),
            patch(
                f"{MODULE}.get_deletion_policy",
                return_value="TEST-POLICY",
            ),
            patch(
                f"{MODULE}.frappe.db.exists",
                return_value=True,
            ),
            patch(
                f"{MODULE}.frappe.has_permission",
                return_value=True,
            ),
            patch(
                f"{MODULE}.frappe.delete_doc",
            ),
            patch(
                f"{MODULE}.save_request",
            ),
            patch(
                f"{MODULE}.frappe.get_doc",
            ),
        ]

        self.mocks = [
            patcher.start()
            for patcher in self.patches
        ]

        for patcher in self.patches:
            self.addCleanup(patcher.stop)

        (
            self.mock_user,
            self.mock_lock,
            self.mock_policy,
            self.mock_exists,
            self.mock_permission,
            self.mock_delete,
            self.mock_save,
            self.mock_get_doc,
        ) = self.mocks

        self.mock_log = MagicMock()
        self.mock_get_doc.return_value = self.mock_log

    def execute(self):
        return executor.execute_approved_deletion(
            self.request.name
        )

    def assert_no_deletion(self):
        self.mock_delete.assert_not_called()
        self.mock_save.assert_not_called()
        self.mock_get_doc.assert_not_called()

    def test_manager_executes_approved_deletion(self):
        result = self.execute()

        self.assertEqual(result["status"], "Completed")
        self.assertEqual(
            self.request.workflow_state,
            "Completed",
        )
        self.assertEqual(
            self.request.execution_status,
            "Completed",
        )
        self.assertEqual(
            self.request.executed_by,
            self.manager,
        )

        self.mock_delete.assert_called_once_with(
            "Lead",
            "TEST-LEAD-001",
        )
        self.mock_save.assert_called_once_with(
            self.request
        )
        self.mock_log.insert.assert_called_once_with(
            ignore_permissions=True
        )

    def test_pending_request_blocked(self):
        self.request.workflow_state = "Pending Approval"

        with self.assertRaises(frappe.ValidationError):
            self.execute()

        self.assert_no_deletion()

    def test_rejected_request_blocked(self):
        self.request.workflow_state = "Rejected"

        with self.assertRaises(frappe.ValidationError):
            self.execute()

        self.assert_no_deletion()

    def test_unassigned_manager_blocked(self):
        self.request.assigned_approver = "other@example.com"

        with self.assertRaises(frappe.PermissionError):
            self.execute()

        self.assert_no_deletion()

    def test_self_approval_blocked(self):
        self.request.requested_by = self.manager

        with self.assertRaises(frappe.PermissionError):
            self.execute()

        self.assert_no_deletion()

    def test_completed_request_blocked(self):
        self.request.execution_status = "Completed"

        with self.assertRaises(frappe.ValidationError):
            self.execute()

        self.assert_no_deletion()

    def test_inactive_policy_blocked(self):
        self.mock_policy.return_value = None

        with self.assertRaises(frappe.ValidationError):
            self.execute()

        self.assert_no_deletion()


    def test_missing_target_blocked(self):

        def check_exists(doctype, name):
                if doctype == "Approval Decision":
                        return "TEST-DECISION-001"

                if doctype == "Lead":
                        return None

                return True

        self.mock_exists.side_effect = check_exists

        with self.assertRaises(frappe.ValidationError):
                self.execute()

        self.assert_no_deletion()

    def test_manager_without_delete_permission(self):
        self.mock_permission.return_value = False

        with self.assertRaises(frappe.PermissionError):
            self.execute()

        self.assert_no_deletion()

    def test_deletion_failure_does_not_complete(self):
        self.mock_delete.side_effect = frappe.ValidationError(
            "Document is linked to another record"
        )

        with self.assertRaises(frappe.ValidationError):
            self.execute()

        self.assertEqual(
            self.request.workflow_state,
            "Approved",
        )
        self.assertEqual(
            self.request.execution_status,
            "Not Started",
        )

        self.mock_save.assert_not_called()
        self.mock_get_doc.assert_not_called()

    def test_exact_target_authorization(self):
        captured = {}

        from contextlib import contextmanager

        @contextmanager
        def capture_authorization(**kwargs):
            captured.update(kwargs)
            yield

        with patch(
            f"{MODULE}.authorized_deletion",
            side_effect=capture_authorization,
        ):
            self.execute()

        self.assertEqual(
            captured["request_name"],
            self.request.name,
        )
        self.assertEqual(
            captured["doctype"],
            "Lead",
        )
        self.assertEqual(
            captured["docname"],
            "TEST-LEAD-001",
        )
        self.assertEqual(
            captured["executor"],
            self.manager,
        )
        self.assertEqual(
            captured["policy_name"],
            "TEST-POLICY",
        )

    def test_missing_approval_decision_blocked(self):
        original_exists = self.mock_exists.return_value

        def check_exists(doctype, name):
                if doctype == "Approval Decision":
                        return None
                return original_exists

        self.mock_exists.side_effect = check_exists

        with self.assertRaises(frappe.PermissionError):
                self.execute()

        self.assert_no_deletion()

    def test_approval_decision_matches_manager(self):
        self.execute()

        self.mock_exists.assert_any_call(
                "Approval Decision",
                {
                        "approval_request": self.request.name,
                        "review_cycle": self.request.review_cycle,
                        "decision": "Approved",
                        "decided_by": self.manager,
                },
        )
