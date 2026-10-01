import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.machine = MagicMock()
        self.machine.unique_id.return_value = b"abcdefgh"
        spec = importlib.util.spec_from_file_location(
            "panel_config", Path(__file__).resolve().parents[1] / "panel_config.py"
        )
        self.config = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, machine=self.machine):
            spec.loader.exec_module(self.config)
        self.config.PATH = self.temp.name + "/panel_config.json"

    def snapshot(self, **updates):
        config = {
            "configured": True,
            "display": "inky-frame-spectra-7",
            "panel_profile": "spectra6",
            "name": "Paris 🌦",
            "lat": 48.86,
            "long": 2.35,
            "battery_type": "unknown",
            "battery_cells": 3,
        }
        config.update(updates)
        return {"schema": 1, "version": "a" * 64, "config": config}

    def headers(self, value):
        return [b"x-WEATHER-config: " + json.dumps(value, ensure_ascii=True).encode()]

    def test_apply_atomic_reload_and_ack(self):
        value = self.snapshot()
        self.assertTrue(self.config.apply(self.headers(value)))
        self.assertEqual(json.loads(Path(self.config.PATH).read_text()), value)
        self.config.current = None
        self.assertEqual(self.config.load(), value)
        self.assertEqual(
            self.config.request_headers()[b"X-Weather-Device-ID"], b"6162636465666768"
        )
        self.assertEqual(
            self.config.request_headers()[b"X-Weather-Config-Version"], b"a" * 64
        )
        with patch.object(self.config.os, "rename") as rename:
            self.assertFalse(self.config.apply(self.headers(value)))
            rename.assert_not_called()

    def test_invalid_headers_preserve_cache(self):
        original = self.snapshot()
        self.config.apply(self.headers(original))
        for value in (
            self.snapshot(lat=float("nan")),
            self.snapshot(long=181),
            self.snapshot(display="other"),
            self.snapshot(battery_type="li-ion", battery_cells=3),
            self.snapshot(configured=1),
            {"schema": 99, "version": "a" * 64, "config": {}},
        ):
            self.assertFalse(self.config.apply(self.headers(value)))
            self.assertEqual(self.config.current, original)
        self.assertFalse(
            self.config.apply(
                [b"X-Weather-Config: " + b"x" * (self.config.MAX_HEADER + 1)]
            )
        )
        self.assertFalse(self.config.apply(self.headers(original) * 2))

    def test_interrupted_write_never_acknowledges(self):
        original = self.snapshot()
        self.config.apply(self.headers(original))
        new = self.snapshot(name="Tokyo")
        new["version"] = "b" * 64
        with patch.object(self.config.os, "rename", side_effect=OSError("Full flash")):
            self.assertFalse(self.config.apply(self.headers(new)))
        self.assertEqual(self.config.current, original)
        self.assertEqual(json.loads(Path(self.config.PATH).read_text()), original)
        self.assertEqual(self.config.load(), original)

    def test_corrupt_cache_boot_default(self):
        Path(self.config.PATH).write_text("partial JSON")
        self.assertIsNone(self.config.load())
        with patch.dict(
            sys.modules, picographics=SimpleNamespace(DISPLAY_INKY_FRAME_SPECTRA_7=7)
        ):
            self.assertEqual(self.config.display_driver(), 7)
        self.assertNotIn(b"X-Weather-Config-Version", self.config.request_headers())

    def test_57_hardware_selection_and_mismatched_server_config(self):
        spec = importlib.util.spec_from_file_location(
            "panel_config_57", Path(__file__).resolve().parents[1] / "panel_config.py"
        )
        config = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, machine=self.machine,
                        weather_config=SimpleNamespace(HARDWARE_DISPLAY="inky-frame-5.7"),
                        picographics=SimpleNamespace(DISPLAY_INKY_FRAME=57)):
            spec.loader.exec_module(config)
            config.PATH = self.temp.name + "/panel_config-57.json"
            self.assertEqual(config.display_driver(), 57)
            self.assertEqual(config.request_headers()[b"X-Weather-Display"], b"inky-frame-5.7")
            self.assertFalse(config.apply(self.headers(self.snapshot())))
            self.assertTrue(config.apply(self.headers(self.snapshot(
                display="inky-frame-5.7", panel_profile="acep"))))
            self.assertEqual(config.active_display, "inky-frame-5.7")

    def test_battery_sampling_and_telemetry(self):
        self.machine.Pin.return_value.value.return_value = 0
        self.machine.ADC.return_value.read_u16.return_value = 25818
        voltage, source = self.config.battery_reading()
        self.assertAlmostEqual(voltage, 3.9, places=2)
        self.assertEqual(source, "battery")
        self.machine.Pin.assert_any_call(25, self.machine.Pin.OUT, value=1)
        self.assertEqual(
            self.config.request_headers((voltage, source))[b"X-Weather-Power-Source"],
            b"battery",
        )
        self.machine.ADC.return_value.read_u16.return_value = 0
        self.assertIsNone(self.config.battery_reading())
        self.machine.ADC.side_effect = OSError("ADC unavailable")
        self.assertIsNone(self.config.battery_reading())

    def test_micropython_surrogates_normalize_before_length_validation(self):
        value = self.snapshot(name="\ud83c\udf26" * 160)
        self.assertEqual(self.config.normalize(value)["config"]["name"], "🌦" * 160)
        self.assertTrue(self.config.valid(value))
        for name in ("\ud83c", "\udf26", "\ud83cX"):
            with self.assertRaises(ValueError):
                self.config.normalize(self.snapshot(name=name))


if __name__ == "__main__":
    unittest.main()
