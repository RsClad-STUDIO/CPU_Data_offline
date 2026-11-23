import unittest
from pathlib import Path

from cpu_data.config import PROJECT_ROOT, load_settings


class SettingsTests(unittest.TestCase):
    def test_default_data_location_uses_os_standard_directory(self):
        settings = load_settings({"LOCALAPPDATA": "/tmp/local-app-data"}, platform="nt", home=Path("/home/test"))
        self.assertEqual(settings.data_dir, Path("/tmp/local-app-data/CPU_Data_offline"))
        self.assertEqual(settings.db_path.name, "cpu.db")

    def test_macos_and_linux_default_locations(self):
        mac = load_settings({}, platform="darwin", home=Path("/Users/test"))
        self.assertEqual(mac.data_dir, Path("/Users/test/Library/Application Support/CPU_Data_offline"))
        linux = load_settings({}, platform="posix", home=Path("/home/test"))
        self.assertEqual(linux.data_dir, Path("/home/test/.local/share/cpu-data-offline"))

    def test_platform_configuration_directories(self):
        windows = load_settings({"APPDATA": "/tmp/roaming"}, platform="win32", home=Path("/home/test"))
        self.assertEqual(windows.config_dir, Path("/tmp/roaming/CPU_Data_offline"))
        mac = load_settings({}, platform="darwin", home=Path("/Users/test"))
        self.assertEqual(mac.config_dir, Path("/Users/test/Library/Preferences/CPU_Data_offline"))
        linux = load_settings({"XDG_CONFIG_HOME": "/tmp/config"}, platform="linux", home=Path("/home/test"))
        self.assertEqual(linux.config_dir, Path("/tmp/config/cpu-data-offline"))

    def test_xdg_data_home_is_respected(self):
        settings = load_settings({"XDG_DATA_HOME": "/mnt/data"}, platform="posix", home=Path("/home/test"))
        self.assertEqual(settings.data_dir, Path("/mnt/data/cpu-data-offline"))

    def test_relative_data_home_is_resolved_from_project_root(self):
        settings = load_settings({"CPU_DATA_HOME": "custom-data"}, platform="posix", home=Path("/home/test"))
        self.assertEqual(settings.data_dir, (PROJECT_ROOT / "custom-data").resolve())
        self.assertEqual(settings.db_path.name, "cpu.db")

    def test_runtime_settings_can_be_overridden(self):
        settings = load_settings({
            "CPU_DATA_HOME": str(Path.home() / "cpu-data-test"),
            "CPU_HTTP_CONNECT_TIMEOUT": "8",
            "CPU_HTTP_READ_TIMEOUT": "45",
            "CPU_HTTP_RETRIES": "5",
            "CPU_HTTP_RETRY_BACKOFF": "1.25",
            "CPU_UPDATE_BATCH_SIZE": "50",
            "CPU_NANOREVIEW_DELAY": "0.75",
        })
        self.assertEqual(settings.http_connect_timeout, 8)
        self.assertEqual(settings.http_read_timeout, 45)
        self.assertEqual(settings.http_retries, 5)
        self.assertEqual(settings.retry_backoff, 1.25)
        self.assertEqual(settings.update_batch_size, 50)
        self.assertEqual(settings.nanoreview_delay, 0.75)

    def test_invalid_values_are_rejected(self):
        with self.assertRaises(ValueError):
            load_settings({"CPU_UPDATE_BATCH_SIZE": "0"})
        with self.assertRaises(ValueError):
            load_settings({"CPU_NANOREVIEW_DELAY": "-1"})


if __name__ == "__main__":
    unittest.main()
