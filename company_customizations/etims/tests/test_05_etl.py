import unittest

from copy import deepcopy
from unittest.mock import patch
from decimal import Decimal

from company_customizations.etims.sales_integration import (
    extractor,
    transformer,
)


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------

def sample_record(customer_type="C2C"):
    return {
        "parcel_id": 2966,
        "parcel": {
            "id": 2966,
            "parcelNumber": "TEST-2966",
            "senderId": 802,
            "isPostPaid": False,
            "isDeleted": False,
        },
        "customer": {
            "customer_id": 802,
            "customer_type": customer_type,
            "customer_name": "Test Customer",
            "country": "KE",
            "kra_pin": None,
        },
        "services": [{
            "serviceType": "SEND",
            "payBy": customer_type,
            "grossPrice": 249.00,
            "netPrice": 214.66,
            "vat": 16,
            "currency": "KES",
            "isDeleted": False,
            "invoicedAt": None,
        }],
        "payments": [{
            "paymentType": "SEND",
            "payType": "PAYMENT",
            "status": "PAID",
            "amount": 249.00,
            "currency": "KES",
            "paymentChannel": "MPESA",
            "mpesaTransactionId": "TEST001",
            "mpesaTransactionDate": "2026-11-19T12:26:24",
        }],
    }


# ---------------------------------------------------------------------------
# Extraction Tests
# ---------------------------------------------------------------------------

class ExtractorTests(unittest.TestCase):

    def test_backfill_window(self):
        window = extractor.get_window(
            mode="backfill",
            start="2026-11-19T00:00:00+03:00",
            end="2026-11-20T00:00:00+03:00",
        )

        self.assertEqual(
            window["createdAtFrom"], "2026-11-18T21:00:00"
        )
        self.assertEqual(
            window["createdAtTo"], "2026-11-19T21:00:00"
        )

    def test_invalid_window(self):
        with self.assertRaises(ValueError):
            extractor.get_window(
                "backfill",
                "2026-11-19T00:00:00+03:00",
                "2026-11-19T00:00:00+03:00",
            )

    def test_full_window(self):
        self.assertEqual(extractor.get_window("full"), {})

    def test_paid_send_filter(self):
        paid = sample_record()["payments"][0]

        charges = {
            "payments": [
                paid,
                {**paid, "status": "UNPAID"},
                {**paid, "paymentType": "COD"},
                {**paid, "paymentType": "COD_FEE"},
            ]
        }

        result = extractor.get_paid_send_payments(charges)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], paid)

    def test_empty_payments(self):
        self.assertEqual(
            extractor.get_paid_send_payments({"payments": []}),
            [],
        )

    def test_send_service_filter(self):
        service = sample_record()["services"][0]

        result = extractor.get_send_services({
            "services": [
                service,
                {**service, "serviceType": "COD"},
                {**service, "serviceType": "COD_FEE"},
            ]
        })

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["serviceType"], "SEND")

    @patch.object(extractor, "api_get")
    def test_pagination(self, api):
        api.side_effect = [
            {
                "content": [{"id": 1}, {"id": 2}],
                "page": {"totalPages": 2},
            },
            {
                "content": [{"id": 3}],
                "page": {"totalPages": 2},
            },
        ]

        records = list(extractor.fetch_parcels({}))

        self.assertEqual(len(records), 3)
        self.assertEqual(api.call_count, 2)

    @patch.object(extractor, "api_get")
    def test_unpaid_parcel(self, api):
        api.return_value = {"payments": [], "services": []}

        self.assertIsNone(extractor.extract_parcel(2877))
        api.assert_called_once_with("/parcel/charges/2877")

    @patch.object(extractor, "api_get")
    def test_c2c_customer(self, api):
        api.return_value = {
            "id": 802,
            "givenName": "Test",
            "surname": "Customer",
            "type": "C2C",
        }

        customer = extractor.extract_customer(
            {"senderId": 802},
            {"payBy": "C2C"},
        )

        self.assertEqual(customer["customer_name"], "Test Customer")
        self.assertEqual(customer["customer_type"], "C2C")
        api.assert_called_once_with("/customer/802")

    @patch.object(extractor, "api_get")
    def test_b2c_customer(self, api):
        api.return_value = {
            "id": 6,
            "companyName": "Test Company",
            "invoiceData": {
                "taxNumber": "TEST-PIN",
                "invoicingFrequency": "MONTHLY",
            },
        }

        customer = extractor.extract_customer(
            {"senderId": 6},
            {"payBy": "B2C"},
        )

        self.assertEqual(customer["customer_name"], "Test Company")
        self.assertEqual(customer["kra_pin"], "TEST-PIN")
        api.assert_called_once_with("/company/6")

    @patch.object(extractor, "api_get")
    def test_customer_id_mismatch(self, api):
        api.return_value = {"id": 999}

        with self.assertRaises(ValueError):
            extractor.extract_customer(
                {"senderId": 802},
                {"payBy": "C2C"},
            )


