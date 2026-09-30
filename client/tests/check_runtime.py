"""Run with the pinned unix MicroPython built with native/ota_verify.

Arguments: client directory, signed bundle directory, scratch filesystem directory.
The verifier must have the bundle's public key compiled in.
"""
import io
import json
import sys

client, bundle, scratch = sys.argv[1:4]
sys.path.insert(0, client)
sys.path.insert(0, bundle + "/scripts/lib")
sys.path.insert(0, bundle + "/scripts")
import mrequests  # noqa: F401 - verify compiled dependency imports
import ota_verify

import ota
import ota_boot as boot
import ota_protocol as protocol

with open(bundle + "/manifest.json", "rb") as f:
    raw = f.read()
with open(bundle + "/manifest.sig", "rb") as f:
    signature = f.read()
assert ota_verify.verify(raw, signature)
assert not ota_verify.verify(raw + b" ", signature)
assert not ota_verify.verify(raw, signature[:-1])
manifest = json.loads(raw)
hashes = protocol.validate_manifest(manifest)
with open(bundle + "/hashes.py") as f:
    assert f.read() == protocol.hashes_source(manifest["root"], hashes)
boot.BASE = scratch
boot.STATE = scratch + "/state.json"
boot.slot = "a"
boot.state = {"active": "a"}
boot.script_hashes = {}
boot.write_state(boot.state)
# The production server uses exactly this per-part framing.
body = bytearray()
for path in ["manifest.json", "manifest.sig"] + sorted(hashes):
    filename = bundle + "/" + path if path.startswith("manifest.") else bundle + "/scripts/" + path
    with open(filename, "rb") as f:
        data = f.read()
    body.extend(b"--weather-ota-v1\r\nX-OTA-Path: " + path.encode() + b"\r\nContent-Length: "
                + str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n")
body.extend(b"--weather-ota-v1--\r\n")

class Fragments:
    def __init__(self, body):
        self.source = io.BytesIO(body)

    def read(self, size):
        return self.source.read(min(size, 13))

ota.install(Fragments(body), manifest["root"])
assert boot.read_state()["pending"] == "b"
assert boot.select() == "b"
boot.confirm()
assert boot.read_state() == {"active": "b"}
print("Native signatures, compiled OTA/mrequests imports, streaming install, trial and confirmation passed")

if len(sys.argv) > 4:
    # Exercise mrequests' real HTTP chunked decoder against the deployed API.
    boot.root_hash = "0" * 64
    boot.script_hashes = {}
    assert ota.check(manifest["root"], sys.argv[4])
    assert boot.read_state()["pending"] == "a"
    print("Real HTTP chunked multipart update passed")
