"""OTA v1 primitives shared by the host and frozen device bootstrap."""
# Percent formatting also works on older MicroPython builds.
# ruff: noqa: UP031
import binascii
import hashlib

PROFILE = "inky-v1-mpy6"
MAX_MANIFEST = 16384
MAX_FILES = 64
MAX_FILE = 128 * 1024
MAX_TOTAL = 256 * 1024
PROTECTED = ("main.mpy", "boot.mpy", "ota_boot.mpy", "ota_protocol.mpy",
             "ota_verify.mpy", "hashes.mpy", "secrets.mpy", "weather_config.mpy")


def digest(data):
    return binascii.hexlify(hashlib.sha256(data).digest()).decode()


def valid_hash(value):
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def valid_path(path):
    # Only compiled code goes in slots. Configuration and boot code stay outside.
    return (isinstance(path, str) and len(path) <= 128 and path.endswith(".mpy")
            and path.rsplit("/", 1)[-1] not in PROTECTED
            and all(p and p not in (".", "..")
                    and all(c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_." for c in p)
                    for p in path.split("/")))


def merkle_root(hashes):
    leaves = [hashlib.sha256(b"\x00" + p.encode() + b"\x00"
              + binascii.unhexlify(hashes[p])).digest() for p in sorted(hashes)]
    if not leaves:
        raise ValueError("Empty script package")
    while len(leaves) > 1:
        if len(leaves) % 2:
            leaves.append(leaves[-1])
        leaves = [hashlib.sha256(b"\x01" + leaves[i] + leaves[i + 1]).digest()
                  for i in range(0, len(leaves), 2)]
    return binascii.hexlify(leaves[0]).decode()


def validate_manifest(manifest):
    if (manifest.get("protocol") != 1 or manifest.get("profile") != PROFILE
            or manifest.get("firmware") != "inky-ota-v1-micropython-1.29.0"
            or manifest.get("mpy_version") != 6 or manifest.get("small_int_bits") != 31):
        raise ValueError("Incompatible firmware profile")
    files = manifest.get("files")
    if not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES:
        raise ValueError("Invalid file count")
    total = 0
    hashes = {}
    for path, info in files.items():
        if not valid_path(path) or not isinstance(info, dict):
            raise ValueError("Invalid script path")
        size = info.get("size")
        if type(size) is not int or not 4 <= size <= MAX_FILE or not valid_hash(info.get("sha256")):
            raise ValueError("Invalid script metadata")
        total += size
        hashes[path] = info["sha256"]
    if total > MAX_TOTAL:
        raise ValueError("Package too large")
    if not {"launcher.mpy", "weather.mpy", "inky_helper.mpy", "ota.mpy"}.issubset(files):
        raise ValueError("Missing required scripts")
    if merkle_root(hashes) != manifest.get("root"):
        raise ValueError("Invalid Merkle root")
    return hashes


def hashes_source(root, hashes):
    entries = "".join("    '%s': '%s',\n" % (path, hashes[path]) for path in sorted(hashes))
    return "root_hash = '%s'\nscript_hashes = {\n%s}\n" % (root, entries)
