import frappe
from common import SiteTest
from config import MOCK_JOB, MOCK_SUBMISSION


class QueueTests(SiteTest):
    def test_job_fields(self):
        self.require_fields("eTims Job Queue", ("request_id", "dedupe_key", "max_retries", "next_retry_at", "attempt_count", "is_terminal", "failure_class", "last_error", "status"))

    def test_status_options(self):
        options = set(frappe.get_meta("eTims Job Queue").get_field("status").options.splitlines())
        self.assertFalse({"Pending", "Processing", "Retrying", "Completed", "Success", "Failed", "Cancelled"} - options)

    def test_unique_index(self):
        self.require_unique("eTims Job Queue", "dedupe_key")

    def test_manager_configuration(self):
        from frappe.model.base_document import get_controller
        import importlib

        cls = get_controller("eTims Job Queue")
        module = importlib.import_module(cls.__module__)
        policy = module.policy

        self.assertGreaterEqual(policy.max_retries(), 0)

        backoff = policy.retry_backoff()
        self.assertTrue(backoff)
        self.assertTrue(all(seconds > 0 for seconds in backoff))

        self.assertGreaterEqual(policy.circuit_failure_threshold(), 1)
        self.assertGreaterEqual(policy.job_retention_hours(), 1)

    def test_historical_job_completed(self):
        if not frappe.db.exists("eTims Job Queue", MOCK_JOB):
            self.skipTest("Historical mock job absent or retained job expired")
        job = frappe.get_doc("eTims Job Queue", MOCK_JOB)
        self.assertIn(job.status, ("Completed", "Success"))
        if job.dedupe_key:
            self.assertEqual(frappe.db.count("eTims Job Queue", {"dedupe_key": job.dedupe_key}), 1)

    def test_historical_submission_state(self):
        if not frappe.db.exists("CHUI eTIMS Submission", MOCK_SUBMISSION):
            self.skipTest("Historical submission absent")
        doc = frappe.get_doc("CHUI eTIMS Submission", MOCK_SUBMISSION)
        self.assertIn(
            doc.submission_status,
            ("Submitted", "Completed", "Mock Completed"),
        )
