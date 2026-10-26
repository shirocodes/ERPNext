from frappe.utils import now_datetime
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from company_customizations.approvals import executor, guard
from company_customizations.approvals.requests import trusted_operation
from company_customizations.chui_custom_erp.doctype.approval_execution_log.approval_execution_log import (
    ApprovalExecutionLog,
)


class TestApprovalIntegration(FrappeTestCase):

    def setUp(self):
        super().setUp()

        frappe.set_user("Administrator")
        self.manager = "Administrator"
        self.requester = "Guest"
        self.suffix = uuid4().hex[:10]

        # Create an inactive policy for a disposable DocType.
        self.policy = frappe.get_doc({
            "doctype": "Approval Policy",
            "policy_name": "Test Deletion " + self.suffix,
            "target_doctype": "ToDo",
            "operation": "Delete Document",
            "approver_user": self.manager,
            "is_active": 0,
            "require_reason": 1,
        }).insert(ignore_permissions=True)

        self.target = frappe.get_doc({
            "doctype": "ToDo",
            "description": "Approval integration test " + self.suffix,
        }).insert(ignore_permissions=True)

        with trusted_operation():
            self.request = frappe.get_doc({
                "doctype": "Approval Request",
                "approval_policy": self.policy.name,
                "reference_doctype": "ToDo",
                "reference_name": self.target.name,
                "reference_label": self.target.name,
                "operation": "Delete Document",
                "requested_by": self.requester,
                "assigned_approver": self.manager,
                "reason": "Disposable integration test",
                "workflow_state": "Approved",
                "review_cycle": 1,
                "execution_status": "Not Started",
            }).insert(ignore_permissions=True)

        with trusted_operation():
            self.decision = frappe.get_doc({
                    "doctype": "Approval Decision",
                    "approval_request": self.request.name,
                    "review_cycle": self.request.review_cycle,
                    "decision": "Approved",
                    "decided_by": self.manager,
                    "decision_comments": "Approved for integration testing",
                    "decided_on": now_datetime(),
            }).insert(ignore_permissions=True)

        # Simulate policy discovery without activating it.
        self.executor_policy = patch.object(
            executor,
            "get_deletion_policy",
            return_value=self.policy.name,
        )
        self.guard_policy = patch.object(
            guard,
            "get_deletion_policy",
            return_value=self.policy.name,
        )

        self.executor_policy.start()
        self.guard_policy.start()

        self.addCleanup(self.executor_policy.stop)
        self.addCleanup(self.guard_policy.stop)

    def test_successful_manager_deletion(self):
        result = executor.execute_approved_deletion(
            self.request.name
        )

        self.assertEqual(result["status"], "Completed")

        self.assertFalse(
            frappe.db.exists("ToDo", self.target.name)
        )

        self.request.reload()

        self.assertEqual(
            self.request.workflow_state,
            "Completed"
        )
        self.assertEqual(
            self.request.execution_status,
            "Completed"
        )

        logs = frappe.get_all(
            "Approval Execution Log",
            filters={
                "approval_request": self.request.name,
                "status": "Success",
            },
            fields=["name"],
        )

        self.assertEqual(len(logs), 1)

    def test_deletion_rollback_if_logging_fails(self):
        savepoint = "approval_execution_test"
        frappe.db.savepoint(savepoint)

        try:
            with patch.object(
                ApprovalExecutionLog,
                "insert",
                side_effect=frappe.ValidationError(
                    "Simulated execution log failure"
                ),
            ):
                executor.execute_approved_deletion(
                    self.request.name
                )

        except frappe.ValidationError:
            frappe.db.rollback(save_point=savepoint)
        else:
            self.fail("Expected the execution log to fail")

        # The target must still exist.
        self.assertTrue(
            frappe.db.exists("ToDo", self.target.name)
        )

        self.request.reload()

        self.assertEqual(
            self.request.workflow_state,
            "Approved"
        )
        self.assertEqual(
            self.request.execution_status,
            "Not Started"
        )

        successful_logs = frappe.db.count(
            "Approval Execution Log",
            {
                "approval_request": self.request.name,
                "status": "Success",
            },
        )

        self.assertEqual(successful_logs, 0)

    def test_unapproved_request_cannot_execute(self):
        with trusted_operation():
            self.request.workflow_state = "Pending Approval"
            self.request.save(ignore_permissions=True)

        with self.assertRaises(frappe.ValidationError):
            executor.execute_approved_deletion(
                self.request.name
            )

        self.assertTrue(
            frappe.db.exists("ToDo", self.target.name)
        )

    def test_ordinary_deletion_blocked(self):
        # Policy discovery is mocked as active.
        with self.assertRaises(frappe.PermissionError):
            frappe.delete_doc(
                "ToDo",
                self.target.name,
            )

        self.assertTrue(
            frappe.db.exists("ToDo", self.target.name)
        )

    def test_execution_blocked_without_manager_decision(self):
        # Deliberately simulate a missing decision by mocking
        # only the decision lookup, without deleting audit data.
        original_exists = frappe.db.exists

        def check_exists(doctype, name, *args, **kwargs):
                if doctype == "Approval Decision":
                        return None

                return original_exists(
                        doctype, name, *args, **kwargs
                )

        with patch.object(
                executor.frappe.db,
                "exists",
                side_effect=check_exists,
        ):
                with self.assertRaises(frappe.PermissionError):
                        executor.execute_approved_deletion(
                                self.request.name
                        )

        self.assertTrue(
                frappe.db.exists("ToDo", self.target.name)
        )

        self.request.reload()

        self.assertEqual(
                self.request.workflow_state,
                "Approved"
        )
