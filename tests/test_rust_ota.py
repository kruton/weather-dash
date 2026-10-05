import hashlib
import importlib.util
import json
import shutil
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from weather_dash import get_app, ota, rust_ota
from weather_dash.fleet import PanelSettings, Registry

FIXTURE = Path(__file__).parent / "fixtures/rust-ota"


@pytest.fixture
def assets(tmp_path, monkeypatch):
    directory = tmp_path / "ota/rust"
    shutil.copytree(FIXTURE, directory)
    monkeypatch.setenv("WEATHER_RUST_OTA_DIR", str(directory))
    monkeypatch.setenv("WEATHER_RUST_OTA_PUBLIC_KEY", str(FIXTURE / "public-key.der"))
    monkeypatch.setenv("WEATHER_DATA_DIR", str(tmp_path / "data"))
    rust_ota.get_rust_package.cache_clear()
    yield directory
    rust_ota.get_rust_package.cache_clear()


def test_signed_assets_and_product_specific_routes(assets):
    package = rust_ota.get_rust_package()
    assert package.manifest["version"] == "0.2.0"
    assert ota.root_header(rust_ota.PROFILE) == {"X-Weather-OTA-Root": package.root}
    assert ota.root_header("other") == {}
    app = get_app()
    _, cache = app.state.fleet()
    cache.start = lambda: None
    with TestClient(app) as client:
        response = client.get(f"/api/ota/firmware/{package.root}/manifest.json")
        assert response.content == (FIXTURE / "manifest.json").read_bytes()
        assert response.headers["X-Weather-OTA-Signature"] == package.signature.hex()
        response = client.get(f"/api/ota/firmware/{package.root}/firmware.bin")
        assert response.content == (FIXTURE / "firmware.bin").read_bytes()
        assert int(response.headers["content-length"]) == len(response.content)
        assert response.headers["cache-control"] == "no-store"
        assert (
            client.get(f"/api/ota/firmware/{'0' * 64}/firmware.bin").status_code == 404
        )


@pytest.mark.parametrize(
    "change",
    [
        "signature",
        "key",
        "image",
        "length",
        "profile",
        "layout",
        "vectors",
        "oversize",
        "duplicate",
    ],
)
def test_bad_assets_fail_startup(assets, change):
    if change == "signature":
        signature = bytearray((assets / "manifest.sig").read_bytes())
        signature[-1] ^= 1
        (assets / "manifest.sig").write_bytes(signature)
    elif change == "key":
        (assets / "public-key.der").write_bytes(b"not the trust key")
    elif change in ("image", "length", "vectors"):
        image = bytearray((assets / "firmware.bin").read_bytes())
        if change == "length":
            image.pop()
        elif change == "vectors":
            image[:8] = bytes(8)
            value = json.loads((assets / "manifest.json").read_bytes())
            value["sha256"] = hashlib.sha256(image).hexdigest()
            sign(assets, json.dumps(value).encode())
        else:
            image[-1] ^= 1
        (assets / "firmware.bin").write_bytes(image)
    elif change == "oversize":
        (assets / "manifest.json").write_bytes(b" " * 2049)
    else:
        value = json.loads((assets / "manifest.json").read_bytes())
        if change == "duplicate":
            raw = b'{"protocol":1,' + json.dumps(value).encode()[1:]
        else:
            value[change] = "micropython"
            raw = json.dumps(value).encode()
        sign(assets, raw)
    with pytest.raises((ValueError, InvalidSignature)), TestClient(get_app()):
        pass


def sign(directory, raw):
    (directory / "manifest.json").write_bytes(raw)
    key = ec.derive_private_key(1, ec.SECP256R1())
    (directory / "manifest.sig").write_bytes(key.sign(raw, ec.ECDSA(hashes.SHA256())))


def test_missing_assets_and_incomplete_directory(tmp_path, monkeypatch):
    directory = tmp_path / "rust"
    monkeypatch.setenv("WEATHER_RUST_OTA_DIR", str(directory))
    rust_ota.get_rust_package.cache_clear()
    assert ota.root_header(rust_ota.PROFILE) == {}
    rust_ota.get_rust_package.cache_clear()
    directory.mkdir()
    with pytest.raises(FileNotFoundError):
        rust_ota.get_rust_package()
    rust_ota.get_rust_package.cache_clear()


