#!/usr/bin/env python3
"""Fetch and verify the exact signed Rust release pinned for a server image."""

import argparse
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "rust_ota_package",
    Path(__file__).resolve().parent.parent / "src/weather_dash/rust_ota.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
RustPackage = module.RustPackage
REPOSITORY = "kruton/weather-dash-rs"
ASSET_NAME = "weather-dash-rs-ota.tar"


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(request, fp, code, msg, headers, newurl)
        if (
            redirected is not None
            and urllib.parse.urlsplit(newurl).hostname
            != urllib.parse.urlsplit(request.full_url).hostname
        ):
            redirected.remove_header("Authorization")
        return redirected


def download(url, accept, limit):
    headers = {"Accept": accept, "User-Agent": "weather-dash-rust-ota"}
    if urllib.parse.urlsplit(url).hostname == "api.github.com" and os.environ.get(
        "RUST_FIRMWARE_READ_TOKEN"
    ):
        headers["Authorization"] = "Bearer " + os.environ["RUST_FIRMWARE_READ_TOKEN"]
    opener = urllib.request.build_opener(SafeRedirect())
    with opener.open(
        urllib.request.Request(url, headers=headers), timeout=60
    ) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Release download exceeds size limit")
    return data


def release_url(tag, digest):
    if (
        not isinstance(tag, str)
        or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?", tag)
        or len(tag) > 33
    ):
        raise ValueError("Invalid firmware release tag")
    release = json.loads(
        download(
            f"https://api.github.com/repos/{REPOSITORY}/releases/tags/{tag}",
            "application/vnd.github+json",
            256 * 1024,
        )
    )
    if (
        not isinstance(release, dict)
        or release.get("tag_name") != tag
        or release.get("draft") is not False
        or release.get("prerelease") is not False
    ):
        raise ValueError("Expected a published stable firmware release")
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise TypeError("Missing firmware release assets")
    matches = [
        a
        for a in assets
        if isinstance(a, dict)
        and a.get("name") == ASSET_NAME
        and a.get("state") == "uploaded"
    ]
    if len(matches) != 1:
        raise ValueError("Expected exactly one firmware archive asset")
    asset = matches[0]
    url = asset.get("url")
    if not isinstance(url, str) or not re.fullmatch(
        rf"https://api\.github\.com/repos/{REPOSITORY}/releases/assets/[0-9]+", url
    ):
        raise ValueError("Unexpected firmware asset URL")
    if asset.get("digest") != "sha256:" + digest:
        raise ValueError("Release asset SHA-256 differs from lock")
    return url


def fetch(lock_path, output, trust_key, required=False):
    lock = json.loads(Path(lock_path).read_text())
    if lock is None:
        if required:
            raise ValueError(
                "Production deployment requires a pinned Rust firmware release"
            )
        return False
    if not isinstance(lock, dict) or set(lock) not in (
        {"url", "sha256"},
        {"tag", "sha256"},
    ):
        raise ValueError("Release lock requires tag (or legacy url) and sha256")
    if (
        not isinstance(lock["sha256"], str)
        or len(lock["sha256"]) != 64
        or any(c not in "0123456789abcdef" for c in lock["sha256"])
    ):
        raise ValueError("Invalid release archive hash")
    url = release_url(lock["tag"], lock["sha256"]) if "tag" in lock else lock["url"]
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ValueError("Release URL must use HTTPS without credentials")
    data = download(url, "application/octet-stream", 2 * 1024 * 1024)
    if (
        len(data) > 2 * 1024 * 1024
        or hashlib.sha256(data).hexdigest() != lock["sha256"]
    ):
        raise ValueError("Release archive size or SHA-256 mismatch")
    output = Path(output)
    if output.exists():
        raise ValueError(
            "Rust package output already exists; use a clean build directory"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        stage = Path(temp) / "rust"
        stage.mkdir()
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
            limits = {
                "manifest.json": 2048,
                "manifest.sig": 80,
                "firmware.bin": 1_028_096,
                "public-key.der": 91,
            }
            members = archive.getmembers()
            if len(members) != 4 or {m.name for m in members} != set(limits):
                raise ValueError("Unexpected Rust package files")
            for member in members:
                if not member.isfile() or not 0 < member.size <= limits[member.name]:
                    raise ValueError("Unsafe or oversized Rust package member")
                with archive.extractfile(member) as source:
                    (stage / member.name).write_bytes(
                        source.read(limits[member.name] + 1)
                    )
        package = RustPackage(stage, trust_key)
        if "tag" in lock and package.manifest["version"] != lock["tag"][1:]:
            raise ValueError("Signed firmware version differs from release tag")
        shutil.move(stage, output)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", default="rust-firmware.lock.json", type=Path)
    parser.add_argument("--output", default="ota-dist/rust", type=Path)
    parser.add_argument("--required", action="store_true")
    args = parser.parse_args()
    fetch(
        args.lock,
        args.output,
        Path(__file__).resolve().parent.parent
        / "src/weather_dash/rust-ota-public-key.der",
        args.required,
    )
