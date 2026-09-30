"""Stream a signed delta into the inactive slot; never replace running files."""
import binascii
import gc
import hashlib
import json
import os
import time

import ota_boot as boot
import ota_protocol as protocol

BOUNDARY = b"weather-ota-v1"


class Reader:
    def __init__(self, response):
        self.response = response
        self.buffer = b""
        self.started = time.time()

    def exact(self, size):
        result = bytearray()
        while len(result) < size:
            if time.time() - self.started > 90:
                raise OSError("OTA download time budget exceeded")
            if not self.buffer:
                self.buffer = self.response.read(1024)
                if not self.buffer:
                    raise ValueError("Truncated OTA response")
            count = min(size - len(result), len(self.buffer))
            result.extend(self.buffer[:count])
            self.buffer = self.buffer[count:]
        return bytes(result)

    def line(self):
        result = bytearray()
        while len(result) <= 256:
            result.extend(self.exact(1))
            if result[-2:] == b"\r\n":
                return bytes(result[:-2])
        raise ValueError("OTA header too long")

    def part(self, first=False):
        if not first and self.exact(2) != b"\r\n":
            raise ValueError("Invalid part separator")
        boundary = self.line()
        if boundary == b"--" + BOUNDARY + b"--":
            return None
        if boundary != b"--" + BOUNDARY:
            raise ValueError("Invalid multipart boundary")
        headers = {}
        for _ in range(8):
            line = self.line()
            if not line:
                break
            name, value = line.split(b":", 1)
            name = name.lower()
            if name in headers:
                raise ValueError("Duplicate header")
            headers[name] = value.strip()
        else:
            raise ValueError("Too many headers")
        size = int(headers[b"content-length"])
        if size < 0 or size > protocol.MAX_FILE:
            raise ValueError("Invalid part size")
        return headers[b"x-ota-path"].decode(), size


def mkdirs(path):
    parts = path.split("/")
    for i in range(2 if path.startswith("/") else 1, len(parts) + 1):
        directory = "/".join(parts[:i])
        try:
            os.mkdir(directory)
        except OSError:
            # Fail on errors other than an already existing directory.
            if not os.stat(directory)[0] & 0x4000:
                raise


def remove_tree(path):
    try:
        entries = os.listdir(path)
    except OSError:
        return
    for name in entries:
        child = path + "/" + name
        if os.stat(child)[0] & 0x4000:
            remove_tree(child)
        else:
            os.remove(child)
    os.rmdir(path)


def write_file(path, size, read, expected):
    mkdirs(path.rsplit("/", 1)[0])
    digest = hashlib.sha256()
    header = b""
    with open(path, "wb") as out:
        remaining = size
        while remaining:
            data = read(min(1024, remaining))
            if not data or len(data) > remaining:
                raise ValueError("Truncated script")
            if len(header) < 4:
                header += data[:4 - len(header)]
            out.write(data)
            digest.update(data)
            remaining -= len(data)
    if binascii.hexlify(digest.digest()).decode() != expected:
        raise ValueError("Script hash mismatch")
    if header[0:2] != b"M\x06" or header[2] & 0xfc or header[3] > 31:
        raise ValueError("Incompatible script bytecode")


def install(response, expected_root):
    import ota_verify
    reader = Reader(response)
    first = reader.part(first=True)
    if first is None or first[0] != "manifest.json" or first[1] > protocol.MAX_MANIFEST:
        raise ValueError("Missing or oversized manifest")
    raw = reader.exact(first[1])
    signature_part = reader.part()
    if signature_part is None or signature_part[0] != "manifest.sig" or not 8 <= signature_part[1] <= 80:
        raise ValueError("Missing signature")
    signature = reader.exact(signature_part[1])
    if not ota_verify.verify(raw, signature):
        raise ValueError("Invalid OTA signature")
    manifest = json.loads(raw)
    hashes = protocol.validate_manifest(manifest)
    if manifest["root"] != expected_root:
        raise ValueError("OTA root changed")
    target = "b" if boot.slot == "a" else "a"
    directory = boot.BASE + "/" + target
    remove_tree(directory)
    mkdirs(directory)
    stats = os.statvfs(boot.BASE)
    # Account for filesystem blocks, metadata, signed manifest and hash module.
    block = stats[1]
    needed = sum(((info["size"] + block - 1) // block) * block
                 for info in manifest["files"].values()) + 32768
    if stats[4] * block < needed:
        raise ValueError("Insufficient space for OTA slot")
    received = set()
    part = reader.part()
    while part is not None:
        path, size = part
        if path not in hashes or path in received or size != manifest["files"][path]["size"]:
            raise ValueError("Unexpected or duplicate script part")
        write_file(directory + "/" + path, size, reader.exact, hashes[path])
        received.add(path)
        part = reader.part()
    for path in hashes:
        if path not in received:
            if boot.script_hashes.get(path) != hashes[path]:
                raise ValueError("Missing changed script")
            with open(boot.BASE + "/" + boot.slot + "/" + path, "rb") as source:
                write_file(directory + "/" + path, manifest["files"][path]["size"], source.read, hashes[path])
                if source.read(1):
                    raise ValueError("Incorrect local script size")
    # Every file has been hashed, including reused code. Unlisted old files are
    # absent from this new slot, so removals need no arbitrary deletion API.
    if protocol.merkle_root(hashes) != expected_root:
        raise ValueError("Incomplete OTA package")
    with open(directory + "/manifest.json", "wb") as out:
        out.write(raw)
    with open(directory + "/manifest.sig", "wb") as out:
        out.write(signature)
    with open(directory + "/hashes.py", "w") as out:
        out.write(protocol.hashes_source(expected_root, hashes))
    boot.sync()
    boot.stage(target, expected_root)


def check(root, url):
    if (not protocol.valid_hash(root) or boot.state is None or root == boot.root_hash
            or root == boot.state.get("rejected") or boot.state.get("pending")):
        return False
    import mrequests
    response = None
    try:
        gc.collect()
        response = mrequests.request("POST", url.rstrip("/") + "/api/ota/update",
            # This pinned mrequests shadows its json= argument with the json
            # module. Serialize explicitly so the actual hash map reaches API.
            data=json.dumps({"profile": protocol.PROFILE, "root": root,
                             "script_hashes": boot.script_hashes}).encode(),
            headers={b"Content-Type": b"application/json"},
            save_headers=True, max_redirects=0, timeout=30)
        if response.status_code == 204:
            return False
        if response.status_code != 200:
            raise ValueError(f"OTA HTTP status {response.status_code}")
        content_type = None
        for header in response.headers:
            name, value = header.split(b":", 1)
            if name.lower() == b"content-type":
                content_type = value.strip()
        if content_type != b"multipart/mixed; boundary=" + BOUNDARY:
            raise ValueError("Invalid OTA content type")
        install(response, root)
        print("OTA staged for next wake:", root)
        return True
    except Exception as error:  # noqa: BLE001 - keep the scheduled draw running
        print("OTA postponed:", error)
        return False
    finally:
        if response is not None:
            response.close()
        gc.collect()
