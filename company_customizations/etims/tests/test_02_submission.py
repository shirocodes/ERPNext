import frappe
from common import SiteTest
from config import MOCK_SUBMISSION, MOCK_JOB


DT = "CHUI eTIMS Submission"


class SubmissionTests(SiteTest):
    def test_schema(self):
        self.require_fields(DT, ("parcel_id", "transaction_id", "idempotency_key", "payment_status", "submission_status", "queue_job", "kra_invoice_number", "kra_response"))
        self.assertEqual(frappe.get_meta(DT).get_field("queue_job").options, "eTims Job Queue")

    def test_unique_index(self):
        self.require_unique(DT, "idempotency_key")

    def test_existing_mock_submission(self):
        doc = frappe.get_doc(DT, MOCK_SUBMISSION)
        if not frappe.db.exists("eTims Job Queue", doc.queue_job):
            self.skipTest("Historical queue job missing or expired")
