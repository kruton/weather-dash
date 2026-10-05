"""Serve one pinned signed Rust firmware release, separate from script OTA."""

import hashlib
import json
import os
import re
import struct
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse

PROFILE = "inky-rp2040-rust-v1"
PRODUCT = "weather-dash-rs"
LAYOUT = "rp2040-2m-swap-v1"
ADDRESS = 0x10009000
MAX_IMAGE = 1_028_096
MAX_MANIFEST = 2048
router = APIRouter(prefix="/api/ota/firmware")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate manifest field")
        result[key] = value
    return result


def validate_manifest(value):
    if not isinstance(value, dict) or set(value) != {
        "protocol",
        "profile",
        "layout",
        "version",
        "revision",
        "flash_start",
        "size",
        "sha256",
    }:
        raise ValueError("Invalid Rust manifest fields")
    if (
        type(value["protocol"]) is not int
        or value["protocol"] != 1
        or value["profile"] != PROFILE
        or value["layout"] != LAYOUT
        or type(value["flash_start"]) is not int
        or value["flash_start"] != ADDRESS
        or type(value["size"]) is not int
        or not 8 <= value["size"] <= MAX_IMAGE
        or not isinstance(value["version"], str)
        or not re.fullmatch(r"[A-Za-z0-9._+\-]{1,32}", value["version"])
        or not isinstance(value["revision"], str)
        or not re.fullmatch(r"[0-9a-f]{40}", value["revision"])
        or not isinstance(value["sha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"])
    ):
        raise ValueError("Incompatible or invalid Rust manifest")
    return value


class RustPackage:
    def __init__(self, directory, trust_key):
        self.directory = Path(directory)
        manifest_path = self.directory / "manifest.json"
        if manifest_path.stat().st_size > MAX_MANIFEST:
            raise ValueError("Oversized Rust manifest")
        self.raw = manifest_path.read_bytes()
        sig_path = self.directory / "manifest.sig"
        if not 8 <= sig_path.stat().st_size <= 80:
            raise ValueError("Invalid Rust signature size")
        self.signature = sig_path.read_bytes()
        pinned = Path(trust_key).read_bytes()
        if (self.directory / "public-key.der").read_bytes() != pinned:
            raise ValueError("Rust package key differs from pinned trust key")
        public = serialization.load_der_public_key(pinned)
        if not isinstance(public, ec.EllipticCurvePublicKey) or not isinstance(
            public.curve, ec.SECP256R1
        ):
            raise TypeError("Rust trust key must be P-256")
        public.verify(self.signature, self.raw, ec.ECDSA(hashes.SHA256()))
        self.manifest = validate_manifest(
            json.loads(self.raw, object_pairs_hook=unique_object)
        )
        self.root = hashlib.sha256(self.raw).hexdigest()
        self.image = self.directory / "firmware.bin"
        if self.image.stat().st_size != self.manifest["size"]:
            raise ValueError("Wrong Rust firmware length")
        digest = hashlib.sha256()
        with self.image.open("rb") as source:
            vectors = source.read(8)
            digest.update(vectors)
            while chunk := source.read(65536):
                digest.update(chunk)
        sp, reset = struct.unpack("<II", vectors)
        if not (
            0x20000000 < sp <= 0x20040000
            and sp % 8 == 0
            and reset & 1
            and ADDRESS <= (reset & ~1) < ADDRESS + self.manifest["size"]
        ):
            raise ValueError("Invalid Rust firmware vectors")
        if digest.hexdigest() != self.manifest["sha256"]:
            raise ValueError("Corrupt Rust firmware")


@lru_cache(maxsize=1)
def get_rust_package():
    directory = Path(
        os.environ.get(
            "WEATHER_RUST_OTA_DIR",
            str(Path(os.environ.get("WEATHER_OTA_DIR", "/app/ota")) / "rust"),
        )
    )
    if not directory.exists():
        return None
    # An existing but incomplete directory is a deployment error, not no OTA.
    return RustPackage(
        directory,
        os.environ.get(
            "WEATHER_RUST_OTA_PUBLIC_KEY",
            str(Path(__file__).with_name("rust-ota-public-key.der")),
        ),
    )


def package_for(root):
    package = get_rust_package()
    if package is None or package.root != root:
        raise HTTPException(404, "No matching Rust firmware in this deployment")
    return package


@router.get("/{root}/manifest.json")
def manifest(root: str):
    package = package_for(root)
    return Response(
        package.raw,
        media_type="application/json",
        headers={
            "Cache-Control": "no-store",
            "X-Weather-OTA-Signature": package.signature.hex(),
        },
    )


@router.get("/{root}/firmware.bin")
def firmware(root: str):
    package = package_for(root)
    return FileResponse(
        package.image,
        media_type="application/octet-stream",
        headers={"Cache-Control": "no-store"},
    )
