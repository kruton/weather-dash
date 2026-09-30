import calendar
from datetime import datetime
import importlib.util
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch


class WeatherTests(unittest.TestCase):
    def setUp(self):
        self.machine = MagicMock()
        self.machine.unique_id.return_value = b"abcdefgh"
        self.requests = MagicMock()
        self.pngdec = MagicMock()
        self.clock = SimpleNamespace(
            gmtime=lambda timestamp: time.gmtime(timestamp)[:8],
            mktime=calendar.timegm,
            time=MagicMock(return_value=0),
        )
        modules = dict(machine=self.machine, mrequests=self.requests,
                       pngdec=self.pngdec, sdcard=MagicMock(), uos=MagicMock(),
                       time=self.clock,
                       panel_config=SimpleNamespace(current=None, active_display="inky-frame-spectra-7",
                           apply=MagicMock(), request_headers=lambda battery: {b"accept": b"image/png", b"X-Weather-Device-ID": b"6162636465666768"}),
                       weather_config=SimpleNamespace(NAME="San Francisco, California",
                           LAT="37.7749", LONG="-122.4194",
                           URL="https://weather-dash.their.net"))
        spec = importlib.util.spec_from_file_location(
            "weather", Path(__file__).resolve().parents[1] / "weather.py")
        self.weather = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules):
            spec.loader.exec_module(self.weather)
        self.weather.graphics = MagicMock()
        self.weather.graphics.measure_text.return_value = 20
        self.weather.WIDTH = 800
        self.weather.HEIGHT = 480

    def timestamp(self, value):
        return int(datetime.fromisoformat(value).timestamp())

    def test_device_request_uses_server_settings(self):
        self.weather.update()
        url = self.requests.get.call_args.args[0]
        self.assertIn("width=800&height=480", url)
        for local in ("lat=", "long=", "name=", "panel_profile="):
            self.assertNotIn(local, url)
        self.assertEqual(self.requests.get.call_args.kwargs["headers"][b"X-Weather-Device-ID"], b"6162636465666768")

    def test_draw_preserves_server_dithering(self):
        self.weather.draw()
        self.pngdec.PNG().decode.assert_called_once_with(mode=self.pngdec.PNG_POSTERISE)

    def test_next_refresh(self):
        cases = (
            ("2026-09-30T19:01:00-07:00", "2026-10-01T07:00:00-07:00", 719),
            ("2026-09-30T06:59:30-07:00", "2026-09-30T07:00:00-07:00", 1),
            ("2026-09-30T07:00:10-07:00", "2026-09-30T07:00:00-07:00", 1),
        )
        for now, target, minutes in cases:
            with self.subTest(now=now):
                self.weather.next_refresh = self.timestamp(target)
                self.assertEqual(self.weather.minutes_until_refresh(self.timestamp(now)), minutes)

    def test_response_next_refresh(self):
        now = self.timestamp("2026-09-30T19:01:00-07:00")
        target = self.timestamp("2026-10-01T07:00:00-07:00")
        self.assertEqual(self.weather.response_next_refresh(
            [f"X-Weather-Next-Refresh: {target}".encode()], now), target)
        for headers in ([], [b"X-Weather-Next-Refresh: invalid"],
                        [f"X-Weather-Next-Refresh: {now - 1}".encode()],
                        [f"X-Weather-Next-Refresh: {now + 27 * 3600}".encode()]):
            self.assertIsNone(self.weather.response_next_refresh(headers, now))

    def test_server_clock_overrides_date(self):
        timestamp = self.timestamp("2026-09-30T14:01:00+00:00")
        self.assertTrue(self.weather.sync_clock([
            b"Date: Wed, 30 Sep 2026 13:59:30 GMT",
            f"X-Weather-Time: {timestamp}".encode(),
        ]))
        self.machine.RTC().datetime.assert_called_once_with((2026, 9, 30, 3, 14, 1, 0, 0))

    def test_unix_timestamp_on_older_micropython_epoch(self):
        self.weather.UNIX_EPOCH_OFFSET = 946684800
        self.clock.gmtime = lambda value: time.gmtime(value + 946684800)[:8]
        now = self.timestamp("2026-09-30T19:01:00-07:00")
        target = self.timestamp("2026-10-01T07:00:00-07:00")
        self.assertTrue(self.weather.sync_clock([f"X-Weather-Time: {now}".encode()]))
        self.assertEqual(self.weather.response_next_refresh(
            [f"X-Weather-Next-Refresh: {target}".encode()], now - 946684800),
            target - 946684800)

    def test_http_clock_and_cache_age(self):
        headers = [b"dAtE: Wed, 30 Sep 2026 13:59:30 GMT\r\n", b"Age: 90\r\n"]
        self.assertTrue(self.weather.sync_clock(headers))
        self.machine.RTC().datetime.assert_called_once_with((2026, 9, 30, 3, 14, 1, 0, 0))

    def test_invalid_http_clock(self):
        for headers in ([], [b"Date: invalid"],
                        [b"Date: Wed, 31 Feb 2026 13:00:00 GMT"],
                        [b"Date: Wed, 30 Sep 2026 25:00:00 GMT"]):
            self.assertFalse(self.weather.sync_clock(headers))
        self.machine.RTC().datetime.assert_not_called()

    def test_download_failure_closes_response(self):
        response = self.requests.get.return_value
        response.headers = [b"Date: Wed, 30 Sep 2026 14:00:00 GMT"]
        response.status_code = 200
        response.save.side_effect = OSError("SD write failed")
        self.weather.update()
        response.close.assert_called_once()
        self.assertTrue(self.requests.get.call_args.kwargs["save_headers"])
        self.assertIn("width=800&height=480", self.requests.get.call_args.args[0])

    def test_schedule_is_calculated_after_refresh(self):
        self.weather.clock_synced = True
        self.weather.next_refresh = self.timestamp("2026-10-01T07:00:00-07:00")
        self.clock.time.return_value = self.timestamp("2026-09-30T18:59:30-07:00")
        def finish_refresh():
            self.clock.time.return_value = self.timestamp("2026-09-30T19:01:00-07:00")
        self.weather.graphics.update.side_effect = finish_refresh
        self.weather.draw()
        self.assertEqual(self.weather.UPDATE_INTERVAL, 719)
        self.weather.graphics.set_blocking.assert_called_once_with(True)

    def test_missing_schedule_uses_fallback(self):
        self.weather.clock_synced = True
        self.weather.draw()
        self.assertEqual(self.weather.UPDATE_INTERVAL, 240)

    def test_successful_update_reads_schedule(self):
        now = self.timestamp("2026-09-30T19:01:00-07:00")
        target = self.timestamp("2026-10-01T07:00:00-07:00")
        self.clock.time.return_value = now
        response = self.requests.get.return_value
        response.status_code = 200
        response.headers = [f"X-Weather-Time: {now}".encode(),
                            f"X-Weather-Next-Refresh: {target}".encode()]
        self.weather.update()
        self.assertEqual(self.weather.next_refresh, target)
        self.weather.draw()
        self.assertEqual(self.weather.UPDATE_INTERVAL, 719)
        self.requests.get.assert_called_once()

    def test_failed_update_clears_previous_schedule(self):
        self.weather.next_refresh = self.timestamp("2026-10-01T07:00:00-07:00")
        self.requests.get.side_effect = OSError("Offline")
        self.weather.update()
        self.weather.draw()
        self.assertIsNone(self.weather.next_refresh)
        self.assertEqual(self.weather.UPDATE_INTERVAL, 240)

    def test_download_crossing_target_retries_in_one_minute(self):
        now = self.timestamp("2026-09-30T06:59:50-07:00")
        target = self.timestamp("2026-09-30T07:00:00-07:00")
        self.clock.time.return_value = now
        response = self.requests.get.return_value
        response.status_code = 200
        response.headers = [f"X-Weather-Time: {now}".encode(),
                            f"X-Weather-Next-Refresh: {target}".encode()]
        def finish_download(*args, **kwargs):
            self.clock.time.return_value = target + 20
        response.save.side_effect = finish_download
        self.weather.update()
        self.weather.draw()
        self.assertEqual(self.weather.UPDATE_INTERVAL, 1)

    def test_unsynced_clock_uses_fallback_even_on_decode_error(self):
        self.pngdec.PNG().decode.side_effect = RuntimeError("Bad PNG")
        self.weather.draw()
        self.assertEqual(self.weather.UPDATE_INTERVAL, 240)
        self.clock.time.assert_not_called()
        self.weather.graphics.update.assert_called_once()

    def ota_response(self, root):
        now = self.timestamp("2026-09-30T19:01:00-07:00")
        self.clock.time.return_value = now
        response = self.requests.get.return_value
        response.status_code = 200
        response.headers = [f"X-Weather-Time: {now}".encode(),
                            f"X-Weather-Next-Refresh: {now + 3600}".encode(),
                            f"X-Weather-OTA-Root: {root}".encode()]
        return response

    def test_current_root_does_not_load_updater(self):
        root = "a" * 64
        response = self.ota_response(root)
        boot = SimpleNamespace(state={"active": "a"}, root_hash=root)
        updater = MagicMock()
        with patch.dict(sys.modules, {"ota_boot": boot, "ota": updater,
                "ota_protocol": SimpleNamespace(PROFILE="inky-v1-mpy6")}):
            self.weather.update()
            self.assertIs(sys.modules["ota"], updater)
        updater.check.assert_not_called()
        response.close.assert_called_once()
        self.assertIn("ota_profile=inky-v1-mpy6", self.requests.get.call_args.args[0])

    def test_ota_runs_after_image_closes_and_time_counts_toward_sleep(self):
        response = self.ota_response("b" * 64)
        boot = SimpleNamespace(state={"active": "a"}, root_hash="a" * 64)
        updater = MagicMock()
        def update(*args):
            response.close.assert_called_once()
            self.weather.graphics.update.assert_not_called()
            self.clock.time.return_value += 120
        updater.check.side_effect = update
        with patch.dict(sys.modules, {"ota_boot": boot, "ota": updater,
                "ota_protocol": SimpleNamespace(PROFILE="inky-v1-mpy6")}):
            self.weather.update()
            self.assertNotIn("ota", sys.modules)
        updater.check.assert_called_once_with("b" * 64, "https://weather-dash.their.net")
        self.weather.draw()
        self.assertEqual(self.weather.UPDATE_INTERVAL, 58)

    def test_ota_failure_still_draws_on_schedule(self):
        self.ota_response("b" * 64)
        boot = SimpleNamespace(state={"active": "a"}, root_hash="a" * 64)
        updater = MagicMock()
        updater.check.side_effect = OSError("Interrupted OTA")
        with patch.dict(sys.modules, {"ota_boot": boot, "ota": updater,
                "ota_protocol": SimpleNamespace(PROFILE="inky-v1-mpy6")}):
            self.weather.update()
        self.weather.draw()
        self.weather.graphics.update.assert_called_once()
        self.assertEqual(self.weather.UPDATE_INTERVAL, 60)

    def test_server_render_failure_can_still_update_scripts(self):
        response = self.ota_response("b" * 64)
        response.status_code = 503
        boot = SimpleNamespace(state={"active": "a"}, root_hash="a" * 64)
        updater = MagicMock()
        with patch.dict(sys.modules, {"ota_boot": boot, "ota": updater,
                "ota_protocol": SimpleNamespace(PROFILE="inky-v1-mpy6")}):
            self.weather.update()
        updater.check.assert_called_once_with("b" * 64, "https://weather-dash.their.net")
        response.save.assert_not_called()
        self.assertEqual(self.weather.err_string, "Error fetching")


if __name__ == "__main__":
    unittest.main()
