"""Exercise the actual client against signed, fragmented server multipart bytes."""
import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

import ota
import ota_boot as boot
import ota_protocol as protocol


class Fragments:
    def __init__(self, data, fragment=7):
        self.source = io.BytesIO(data)
        self.fragment = fragment

    def read(self, size):
        return self.source.read(min(size, self.fragment))


def package(key, scripts):
    from cryptography.hazmat.primitives import serialization
    files = {p: {"size": len(data), "sha256": protocol.digest(data)} for p, data in sorted(scripts.items())}
    manifest = {"protocol": 1, "profile": protocol.PROFILE,
                "firmware": "inky-ota-v1-micropython-1.29.0",
                "mpy_version": 6, "small_int_bits": 31, "files": files,
                "root": protocol.merkle_root({p: info["sha256"] for p, info in files.items()})}
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return manifest, raw, key.sign(raw, ec.ECDSA(hashes.SHA256())), key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def multipart(raw, signature, scripts):
    result = bytearray()
    for path, data in [("manifest.json", raw), ("manifest.sig", signature)] + list(scripts.items()):
        result.extend(b"--weather-ota-v1\r\nX-OTA-Path: " + path.encode() + b"\r\nContent-Length: "
                      + str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n")
    result.extend(b"--weather-ota-v1--\r\n")
    return bytes(result)


class OTATests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name) / "ota"
        self.base.mkdir()
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.scripts = {p: b"M\x06\x03\x1f" + p.encode() for p in
                        ("launcher.mpy", "weather.mpy", "inky_helper.mpy", "ota.mpy")}
        self.old = dict(self.scripts, **{"deleted.mpy": b"M\x06\x03\x1fold"})
        self.old_manifest = self.write_slot("a", self.old)
        boot.BASE = str(self.base)
        boot.STATE = str(self.base / "state.json")
        boot.state = {"active": "a"}
        boot.slot = "a"
        boot.root_hash = self.old_manifest["root"]
        boot.script_hashes = {p: protocol.digest(d) for p, d in self.old.items()}
        boot.write_state(boot.state)
        self.local = Path(self.temp.name) / "weather_config.py"
        self.local.write_text("local settings")
        self.verifier = SimpleNamespace(verify=self.verify)
        mock = patch.dict(sys.modules, {"ota_verify": self.verifier})
        mock.start()
        self.addCleanup(mock.stop)
        self.addCleanup(self.restore_boot)

    def restore_boot(self):
        boot.BASE = "/ota"
        boot.STATE = "/ota/state.json"
        boot.state = None
        boot.slot = None
        boot.script_hashes = None
        boot.root_hash = None

    def verify(self, raw, signature):
        try:
            self.key.public_key().verify(signature, raw, ec.ECDSA(hashes.SHA256()))
            return True
        except (InvalidSignature, ValueError):
            return False

    def write_slot(self, slot, scripts):
        manifest, raw, signature, _ = package(self.key, scripts)
        directory = self.base / slot
        directory.mkdir()
        for p, data in scripts.items():
            (directory / p).parent.mkdir(parents=True, exist_ok=True)
            (directory / p).write_bytes(data)
        (directory / "manifest.json").write_bytes(raw)
        (directory / "manifest.sig").write_bytes(signature)
        (directory / "hashes.py").write_text(protocol.hashes_source(manifest["root"],
            {p: protocol.digest(d) for p, d in scripts.items()}))
        return manifest

    def update_data(self, scripts=None):
        scripts = scripts or self.scripts
        manifest, raw, signature, _ = package(self.key, scripts)
        changed = {p: d for p, d in scripts.items() if boot.script_hashes.get(p) != protocol.digest(d)}
        return manifest, raw, signature, multipart(raw, signature, changed)

    def select(self):
        with patch.object(sys, "implementation", SimpleNamespace(_mpy=6)), patch.object(sys, "path", list(sys.path)):
            return boot.select()

    def test_delta_deletion_and_self_update_preserve_config(self):
        self.scripts["ota.mpy"] += b"new updater\r\n--weather-ota-v1\r\nbinary"
        manifest, _, _, data = self.update_data()
        ota.install(Fragments(data, 1), manifest["root"])
        self.assertEqual(boot.state["active"], "a")
        self.assertEqual(boot.state["pending"], "b")
        self.assertFalse((self.base / "b/deleted.mpy").exists())
        self.assertEqual((self.base / "b/ota.mpy").read_bytes(), self.scripts["ota.mpy"])
        self.assertEqual(self.local.read_text(), "local settings")
        self.assertEqual(self.select(), "b")
        self.assertTrue(boot.read_state()["attempted"])
        boot.confirm()
        self.assertEqual(boot.read_state(), {"active": "b"})

    def test_unconfirmed_trial_rolls_back_and_remembers_root(self):
        manifest, _, _, data = self.update_data()
        ota.install(Fragments(data), manifest["root"])
        self.assertEqual(self.select(), "b")
        self.assertEqual(self.select(), "a")
        self.assertEqual(boot.read_state()["rejected"], manifest["root"])
        with patch.dict(sys.modules, {"mrequests": SimpleNamespace(request=unittest.mock.Mock())}):
            self.assertFalse(ota.check(manifest["root"], "https://server"))
            sys.modules["mrequests"].request.assert_not_called()

    def test_matching_root_needs_no_network(self):
        with patch.dict(sys.modules, {"mrequests": SimpleNamespace(request=unittest.mock.Mock())}):
            self.assertFalse(ota.check(boot.root_hash, "https://server"))
            sys.modules["mrequests"].request.assert_not_called()

    def test_request_uses_explicit_json_and_closes_response(self):
        manifest, _, _, data = self.update_data()
        response = Fragments(data)
        response.status_code = 200
        response.headers = [b"Content-Type: multipart/mixed; boundary=weather-ota-v1"]
        response.close = unittest.mock.Mock()
        request = unittest.mock.Mock(return_value=response)
        with patch.dict(sys.modules, {"mrequests": SimpleNamespace(request=request)}):
            self.assertTrue(ota.check(manifest["root"], "https://server"))
        kwargs = request.call_args.kwargs
        self.assertNotIn("json", kwargs)
        self.assertEqual(json.loads(kwargs["data"])["script_hashes"], boot.script_hashes)
        self.assertEqual(kwargs["headers"], {b"Content-Type": b"application/json"})
        response.close.assert_called_once()

    def test_tampering_and_truncation_never_stage(self):
        self.scripts["weather.mpy"] += b"updated"
        manifest, raw, signature, data = self.update_data()
        invalid = (data[:-8], data.replace(b"updated", b"changed"),
                   multipart(raw + b" ", signature, {}),
                   multipart(raw, b"x" * len(signature), {}))
        for body in invalid:
            with self.subTest(body=body[-20:]), self.assertRaises(ValueError):
                ota.install(Fragments(body), manifest["root"])
            self.assertEqual(boot.read_state(), {"active": "a"})
            self.assertEqual((self.base / "a/weather.mpy").read_bytes(), self.old["weather.mpy"])

    def test_missing_and_duplicate_files_fail(self):
        self.scripts["weather.mpy"] += b"updated"
        manifest, raw, signature, _ = self.update_data()
        with self.assertRaises(ValueError):
            ota.install(Fragments(multipart(raw, signature, {})), manifest["root"])
        data = multipart(raw, signature, {"weather.mpy": self.scripts["weather.mpy"]})
        part = data[data.index(b"--weather-ota-v1\r\nX-OTA-Path: weather.mpy"):data.rindex(b"--weather-ota-v1--")]
        data = data[:data.rindex(b"--weather-ota-v1--")] + part + b"--weather-ota-v1--\r\n"
        with self.assertRaises(ValueError):
            ota.install(Fragments(data), manifest["root"])
        self.assertNotIn("pending", boot.read_state())

    def test_insufficient_space(self):
        manifest, _, _, data = self.update_data()
        with patch.object(ota.os, "statvfs", return_value=(4096, 4096, 1, 0, 0)), self.assertRaisesRegex(ValueError, "space"):
            ota.install(Fragments(data), manifest["root"])
        self.assertNotIn("pending", boot.read_state())

    def test_download_time_budget(self):
        reader = ota.Reader(Fragments(b"test"))
        with patch.object(ota.time, "time", return_value=reader.started + 91), self.assertRaises(OSError):
            reader.exact(1)

    def test_corrupt_reused_file_is_detected(self):
        (self.base / "a/weather.mpy").write_bytes(b"M\x06\x03\x1fbad")
        manifest, _, _, data = self.update_data()
        with self.assertRaises(ValueError):
            ota.install(Fragments(data), manifest["root"])
        self.assertNotIn("pending", boot.read_state())

    def test_atomic_state_failure_keeps_old_selection(self):
        manifest, _, _, data = self.update_data()
        with patch.object(boot.os, "rename", side_effect=OSError("power loss")), self.assertRaises(OSError):
            ota.install(Fragments(data), manifest["root"])
        self.assertEqual(boot.read_state(), {"active": "a"})
        self.assertEqual(self.select(), "a")

    def test_failed_confirmation_rolls_back_on_reboot(self):
        manifest, _, _, data = self.update_data()
        ota.install(Fragments(data), manifest["root"])
        self.select()
        with patch.object(boot.os, "rename", side_effect=OSError("power loss")), self.assertRaises(OSError):
            boot.confirm()
        self.assertEqual(self.select(), "a")
        self.assertEqual(boot.state["rejected"], manifest["root"])

    def test_corrupt_pending_manifest_rolls_back(self):
        manifest, _, _, data = self.update_data()
        ota.install(Fragments(data), manifest["root"])
        (self.base / "b/manifest.sig").write_bytes(b"x" * 70)
        with self.assertRaises(ValueError):
            self.select()
        self.assertEqual(self.select(), "a")

    def test_usb_reset_only_for_pending(self):
        machine = SimpleNamespace(reset=unittest.mock.Mock())
        with patch.dict(sys.modules, {"machine": machine}):
            boot.reset_if_pending()
            machine.reset.assert_not_called()
            boot.state["pending"] = "b"
            boot.reset_if_pending()
            machine.reset.assert_called_once()

    def test_manifest_rejects_path_limits_and_profiles(self):
        manifest, _, _, _ = self.update_data()
        for field, value in (("profile", "other"), ("mpy_version", 7), ("small_int_bits", 63), ("root", "0" * 64)):
            bad = copy.deepcopy(manifest)
            bad[field] = value
            with self.assertRaises(ValueError):
                protocol.validate_manifest(bad)
        for path in ("../weather.mpy", "/weather.mpy", "lib//x.mpy", "secrets.py", "lib/x-y.mpy", "secrets.mpy", "lib/weather_config.mpy", "ota_boot.mpy"):
            self.assertFalse(protocol.valid_path(path))
        bad = copy.deepcopy(manifest)
        bad["files"]["weather.mpy"]["size"] = protocol.MAX_FILE + 1
        with self.assertRaises(ValueError):
            protocol.validate_manifest(bad)

    def test_merkle_independent_of_map_order_and_domain_separated(self):
        hashes_map = {"b.mpy": "1" * 64, "a.mpy": "0" * 64, "c.mpy": "2" * 64}
        self.assertEqual(protocol.merkle_root(hashes_map), protocol.merkle_root(dict(reversed(list(hashes_map.items())))))
        leaves = [hashlib.sha256(b"\x00" + p.encode() + b"\x00" + bytes.fromhex(hashes_map[p])).digest()
                  for p in sorted(hashes_map)]
        left = hashlib.sha256(b"\x01" + leaves[0] + leaves[1]).digest()
        right = hashlib.sha256(b"\x01" + leaves[2] + leaves[2]).digest()
        self.assertEqual(protocol.merkle_root(hashes_map), hashlib.sha256(b"\x01" + left + right).hexdigest())


if __name__ == "__main__":
    unittest.main()
