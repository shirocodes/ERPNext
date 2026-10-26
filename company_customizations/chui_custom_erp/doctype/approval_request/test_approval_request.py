# Copyright (c) 2026, Sammy and Contributors
# See license.txt

# Copyright (c) 2026, Sammy and Contributors
# See license.txt


from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from company_customizations.approvals import requests


class TestApprovalRequest(FrappeTestCase):

    def setUp(self):
        super().setUp()

        # Existing development policy.
        self.policy = frappe.get_doc(
            "Approval Policy", "Test"
        )

        self.requester = "Administrator"
        self.manager = self.policy.approver_user

        self.assertNotEqual(
            self.requester, self.manager,
            "Test manager must differ from requester"
        )

        self.assertTrue(
            frappe.db.get_value(
                "User", self.manager, "enabled"
            )
        )

        # Only inside the test:
        # Bypass the activation requirement and target lookup.
        self.policy_patch = patch.object(
            requests,
            "get_policy",
            return_value=self.policy
        )
        self.target_patch = patch.object(
            requests,
            "validate_target"
        )

        self.policy_patch.start()
        self.target_patch.start()

        self.addCleanup(self.policy_patch.stop)
        self.addCleanup(self.target_patch.stop)

        self.target_name = (
            "TEST-APPROVAL-" + uuid4().hex[:12]
        )

    def as_user(self, user):
        return patch.object(
            requests,
            "current_user",
            return_value=user
        )

    def create_draft(self):
        with self.as_user(self.requester):
            name = requests.create_request(
                policy_name=self.policy.name,
                reference_name=self.target_name,
                reason="Test deletion request"
            )

        return frappe.get_doc("Approval Request", name)

    def submit(self, name):
        with self.as_user(self.requester):
            return requests.submit_request(name)

    def test_create_draft(self):
        doc = self.create_draft()

        self.assertEqual(
            doc.workflow_state, "Draft"
        )
        self.assertEqual(
            doc.requested_by, self.requester
        )

    def test_submit_request(self):
        doc = self.create_draft()

        self.submit(doc.name)
        doc.reload()

        self.assertEqual(
            doc.workflow_state, "Pending Approval"
        )
        self.assertEqual(
            doc.assigned_approver, self.manager
        )
        self.assertEqual(doc.review_cycle, 1)

    def test_requester_cannot_approve(self):
        doc = self.create_draft()
        self.submit(doc.name)

        with self.as_user(self.requester):
            with self.assertRaises(
                frappe.PermissionError
            ):
                requests.decide_request(
                    doc.name,
                    "Approved"
                )

    def test_manager_approves(self):
        doc = self.create_draft()
        self.submit(doc.name)

        with self.as_user(self.manager):
            requests.decide_request(
                doc.name,
                "Approved",
                "Approved for deletion"
            )

        doc.reload()

        self.assertEqual(
            doc.workflow_state, "Approved"
        )

        decisions = frappe.get_all(
            "Approval Decision",
            filters={"approval_request": doc.name},
            fields=["decision", "decided_by"]
        )

        self.assertEqual(len(decisions), 1)
        self.assertEqual(
            decisions[0].decision, "Approved"
        )
        self.assertEqual(
            decisions[0].decided_by, self.manager
        )

    def test_reject_and_resubmit(self):
        doc = self.create_draft()
        self.submit(doc.name)

        with self.as_user(self.manager):
            requests.decide_request(
                doc.name,
                "Rejected",
                "Insufficient justification"
            )

        with self.as_user(self.requester):
            requests.revise_request(
                doc.name,
                "Updated justification"
            )

            requests.submit_request(doc.name)

        doc.reload()

        self.assertEqual(
            doc.workflow_state, "Pending Approval"
        )
        self.assertEqual(doc.review_cycle, 2)
        self.assertEqual(
            doc.assigned_approver, self.manager
        )

    def test_direct_status_change_blocked(self):
        doc = self.create_draft()

        doc.workflow_state = "Approved"

        with self.assertRaises(frappe.PermissionError):
            doc.save(ignore_permissions=True)

    def test_duplicate_request_blocked(self):
        self.create_draft()

        with self.as_user(self.requester):
            with self.assertRaises(frappe.ValidationError):
                requests.create_request(
                    policy_name=self.policy.name,
                    reference_name=self.target_name,
                    reason="Duplicate request"
                )
