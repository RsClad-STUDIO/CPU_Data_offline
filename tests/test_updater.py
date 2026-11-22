import unittest
from types import SimpleNamespace
from unittest.mock import patch

import requests

import updater


PASSMARK_HTML = """
<html><body>
<table id="cputable">
  <tr><th>CPU Name</th><th>CPU Mark</th></tr>
  <tr><td><a href="/cpu.php?cpu=AMD+Ryzen+9+7950X">AMD Ryzen 9 7950X</a></td><td>62,116</td></tr>
  <tr><td><a href="/cpu.php?cpu=Intel+Core+i7-13700K">Intel Core i7-13700K</a></td><td>45,646</td></tr>
  <tr><td><a href="/cpu.php?cpu=Unknown">Unknown CPU</a></td><td>NA</td></tr>
</table>
</body></html>
"""

NANOREVIEW_HTML = """
<html><head><meta name="description" content="16-core processor with 24 threads for socket LGA-1700. Base clock is 3.4 GHz and can boost up to 5.3 GHz. Integrated graphics Intel UHD Graphics 770."></head>
<body>
<ul class="flex">
  <li>Cores: 16</li>
  <li>L3 cache: 30MB (shared)</li>
  <li>TDP: 125 W (max. boost up to 253 W)</li>
  <li>Transistor size: 10 nm</li>
</ul>
<table>
  <tr><td>Codename</td><td>Raptor Lake</td></tr>
  <tr><td>Total Cores</td><td>16</td></tr>
  <tr><td>Total Threads</td><td>24</td></tr>
  <tr><td>Base Frequency (P)</td><td>3.4 GHz</td></tr>
  <tr><td>Turbo Boost Frequency (P)</td><td>5.3 GHz</td></tr>
  <tr><td>Socket</td><td>LGA-1700</td></tr>
  <tr><td>Fabrication Process</td><td>10 nm</td></tr>
  <tr><td>TDP (PL1)</td><td>125 W</td></tr>
  <tr><td>Memory Types</td><td>DDR5-5600 DDR4-3200</td></tr>
  <tr><td>Integrated GPU</td><td>Intel UHD Graphics 770</td></tr>
</table>
</body></html>
"""


