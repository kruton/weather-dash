"""Compile one portable script package and sign its canonical manifest."""
import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import ota_protocol as protocol
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from prepare_launcher import prepare

CLIENT = Path(__file__).resolve().parent


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def build(source, mrequests, compiler, output, key):
    output = Path(output)
    if output.exists():
        shutil.rmtree(output)
    scripts = output / "scripts"
    scripts.mkdir(parents=True)
    files = {}
    with tempfile.TemporaryDirectory() as temp:
        prepared = Path(temp) / "launcher"
        prepare(source, prepared)
        launcher = (prepared / "main.py").read_text()
        # The launcher is imported from a selected slot by the fixed main.py.
        launcher = launcher.replace("graphics = PicoGraphics(DISPLAY)\n", "graphics = PicoGraphics(DISPLAY)\ngraphics.set_blocking(True)\n")
        launcher = launcher.replace("import gc\n", "import gc\nimport ota_boot\n", 1)
        launcher = launcher.replace("    graphics.update()\n", "    graphics.set_blocking(True)\n    graphics.update()\n    ota_boot.confirm()\n", 1)
        launcher = launcher.replace("    ih.app.draw()\n", "    ih.app.draw()\n    ota_boot.confirm()\n")
        launcher += "    ota_boot.reset_if_pending()\n"
        (prepared / "launcher.py").write_text(launcher)
        sources = {"launcher.mpy": prepared / "launcher.py",
                   "inky_helper.mpy": prepared / "inky_helper.py",
                   "weather.mpy": CLIENT / "weather.py", "ota.mpy": CLIENT / "ota.py",
                   "panel_config.mpy": CLIENT / "panel_config.py"}
        for path in sorted(Path(mrequests).glob("*.py")):
            sources["lib/mrequests/" + path.with_suffix(".mpy").name] = path
        if "lib/mrequests/__init__.mpy" not in sources:
            raise ValueError("Missing mrequests package")
        for relative, source_path in sorted(sources.items()):
            destination = scripts / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Portable bytecode, 31 bit small ints, diagnostics retained, stable
            # source names independent of checkout path and runner platform.
            subprocess.run([str(compiler), "-O0", "-msmall-int-bits=31", "-s",
                            relative.replace(".mpy", ".py"), "-o", str(destination),
                            str(source_path)], check=True)
            data = destination.read_bytes()
            if data[:2] != b"M\x06" or data[2] & 0xfc or data[3] > 31:
                raise ValueError("Compiler produced incompatible bytecode")
            files[relative] = {"size": len(data), "sha256": protocol.digest(data)}
    script_hashes = {path: info["sha256"] for path, info in files.items()}
    manifest = {"protocol": 1, "profile": protocol.PROFILE,
                "firmware": "inky-ota-v1-micropython-1.29.0",
                "mpy_version": 6, "small_int_bits": 31,
                "root": protocol.merkle_root(script_hashes), "files": files}
    protocol.validate_manifest(manifest)
    raw = canonical(manifest)
    if len(raw) > protocol.MAX_MANIFEST:
        raise ValueError("Manifest too large")
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise TypeError("Signing key must be ECDSA P-256")
    (output / "manifest.json").write_bytes(raw)
    (output / "manifest.sig").write_bytes(key.sign(raw, ec.ECDSA(hashes.SHA256())))
    public = key.public_key().public_bytes(serialization.Encoding.DER,
                                          serialization.PublicFormat.SubjectPublicKeyInfo)
    (output / "public-key.der").write_bytes(public)
    (output / "hashes.py").write_text(protocol.hashes_source(manifest["root"], script_hashes))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--mrequests", required=True, type=Path)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args()
    pem = os.environ.get("OTA_SIGNING_KEY")
    if args.production and not pem:
        raise SystemExit("Production package requires the OTA_SIGNING_KEY secret")
    key = (serialization.load_pem_private_key(pem.encode(), password=None) if pem
           else ec.generate_private_key(ec.SECP256R1()))
    build(args.source, args.mrequests, args.compiler, args.output, key)
