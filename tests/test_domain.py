import unittest

from cpu_data.domain.cpu import CPURecord


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


if __name__ == "__main__":
    unittest.main()