class UpdaterParserTests(unittest.TestCase):
    def test_cpu_list_includes_multiple_vendors_and_parses_scores(self):
        rows = updater._parse_cpu_list_html(PASSMARK_HTML)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["name"], "AMD Ryzen 9 7950X")
        self.assertEqual(rows[0]["passmark_score"], 62116)
        self.assertEqual(rows[0]["detail_url"], "https://www.cpubenchmark.net/cpu.php?cpu=AMD+Ryzen+9+7950X")
        self.assertIsNone(rows[2]["passmark_score"])

    def test_cpu_list_rejects_unrecognized_html(self):
        with self.assertRaises(updater.DataSourceParseError):
            updater._parse_cpu_list_html("<html><body>layout changed</body></html>")

    def test_nanoreview_table_fields_are_mapped_to_correct_columns(self):
        specs = updater._parse_nanoreview_html(NANOREVIEW_HTML)
        row = updater._parse_specs(
            "Intel Core i7-13700K", specs, "https://www.cpubenchmark.net/cpu.php?id=1", 45646
        )
        self.assertEqual(row["family"], "Raptor Lake")
        self.assertEqual(row["cores"], "16")
        self.assertEqual(row["threads"], "24")
        self.assertEqual(row["base_clock"], "3.4 GHz")
        self.assertEqual(row["boost_clock"], "5.3 GHz")
        self.assertEqual(row["tdp"], "125 W")
        self.assertEqual(row["socket"], "LGA-1700")
        self.assertEqual(row["process"], "10 nm")
        self.assertEqual(row["memory_support"], "DDR5-5600 DDR4-3200")
        self.assertEqual(row["igpu"], "Intel UHD Graphics 770")
        self.assertNotEqual(row["family"], specs["l3 cache"])

    def test_nanoreview_404_is_a_miss(self):
        response = requests.Response()
        response.status_code = 404
        error = requests.HTTPError("not found", response=response)
        with patch.object(updater, "_get", side_effect=error):
            self.assertEqual(updater.fetch_nanoreview("missing-cpu"), {})

    def test_nanoreview_server_error_is_not_treated_as_a_miss(self):
        response = requests.Response()
        response.status_code = 503
        error = requests.HTTPError("unavailable", response=response)
        with patch.object(updater, "_get", side_effect=error):
            with self.assertRaises(requests.HTTPError):
                updater.fetch_nanoreview("cpu")

    def test_cpu_slug(self):
        self.assertEqual(
            updater._cpu_to_slug("Intel Core i5-4300U @ 1.90GHz"),
            "intel-core-i5-4300u",
        )

    def test_all_vendor_list_endpoint_and_vendor_classification(self):
        self.assertTrue(updater.CPU_LIST_URL.endswith("/cpu-list/all"))
        self.assertEqual(updater._brand("AMD Ryzen 9 7950X"), "AMD")
        self.assertEqual(updater._brand("Apple M3 Max"), "Apple")
        self.assertEqual(updater._brand("Qualcomm Snapdragon X Elite"), "Qualcomm")
        self.assertEqual(updater._brand("AArch64"), "ARM")

    def test_nanoreview_rejects_unrecognized_html(self):
        with self.assertRaises(updater.DataSourceParseError):
            updater._parse_nanoreview_html("<html><body>maintenance page</body></html>")

    def test_passmark_network_error_propagates(self):
        with patch.object(updater, "_get", side_effect=requests.ConnectionError("offline")):
            with self.assertRaises(requests.ConnectionError):
                updater.fetch_cpu_list()

    def test_interruption_flushes_processed_records_and_checkpoint(self):
        items = [
            {"name": "Intel Core i5-1", "passmark_score": 100, "detail_url": "passmark-1"},
            {"name": "Intel Core i5-2", "passmark_score": 200, "detail_url": "passmark-2"},
        ]
        meta = {"update_in_progress": "false"}
        with patch.object(updater, "init_db"), \
             patch.object(updater, "fetch_cpu_list", return_value=items), \
             patch.object(updater, "get_meta", side_effect=lambda key: meta.get(key)), \
             patch.object(updater, "set_meta") as set_meta, \
             patch.object(updater, "upsert_many") as upsert_many, \
             patch.object(updater, "fetch_nanoreview", side_effect=[{"cores": "4"}, requests.ConnectionError("offline")]), \
             patch.object(updater.time, "sleep"):
            with self.assertRaises(requests.ConnectionError):
                updater.run_update()

        saved = upsert_many.call_args.args[0]
        self.assertEqual([row["name"] for row in saved], ["Intel Core i5-1"])
        set_meta.assert_any_call("update_checkpoint", "Intel Core i5-1")
        set_meta.assert_any_call("update_in_progress", "true")

    def test_full_update_resumes_after_last_checkpoint(self):
        items = [
            {"name": "Intel Core i5-1", "passmark_score": 100, "detail_url": "passmark-1"},
            {"name": "Intel Core i5-2", "passmark_score": 200, "detail_url": "passmark-2"},
            {"name": "Intel Core i5-3", "passmark_score": 300, "detail_url": "passmark-3"},
        ]
        meta = {"update_in_progress": "true", "update_checkpoint": "Intel Core i5-2"}
        with patch.object(updater, "init_db"), \
             patch.object(updater, "fetch_cpu_list", return_value=items), \
             patch.object(updater, "get_meta", side_effect=lambda key: meta.get(key)), \
             patch.object(updater, "set_meta") as set_meta, \
             patch.object(updater, "upsert_many") as upsert_many, \
             patch.object(updater, "fetch_nanoreview", return_value={}) as fetch_nano, \
             patch.object(updater, "count_cpus", return_value=3), \
             patch.object(updater.time, "sleep"):
            updater.run_update()

        fetch_nano.assert_called_once_with(updater._cpu_to_slug("Intel Core i5-3"))
        saved = upsert_many.call_args.args[0]
        self.assertEqual([row["name"] for row in saved], ["Intel Core i5-3"])
        set_meta.assert_any_call("update_in_progress", "false")
        set_meta.assert_any_call("update_checkpoint", "")


if __name__ == "__main__":
    unittest.main()