def test_fleet_telemetry_survives_old_clients_and_discovery_on_503(assets):
    app = get_app()
    registry, cache = app.state.fleet()
    cache.start = lambda: None
    cache.get = AsyncMock(side_effect=ValueError("test render failure"))
    headers = {
        "X-Weather-Device-ID": "abcd",
        "X-Weather-Display": "inky-frame-5.7",
        "X-Weather-OTA-Firmware-Product": "weather-dash-rs",
        "X-Weather-Firmware-Version": "0.2.0",
        "X-Weather-Firmware-SHA256": "1" * 64,
        "X-Weather-OTA-Status": "rolled_back",
        "X-Weather-OTA-Target": "2" * 64,
    }
    path = f"/api/screenshot?width=600&height=448&image_format=inky-57-raw&ota_profile={rust_ota.PROFILE}"
    with TestClient(app) as client:
        assert client.get(path, headers=headers).status_code == 200
        registry.configure(
            "abcd",
            PanelSettings(
                display="inky-frame-5.7", lat=10, long=20, panel_profile="acep"
            ),
        )
        response = client.get(path, headers=headers)
        assert response.status_code == 503
        assert (
            response.headers["X-Weather-OTA-Root"] == rust_ota.get_rust_package().root
        )
        panel = client.get("/admin/api/panels/abcd").json()
        assert panel["firmware_product"] == "weather-dash-rs"
        assert panel["firmware_version"] == "0.2.0"
        assert panel["ota_status"] == "rolled_back"
        assert panel["ota_target"] == "2" * 64
        client.get(
            "/api/screenshot?width=600&height=448",
            headers={"X-Weather-Device-ID": "abcd"},
        )
        assert registry.get("abcd")["firmware_sha256"] == "1" * 64
        assert (
            client.get(
                path,
                headers={**headers, "X-Weather-OTA-Firmware-Product": "micropython"},
            ).status_code
            == 422
        )
        assert (
            client.get(
                path, headers={**headers, "X-Weather-Firmware-SHA256": "bad"}
            ).status_code
            == 422
        )


def test_additive_database_migration(tmp_path):
    with sqlite3.connect(tmp_path / "panels.sqlite3") as db:
        db.execute("""CREATE TABLE panels (id TEXT PRIMARY KEY, friendly_name TEXT NOT NULL DEFAULT '',
            registered_at INTEGER NOT NULL, last_seen INTEGER NOT NULL, width INTEGER NOT NULL,
            height INTEGER NOT NULL, reported_version TEXT, config TEXT NOT NULL)""")
    registry = Registry(tmp_path)
    registry.register("abcd", 600, 448, None)
    assert registry.get("abcd")["firmware_version"] is None
    assert Registry(tmp_path).get("abcd")["firmware_product"] is None


def test_private_download_redirect_drops_authorization():
    spec = importlib.util.spec_from_file_location(
        "fetch", Path(__file__).parents[1] / "scripts/fetch-rust-firmware.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    request = module.urllib.request.Request(
        "https://api.github.com/repos/test/assets/1",
        headers={"Authorization": "Bearer test"},
    )
    redirected = module.SafeRedirect().redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "https://release-assets.githubusercontent.com/test",
    )
    assert not redirected.has_header("Authorization")


