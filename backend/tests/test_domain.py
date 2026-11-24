import unittest

from cpu_data.domain.cpu import CPURecord
from cpu_data.domain.vendors import classify_vendor


class CPURecordTests(unittest.TestCase):
    def test_mapping_round_trip(self):
        source = {
            "name": " Intel Core i7-13700K ",
            "brand": "Intel",
            "family": "Raptor Lake",
            "cores": "16",
            "threads": "24",
            "passmark_score": "45646",
            "source_url": "https://example.invalid/cpu",
            "unrelated": "ignored",
        }
        record = CPURecord.from_mapping(source)
        self.assertEqual(record.name, "Intel Core i7-13700K")
        self.assertEqual(record.passmark_score, 45646)
        self.assertEqual(record.to_mapping()["family"], "Raptor Lake")
        self.assertNotIn("unrelated", record.to_mapping())

    def test_empty_name_is_rejected(self):
        with self.assertRaises(ValueError):
            CPURecord.from_mapping({"name": " "})

    def test_invalid_or_negative_score_is_rejected(self):
        with self.assertRaises(ValueError):
            CPURecord.from_mapping({"name": "CPU", "passmark_score": "not-a-number"})
        with self.assertRaises(ValueError):
            CPURecord.from_mapping({"name": "CPU", "passmark_score": -1})
        with self.assertRaises(ValueError):
            CPURecord.from_mapping({"name": "CPU", "passmark_score": True})


    def test_fractional_passmark_score_is_rejected_without_truncation(self):
        with self.assertRaises(ValueError):
            CPURecord.from_mapping({"name": "CPU", "passmark_score": 123.75})
        self.assertEqual(
            CPURecord.from_mapping({"name": "CPU", "passmark_score": 123.0}).passmark_score,
            123,
        )

    def test_vendor_classification_is_shared_and_explicit(self):
        self.assertEqual(classify_vendor("AMD Ryzen 9 7950X"), "AMD")
        self.assertEqual(classify_vendor("Intel Core i7-13700K"), "Intel")
        self.assertEqual(classify_vendor("Apple M3 Max"), "Apple")
        self.assertEqual(classify_vendor("Qualcomm Snapdragon X Elite"), "Qualcomm")
        self.assertEqual(classify_vendor("AArch64"), "ARM")
        self.assertEqual(classify_vendor("Unlisted CPU Vendor"), "Unknown")


if __name__ == "__main__":
    unittest.main()
