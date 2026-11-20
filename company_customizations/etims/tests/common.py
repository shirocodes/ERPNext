import frappe
import unittest
from decimal import Decimal
from importlib import import_module


def resolve(path):
    module, attr = path.rsplit(".", 1)
    return getattr(import_module(module), attr)


def money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"))


class SiteTest(unittest.TestCase):
    def require_fields(self, doctype, names):
        fields = {f.fieldname for f in frappe.get_meta(doctype).fields}
        self.assertFalse(set(names) - fields, f"Missing fields: {set(names) - fields}")

    def require_unique(self, doctype, field):
        # MariaDB SHOW INDEX; require a single-column unique index, not just metadata.
        rows = frappe.db.sql(f"SHOW INDEX FROM `tab{doctype}`", as_dict=True)
        grouped = {}
        for row in rows:
            if int(row.Non_unique) == 0:
                grouped.setdefault(row.Key_name, []).append(row.Column_name)
        self.assertIn([field], list(grouped.values()))
