import unittest

from cpu_data.domain.identity import normalize_cpu_name


class CPUIdentityTests(unittest.TestCase):
    def test_normalizes_case_whitespace_and_full_width_characters(self):
        self.assertEqual(
            normalize_cpu_name("  Ｉｎｔｅｌ   Core i7-13700K "),
            "intel core i7-13700k",
        )

    def test_rejects_empty_names(self):
        for value in ("", "   ", None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_cpu_name(value)
