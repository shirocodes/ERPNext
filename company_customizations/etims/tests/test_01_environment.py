import subprocess
from pathlib import Path
import frappe
from common import SiteTest
from config import EXPECTED_BRANCHES
import unittest

class EnvironmentTests(SiteTest):
    def test_required_apps(self):
        required = {"frappe", "erpnext", "company_customizations", "csf_ke", "kenya_compliance_via_slade"}
        self.assertFalse(required - set(frappe.get_installed_apps()))

    def test_branches(self):
        for app, expected in EXPECTED_BRANCHES.items():
            with self.subTest(app=app):
                path = Path(frappe.get_app_path(app)).parent
                actual = subprocess.check_output(["git", "-C", str(path), "branch", "--show-current"], text=True).strip()
                self.assertEqual(actual, expected)

    def test_post_restore_schema(self):
        for dt in ("CHUI eTIMS Submission", "eTims Job Queue", "eTims Queue Manager"):
            self.assertTrue(frappe.db.exists("DocType", dt))

            if not frappe.get_meta(dt).issingle:
                self.assertTrue(frappe.db.table_exists(dt), dt)

    @unittest.skip("Scheduler intentionally disabled during development")
    def test_scheduler(self):
        from frappe.utils.scheduler import is_scheduler_inactive
        self.assertFalse(is_scheduler_inactive())

    def test_workers(self):
        from frappe.utils.background_jobs import get_workers
        self.assertGreater(len(get_workers()), 0)
