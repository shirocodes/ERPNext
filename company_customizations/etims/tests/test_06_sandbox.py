from urllib.parse import urlsplit
import frappe
from common import SiteTest
from config import SANDBOX_DOCTYPE, SANDBOX_URL_FIELD, EXPECTED_SANDBOX_HOST


class SandboxTests(SiteTest):
    def test_sandbox_endpoint_configuration(self):
        if not all((SANDBOX_DOCTYPE, SANDBOX_URL_FIELD, EXPECTED_SANDBOX_HOST)):
            self.skipTest("Configure the sandbox settings DocType, URL field and verified host")
        self.require_fields(SANDBOX_DOCTYPE, (SANDBOX_URL_FIELD,))
        url = frappe.get_single(SANDBOX_DOCTYPE).get(SANDBOX_URL_FIELD)
        parsed = urlsplit(url or "")
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.hostname, EXPECTED_SANDBOX_HOST)
