import json
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from weather_dash import get_app, ota
from weather_dash import ota_protocol as protocol


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    scripts = {p: b"M\x06\x03\x1f" + p.encode() for p in
               ("launcher.mpy", "inky_helper.mpy", "weather.mpy", "ota.mpy")}
    files = {p: {"size": len(d), "sha256": protocol.digest(d)} for p, d in sorted(scripts.items())}
    manifest = {"protocol": 1, "profile": protocol.PROFILE,
                "firmware": "inky-ota-v1-micropython-1.29.0",
                "mpy_version": 6, "small_int_bits": 31, "files": files,
                "root": protocol.merkle_root({p: i["sha256"] for p, i in files.items()})}
    raw = json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode()
    (tmp_path / "manifest.json").write_bytes(raw)
    (tmp_path / "manifest.sig").write_bytes(key.sign(raw, ec.ECDSA(hashes.SHA256())))
    (tmp_path / "public-key.der").write_bytes(key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo))
    (tmp_path / "scripts").mkdir()
    for p, d in scripts.items():
        (tmp_path / "scripts" / p).write_bytes(d)
    monkeypatch.setenv("WEATHER_OTA_DIR", str(tmp_path))
    ota.get_package.cache_clear()
    yield tmp_path, manifest
    ota.get_package.cache_clear()


def test_profile_root_header(bundle):
    _, manifest = bundle
    assert ota.root_header(protocol.PROFILE) == {"X-Weather-OTA-Root": manifest["root"]}
    assert ota.root_header(None) == {}
    assert ota.root_header("other") == {}


def test_delta_response_and_current_no_content(bundle):
    _, manifest = bundle
    hashes_map = {p: i["sha256"] for p, i in manifest["files"].items()}
    request = {"profile": protocol.PROFILE, "root": manifest["root"], "script_hashes": hashes_map}
    with TestClient(get_app()) as client:
        assert client.post("/api/ota/update", json=request).status_code == 204
        hashes_map.pop("weather.mpy")
        hashes_map["removed.mpy"] = "0" * 64
        response = client.post("/api/ota/update", json=request)
    assert response.status_code == 200
    assert response.headers["content-type"] == "multipart/mixed; boundary=weather-ota-v1"
    assert b"X-OTA-Path: manifest.json" in response.content
    assert b"X-OTA-Path: manifest.sig" in response.content
    assert b"X-OTA-Path: weather.mpy" in response.content
    assert b"X-OTA-Path: ota.mpy" not in response.content
    assert b"X-OTA-Path: removed.mpy" not in response.content


def test_stale_incompatible_and_bad_requests(bundle):
    _, manifest = bundle
    request = {"profile": protocol.PROFILE, "root": manifest["root"], "script_hashes": {}}
    with TestClient(get_app()) as client:
        assert client.post("/api/ota/update", json={**request, "root": "0" * 64}).status_code == 409
        assert client.post("/api/ota/update", json={**request, "profile": "other"}).status_code == 409
        assert client.post("/api/ota/update", json={**request, "script_hashes": {"../x.mpy": "0" * 64}}).status_code == 422
        assert client.post("/api/ota/update", content=b"bad json").status_code == 422
        assert client.post("/api/ota/update", content=b"x" * 16385).status_code == 413


def test_no_assets_no_ota(tmp_path, monkeypatch):
    monkeypatch.setenv("WEATHER_OTA_DIR", str(tmp_path))
    ota.get_package.cache_clear()
    with TestClient(get_app()) as client:
        assert client.post("/api/ota/update", json={}).status_code == 404
        assert ota.root_header(protocol.PROFILE) == {}
    ota.get_package.cache_clear()


def test_corrupt_deployment_fails_validation(bundle):
    directory, _ = bundle
    (directory / "scripts/weather.mpy").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="Corrupt"):
        ota.Package(directory)


def test_invalid_signature_fails_validation(bundle):
    from cryptography.exceptions import InvalidSignature
    directory, _ = bundle
    (directory / "manifest.sig").write_bytes(b"x" * 70)
    with pytest.raises(InvalidSignature):
        ota.Package(directory)


def test_client_consumes_real_server_multipart(bundle, tmp_path, monkeypatch):
    import importlib.util
    import sys
    from types import SimpleNamespace
    client_path = Path(__file__).resolve().parents[1] / "client"
    with patch.object(sys, "path", [str(client_path), *sys.path]):
        import ota_boot as boot
        spec = importlib.util.spec_from_file_location("device_ota", client_path / "ota.py")
        device = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(device)
    directory, manifest = bundle
    public = serialization.load_der_public_key((directory / "public-key.der").read_bytes())
    def verify(raw, signature):
        public.verify(signature, raw, ec.ECDSA(hashes.SHA256()))
        return True
    base = tmp_path / "device"
    (base / "a").mkdir(parents=True)
    monkeypatch.setattr(boot, "BASE", str(base))
    monkeypatch.setattr(boot, "STATE", str(base / "state.json"))
    monkeypatch.setattr(boot, "state", {"active": "a"})
    monkeypatch.setattr(boot, "slot", "a")
    monkeypatch.setattr(boot, "script_hashes", {})
    boot.write_state(boot.state)
    package = ota.get_package()
    import io
    stream = io.BytesIO(b"".join(package.multipart({})))
    with patch.dict(sys.modules, {"ota_verify": SimpleNamespace(verify=verify)}):
        device.install(stream, manifest["root"])
    assert boot.read_state()["pending"] == "b"
    assert (base / "b/weather.mpy").read_bytes() == (directory / "scripts/weather.mpy").read_bytes()


def test_shared_protocol_matches_frozen_client():
    root = Path(__file__).resolve().parents[1]
    assert (root / "client/ota_protocol.py").read_bytes() == (root / "src/weather_dash/ota_protocol.py").read_bytes()