def test_production_download_requires_pin(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "fetch", Path(__file__).parents[1] / "scripts/fetch-rust-firmware.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lock = tmp_path / "lock.json"
    lock.write_text("null")
    assert not module.fetch(lock, tmp_path / "out", FIXTURE / "public-key.der")
    with pytest.raises(ValueError, match="pinned"):
        module.fetch(lock, tmp_path / "out", FIXTURE / "public-key.der", True)


@pytest.mark.parametrize("unsafe", [False, True])
@pytest.mark.parametrize("lock_kind", ["url", "tag", "wrong_version"])
def test_archive_download_is_pinned_verified_and_rejects_paths(
    tmp_path, monkeypatch, unsafe, lock_kind
):
    import io
    import tarfile

    spec = importlib.util.spec_from_file_location(
        "fetch", Path(__file__).parents[1] / "scripts/fetch-rust-firmware.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as archive:
        for path in FIXTURE.iterdir():
            raw = path.read_bytes()
            info = tarfile.TarInfo(
                "../firmware.bin"
                if unsafe and path.name == "firmware.bin"
                else path.name
            )
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
    raw = data.getvalue()
    asset_url = f"https://api.github.com/repos/{module.REPOSITORY}/releases/assets/1"
    digest = hashlib.sha256(raw).hexdigest()
    tag = "v0.3.0" if lock_kind == "wrong_version" else "v0.2.0"
    release = {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": module.ASSET_NAME,
                "state": "uploaded",
                "url": asset_url,
                "digest": "sha256:" + digest,
            }
        ],
    }

    class Opener:
        def open(self, request, timeout):
            assert request.headers["Authorization"] == "Bearer fixture-token"
            assert timeout == 60
            if "/releases/tags/" in request.full_url:
                assert request.headers["Accept"] == "application/vnd.github+json"
                return io.BytesIO(json.dumps(release).encode())
            assert request.headers["Accept"] == "application/octet-stream"
            return io.BytesIO(raw)

    monkeypatch.setenv("RUST_FIRMWARE_READ_TOKEN", "fixture-token")
    monkeypatch.setattr(module.urllib.request, "build_opener", lambda *args: Opener())
    lock = tmp_path / "lock.json"
    lock_value = {
        "url" if lock_kind == "url" else "tag": asset_url
        if lock_kind == "url"
        else tag,
        "sha256": digest,
    }
    lock.write_text(json.dumps(lock_value))
    output = tmp_path / "package"
    if unsafe:
        with pytest.raises(ValueError, match="Unexpected"):
            module.fetch(lock, output, FIXTURE / "public-key.der", True)
        assert not output.exists()
    elif lock_kind == "wrong_version":
        with pytest.raises(ValueError, match="Signed firmware version"):
            module.fetch(lock, output, FIXTURE / "public-key.der", True)
        assert not output.exists()
    else:
        assert module.fetch(lock, output, FIXTURE / "public-key.der", True)
        assert (output / "firmware.bin").read_bytes() == (
            FIXTURE / "firmware.bin"
        ).read_bytes()
        lock_value["sha256"] = "0" * 64
        lock.write_text(json.dumps(lock_value))
        with pytest.raises(ValueError, match="SHA-256"):
            module.fetch(lock, tmp_path / "other", FIXTURE / "public-key.der", True)


@pytest.mark.parametrize(
    "failure",
    [
        "draft",
        "prerelease",
        "wrong_tag",
        "duplicate",
        "missing",
        "wrong_url",
        "wrong_hash",
        "invalid_tag",
    ],
)
def test_release_resolution_rejects_unusable_assets(monkeypatch, failure):
    spec = importlib.util.spec_from_file_location(
        "fetch", Path(__file__).parents[1] / "scripts/fetch-rust-firmware.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    url = f"https://api.github.com/repos/{module.REPOSITORY}/releases/assets/1"
    asset = {
        "name": module.ASSET_NAME,
        "state": "uploaded",
        "url": url,
        "digest": "sha256:" + "1" * 64,
    }
    release = {
        "tag_name": "v0.2.0",
        "draft": False,
        "prerelease": False,
        "assets": [asset],
    }
    if failure in ("draft", "prerelease"):
        release[failure] = True
    elif failure == "wrong_tag":
        release["tag_name"] = "v0.3.0"
    elif failure == "duplicate":
        release["assets"].append(asset)
    elif failure == "missing":
        release["assets"] = []
    elif failure == "wrong_url":
        asset["url"] = "https://example.com/firmware.tar"
    elif failure == "wrong_hash":
        asset["digest"] = "sha256:" + "2" * 64
    monkeypatch.setattr(module, "download", lambda *args: json.dumps(release).encode())
    with pytest.raises(ValueError):
        module.release_url(
            "../../bad" if failure == "invalid_tag" else "v0.2.0", "1" * 64
        )
