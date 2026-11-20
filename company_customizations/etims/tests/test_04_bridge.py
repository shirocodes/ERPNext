import frappe
import unittest

from frappe.model.base_document import get_controller


class BridgeTests(unittest.TestCase):

    def test_queue_class_override(self):
        cls = get_controller("eTims Job Queue")

        self.assertEqual(cls.__name__, "CustomETimsJobQueue")
        self.assertTrue(callable(getattr(cls, "run_queue", None)))

    def test_chui_provider_route(self):
        cls = get_controller("eTims Job Queue")

        self.assertTrue(
            callable(getattr(cls, "_run_chui_job", None))
        )

    def test_dispatcher_hook(self):
        dispatcher = frappe.get_attr(
            "company_customizations.etims.dispatcher.process_job"
        )

        self.assertTrue(callable(dispatcher))