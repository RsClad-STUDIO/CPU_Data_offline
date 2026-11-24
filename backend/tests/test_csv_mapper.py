import unittest

from cpu_data.infrastructure.importers.csv_mapper import (
    CSVMappingError,
    preview_csv,
)


class CSVMapperTests(unittest.TestCase):
    def test_maps_common_english_and_japanese_headers(self):
        preview = preview_csv(
            "CPU Name,メーカー,コア数,Threads,PassMark CPU Mark\n"
            "Intel Core i7-13700K,Intel,16,24,45646\n".encode()
        )
        row = preview.rows[0]
        self.assertEqual(row.status, "new")
        self.assertEqual(row.record.name, "Intel Core i7-13700K")
        self.assertEqual(row.record.brand, "Intel")
        self.assertEqual(row.record.cores, "16")
        self.assertEqual(row.record.threads, "24")
        self.assertEqual(row.record.passmark_score, 45646)

    def test_generic_score_is_not_assigned_to_passmark(self):
        preview = preview_csv(
            b"CPU Name,Score\nIntel Core i7-13700K,45646\n"
        )
        self.assertIsNone(preview.rows[0].record.passmark_score)
        self.assertEqual(preview.unknown_columns, ("Score",))
        self.assertEqual(preview.rows[0].unknown_fields["Score"], "45646")

    def test_explicit_mapping_can_assign_a_generic_score(self):
        preview = preview_csv(
            b"Processor,Score\nIntel Core i7-13700K,45646\n",
            column_mapping={"Processor": "name", "Score": "passmark_score"},
        )
        self.assertEqual(preview.rows[0].record.passmark_score, 45646)

    def test_rejects_non_integer_passmark_score(self):
        preview = preview_csv(
            b"CPU Name,PassMark Score\nIntel Core i7-13700K,45,646\n"
        ) if False else preview_csv(
            b'CPU Name,PassMark Score\nIntel Core i7-13700K,"45.6k"\n'
        )
        self.assertEqual(preview.rows[0].status, "error")
        self.assertIn("whole number", preview.rows[0].errors[0])

    def test_rejects_negative_passmark_score(self):
        preview = preview_csv(
            b"CPU Name,PassMark Score\nIntel Core i7-13700K,-1\n"
        )
        self.assertEqual(preview.rows[0].status, "error")

    def test_classifies_exact_existing_cpu_as_update(self):
        preview = preview_csv(
            b"CPU Name,Brand\nIntel Core i7-13700K,Intel\n",
            existing_records=[{"name": "  intel   core i7-13700k "}],
        )
        self.assertEqual(preview.rows[0].status, "update")

    def test_classifies_unmatched_cpu_as_new(self):
        preview = preview_csv(
            b"CPU Name\nIntel Core i7-13700K\n",
            existing_records=[{"name": "Intel Core i5-12400"}],
        )
        self.assertEqual(preview.rows[0].status, "new")

    def test_duplicate_existing_identity_is_ambiguous(self):
        preview = preview_csv(
            b"CPU Name\nIntel Core i7-13700K\n",
            existing_records=[
                {"name": "Intel Core i7-13700K"},
                {"name": "intel core i7-13700k"},
            ],
        )
        self.assertEqual(preview.rows[0].status, "ambiguous")

    def test_duplicate_input_identity_is_ambiguous(self):
        preview = preview_csv(
            b"CPU Name\nIntel Core i7-13700K\nintel core i7-13700k\n"
        )
        self.assertEqual([row.status for row in preview.rows], ["ambiguous", "ambiguous"])

    def test_preserves_unknown_columns_for_each_row(self):
        preview = preview_csv(
            b"CPU Name,Unknown Metric\nIntel Core i7-13700K,abc\n"
        )
        self.assertEqual(preview.unknown_columns, ("Unknown Metric",))
        self.assertEqual(preview.rows[0].unknown_fields, {"Unknown Metric": "abc"})

    def test_requires_cpu_name_mapping(self):
        with self.assertRaises(CSVMappingError):
            preview_csv(b"Brand,Score\nIntel,123\n")

    def test_rejects_conflicting_field_mappings(self):
        with self.assertRaises(CSVMappingError):
            preview_csv(
                b"CPU Name,Processor\nIntel Core i7,Intel Core i7\n",
                column_mapping={"Processor": "name"},
            )

    def test_rejects_unknown_explicit_target(self):
        with self.assertRaises(CSVMappingError):
            preview_csv(
                b"Processor\nIntel Core i7\n",
                column_mapping={"Processor": "unknown_field"},
            )

    def test_preview_counts_all_statuses(self):
        preview = preview_csv(
            b"CPU Name,PassMark Score\n"
            b"Intel Core i7-13700K,45646\n"
            b"AMD Ryzen 7 7800X3D,unknown\n",
            existing_records=[{"name": "Intel Core i7-13700K"}],
        )
        self.assertEqual(
            preview.counts,
            {"new": 0, "update": 1, "ambiguous": 0, "error": 1},
        )

    def test_preview_does_not_import_or_write_to_database(self):
        import inspect
        from cpu_data.infrastructure.importers import csv_mapper

        source = inspect.getsource(csv_mapper)
        self.assertNotIn("sqlite3", source)
        self.assertNotIn("upsert_many", source)
        self.assertNotIn("init_db", source)


if __name__ == "__main__":
    unittest.main()
