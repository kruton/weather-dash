"""Serve the signed script package baked into this deployed container."""
import json
import os
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from . import ota_protocol as protocol

router = APIRouter(prefix="/api/ota")
BOUNDARY = b"weather-ota-v1"


class Package:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.raw = (self.directory / "manifest.json").read_bytes()
        self.signature = (self.directory / "manifest.sig").read_bytes()
        if len(self.raw) > protocol.MAX_MANIFEST or not 8 <= len(self.signature) <= 80:
            raise ValueError("Invalid OTA manifest size")
        public = serialization.load_der_public_key((self.directory / "public-key.der").read_bytes())
        if not isinstance(public, ec.EllipticCurvePublicKey) or not isinstance(public.curve, ec.SECP256R1):
            raise TypeError("OTA trust key must be P-256")
        public.verify(self.signature, self.raw, ec.ECDSA(hashes.SHA256()))
        self.manifest = json.loads(self.raw)
        self.hashes = protocol.validate_manifest(self.manifest)
        self.root = self.manifest["root"]
        for path, info in self.manifest["files"].items():
            data = (self.directory / "scripts" / path).read_bytes()
            if len(data) != info["size"] or protocol.digest(data) != info["sha256"]:
                raise ValueError("Corrupt bundled OTA script: " + path)
            if data[:2] != b"M\x06" or data[2] & 0xfc or data[3] > 31:
                raise ValueError("Incompatible bundled bytecode")

    def multipart(self, client_hashes):
        def part(path, size):
            return (b"--" + BOUNDARY + b"\r\nContent-Type: application/octet-stream\r\n"
                    + b"X-OTA-Path: " + path.encode() + b"\r\nContent-Length: "
                    + str(size).encode() + b"\r\n\r\n")
        yield part("manifest.json", len(self.raw))
        yield self.raw
        yield b"\r\n"
        yield part("manifest.sig", len(self.signature))
        yield self.signature
        yield b"\r\n"
        for path, info in self.manifest["files"].items():
            if client_hashes.get(path) == info["sha256"]:
                continue
            yield part(path, info["size"])
            with (self.directory / "scripts" / path).open("rb") as source:
                while data := source.read(1024):
                    yield data
            yield b"\r\n"
        yield b"--" + BOUNDARY + b"--\r\n"


@lru_cache(maxsize=1)
def get_package():
    directory = Path(os.environ.get("WEATHER_OTA_DIR", "/app/ota"))
    if not (directory / "manifest.json").exists():
        return None  # Source checkouts and local images can run without OTA.
    return Package(directory)


def root_header(profile):
    from .rust_ota import PROFILE, get_rust_package
    if profile == PROFILE:
        package = get_rust_package()
        return {"X-Weather-OTA-Root": package.root} if package is not None else {}
    package = get_package()
    if package is not None and profile == protocol.PROFILE:
        return {"X-Weather-OTA-Root": package.root}
    return {}


@router.post("/update")
async def update(request: Request):
    package = get_package()
    if package is None:
        raise HTTPException(404, "No script package in this deployment")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > protocol.MAX_MANIFEST:
            raise HTTPException(413, "Hash request too large")
    try:
        value = json.loads(body)
        if not isinstance(value, dict):
            raise TypeError("Invalid request")
        if value.get("profile") != protocol.PROFILE:
            raise HTTPException(409, "Incompatible firmware profile")
        root = value.get("root")
        client_hashes = value.get("script_hashes")
        if not protocol.valid_hash(root) or not isinstance(client_hashes, dict) or len(client_hashes) > protocol.MAX_FILES:
            raise ValueError("Invalid hash map")
        if any(not protocol.valid_path(p) or not protocol.valid_hash(h) for p, h in client_hashes.items()):
            raise ValueError("Invalid script hash")
    except (ValueError, TypeError) as error:
        raise HTTPException(422, "Invalid OTA request") from error
    if root != package.root:
        raise HTTPException(409, "Script package changed; retry on next weather refresh")
    if client_hashes == package.hashes:
        return Response(status_code=204, headers={"Cache-Control": "no-store"})
    return StreamingResponse(package.multipart(client_hashes),
        media_type="multipart/mixed; boundary=weather-ota-v1", headers={"Cache-Control": "no-store"})
