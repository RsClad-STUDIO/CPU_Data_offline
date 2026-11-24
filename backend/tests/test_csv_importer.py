import unittest

from cpu_data.infrastructure.importers.csv_reader import (
    CSVImportError,
    read_csv,
)


class CSVReaderTests(unittest.TestCase):
    def test_reads_utf8_bom_and_normalizes_null_values(self):
        document = read_csv(
            b"\xef\xbb\xbfCPU Name,Score,Socket\r\n"
            b"Intel Core i7-13700K,45646,LGA1700\r\n"
            b"AMD Ryzen 7 7800X3D,NA,null\r\n"
        )
        self.assertEqual(document.encoding, "utf-8-sig")
        self.assertEqual(document.headers, ("CPU Name", "Score", "Socket"))
        self.assertEqual(document.rows[0].values["Score"], "45646")
        self.assertIsNone(document.rows[1].values["Score"])
        self.assertIsNone(document.rows[1].values["Socket"])

    def test_reads_plain_utf8(self):
        document = read_csv("CPU名,メーカー\nRyzen 7 7800X3D,AMD\n".encode())
        self.assertEqual(document.encoding, "utf-8-sig")
        self.assertEqual(document.rows[0].values["CPU名"], "Ryzen 7 7800X3D")

    def test_falls_back_to_cp932(self):
        document = read_csv("CPU名,メーカー\nCore i7,インテル\n".encode("cp932"))
        self.assertEqual(document.encoding, "cp932")
        self.assertEqual(document.rows[0].values["メーカー"], "インテル")

    def test_accepts_explicit_encoding(self):
        document = read_csv(
            "CPU名,メーカー\nCore i7,インテル\n".encode("cp932"),
            encoding="cp932",
        )
        self.assertEqual(document.encoding, "cp932")

    def test_supports_tab_and_semicolon_delimiters(self):
        tabbed = read_csv(b"Name\tBrand\nRyzen\tAMD\n", delimiter="\t")
        semicolon = read_csv(b"Name;Brand\nCore;Intel\n", delimiter=";")
        self.assertEqual(tabbed.rows[0].values["Brand"], "AMD")
        self.assertEqual(semicolon.rows[0].values["Brand"], "Intel")

    def test_preserves_quoted_commas_and_multiline_cells(self):
        document = read_csv(
            b'Name,Description\nCPU,"High performance, desktop"\n'
            b'Other,"first line\nsecond line"\n'
        )
        self.assertEqual(
            document.rows[0].values["Description"],
            "High performance, desktop",
        )
        self.assertEqual(
            document.rows[1].values["Description"],
            "first line\nsecond line",
        )
        self.assertEqual(document.rows[1].row_number, 4)

    def test_skips_blank_rows(self):
        document = read_csv(b"Name,Brand\n\nCPU,Intel\n,\n")
        self.assertEqual(len(document.rows), 1)

    def test_rejects_empty_input_and_empty_headers(self):
        with self.assertRaises(CSVImportError):
            read_csv(b"")
        with self.assertRaises(CSVImportError):
            read_csv(b"Name,,Brand\nCPU,x,Intel\n")

    def test_rejects_duplicate_headers_case_insensitively(self):
        with self.assertRaisesRegex(CSVImportError, "duplicate"):
            read_csv(b"Name,name\nCPU,CPU\n")

    def test_rejects_rows_with_wrong_field_count(self):
        with self.assertRaisesRegex(CSVImportError, "expected 2"):
            read_csv(b"Name,Brand\nCPU,Intel,Extra\n")

    def test_rejects_unsupported_delimiters(self):
        with self.assertRaises(ValueError):
            read_csv(b"Name|Brand\nCPU|Intel\n", delimiter="|")

    def test_does_not_import_database_or_write_records(self):
        # The reader is intentionally a pure parsing boundary.
        import inspect
        from cpu_data.infrastructure.importers import csv_reader

        source = inspect.getsource(csv_reader)
        self.assertNotIn("sqlite3", source)
        self.assertNotIn("upsert", source.lower())


if __name__ == "__main__":
    unittest.main()