# ---------------------------------------------------------------------------
# Transformation Tests
# ---------------------------------------------------------------------------

class TransformerTests(unittest.TestCase):

    def test_valid_c2c_transaction(self):
        transaction = transformer.transform_transaction(
            sample_record()
        )

        self.assertEqual(transaction["validation_status"], "Validated")
        self.assertEqual(
            transaction["customer"]["external_customer_id"],
            "C2C:802",
        )

    def test_valid_b2c_transaction(self):
        transaction = transformer.transform_transaction(
            sample_record("B2C")
        )

        self.assertEqual(
            transaction["customer"]["external_customer_id"],
            "B2C:802",
        )

    def test_financial_calculation(self):
        transaction = transformer.transform_transaction(
            sample_record()
        )

        gross = Decimal(transaction["gross_amount"])
        net = Decimal(transaction["net_amount"])
        vat = Decimal(transaction["vat_amount"])

        self.assertEqual(gross, Decimal("249.00"))
        self.assertEqual(net, Decimal("214.66"))
        self.assertEqual(vat, Decimal("34.34"))
        self.assertEqual(net + vat, gross)

    def test_decimal_precision(self):
        record = sample_record()

        record["payments"][0]["amount"] = 248.99
        record["services"][0]["grossPrice"] = 248.99
        record["services"][0]["netPrice"] = 214.65

        transaction = transformer.transform_transaction(record)

        self.assertEqual(transaction["gross_amount"], "248.99")
        self.assertEqual(transaction["vat_amount"], "34.34")

    def test_unpaid_rejected(self):
        record = sample_record()
        record["payments"][0]["status"] = "UNPAID"

        with self.assertRaises(ValueError):
            transformer.transform_transaction(record)

    def test_missing_transaction_reference(self):
        record = sample_record()
        record["payments"][0]["mpesaTransactionId"] = None

        with self.assertRaises(ValueError):
            transformer.transform_transaction(record)

    def test_amount_mismatch(self):
        record = sample_record()
        record["payments"][0]["amount"] = 100

        with self.assertRaises(ValueError):
            transformer.transform_transaction(record)

    def test_currency_mismatch(self):
        record = sample_record()
        record["payments"][0]["currency"] = "USD"

        with self.assertRaises(ValueError):
            transformer.transform_transaction(record)

    def test_customer_category_mismatch(self):
        record = sample_record()
        record["customer"]["customer_type"] = "B2C"

        with self.assertRaises(ValueError):
            transformer.transform_transaction(record)

    def test_multiple_paid_payments(self):
        record = sample_record()
        record["payments"].append(deepcopy(record["payments"][0]))

        with self.assertRaises(ValueError):
            transformer.transform_transaction(record)

    def test_already_invoiced(self):
        record = sample_record()
        record["services"][0]["invoicedAt"] = "2026-11-19T12:30:00"

        with self.assertRaises(ValueError):
            transformer.transform_transaction(record)

    def test_idempotency_key(self):
        first = transformer.transform_transaction(sample_record())
        second = transformer.transform_transaction(sample_record())

        self.assertEqual(
            first["idempotency_key"],
            second["idempotency_key"],
        )

    def test_batch_duplicates(self):
        result = transformer.run_transformation([
            sample_record(),
            sample_record(),
        ])

        self.assertEqual(result["summary"]["validated"], 1)
        self.assertEqual(result["summary"]["rejected"], 1)

    def test_missing_kra_pin(self):
        transaction = transformer.transform_transaction(
            sample_record("B2C")
        )

        self.assertIsNone(transaction["customer"]["kra_pin"])


# ---------------------------------------------------------------------------
# Mocked Extract + Transform Integration Tests
# ---------------------------------------------------------------------------

class ETLTests(unittest.TestCase):

    @patch.object(extractor, "fetch_parcels")
    @patch.object(extractor, "extract_parcel")
    def test_pipeline(self, extract, discover):
        discover.return_value = [
            {"id": 2966},
            {"id": 2877},
        ]

        extract.side_effect = [
            sample_record(),
            None,
        ]

        extraction = extractor.run_extraction(mode="daily")

        result = transformer.run_transformation(
            extraction["extracted"]
        )

        self.assertTrue(extraction["summary"]["complete"])
        self.assertEqual(extraction["summary"]["discovered"], 2)
        self.assertEqual(extraction["summary"]["pending"], 1)
        self.assertEqual(result["summary"]["validated"], 1)
        self.assertEqual(result["summary"]["rejected"], 0)

    @patch.object(extractor, "fetch_parcels")
    @patch.object(extractor, "extract_parcel")
    def test_extraction_failure(self, extract, discover):
        discover.return_value = [{"id": 2966}]
        extract.side_effect = RuntimeError("API unavailable")

        result = extractor.run_extraction(mode="daily")

        self.assertFalse(result["summary"]["complete"])
        self.assertEqual(result["summary"]["failed"], 1)


# ---------------------------------------------------------------------------
# Test Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)