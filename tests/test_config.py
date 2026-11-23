import tempfile
import unittest
from pathlib import Path

from cpu_data.config import PROJECT_ROOT, load_settings


class SettingsTests(unittest.TestCase):
    def test_default_data_location_uses_os_standard_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local_app_data = root / "local-app-data"
            settings = load_settings(
                {"LOCALAPPDATA": str(local_app_data)},
                platform="nt",
                home=root / "home",
            )
            self.assertEqual(settings.data_dir, (local_app_data / "CPU_Data_offline").resolve())
            self.assertEqual(settings.db_path.name, "cpu.db")

    def test_macos_and_linux_default_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            mac = load_settings({}, platform="darwin", home=home)
            self.assertEqual(
                mac.data_dir,
                (home / "Library" / "Application Support" / "CPU_Data_offline").resolve(),
            )
            linux = load_settings({}, platform="linux", home=home)
            self.assertEqual(
                linux.data_dir,
                (home / ".local" / "share" / "cpu-data-offline").resolve(),
            )

    def test_platform_configuration_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            roaming = root / "roaming"
            windows = load_settings(
                {"APPDATA": str(roaming)}, platform="win32", home=root / "home"
            )
            self.assertEqual(
                windows.config_dir, (roaming / "CPU_Data_offline").resolve()
            )
            home = root / "mac-home"
            mac = load_settings({}, platform="darwin", home=home)
            self.assertEqual(
                mac.config_dir,
                (home / "Library" / "Preferences" / "CPU_Data_offline").resolve(),
            )
            xdg_config = root / "config"
            linux = load_settings(
                {"XDG_CONFIG_HOME": str(xdg_config)},
                platform="linux",
                home=root / "linux-home",
            )
            self.assertEqual(
                linux.config_dir, (xdg_config / "cpu-data-offline").resolve()
            )

    def test_xdg_data_home_is_respected(self):
        with tempfile.TemporaryDirectory() as directory:
            xdg_data = Path(directory) / "data"
            settings = load_settings(
                {"XDG_DATA_HOME": str(xdg_data)},
                platform="linux",
                home=Path(directory) / "home",
            )
            self.assertEqual(
                settings.data_dir, (xdg_data / "cpu-data-offline").resolve()
            )

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
        for value in ("nan", "inf", "-inf"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                load_settings({"CPU_HTTP_RETRY_BACKOFF": value})


if __name__ == "__main__":
    unittest.main()
