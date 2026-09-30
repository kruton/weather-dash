"""Install a prebuilt signed package and frozen recovery code into an Inky build."""
import argparse
import json
import shutil
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

import ota_protocol as protocol

CLIENT = Path(__file__).resolve().parent


def install(inky, bundle):
    inky, bundle = Path(inky).resolve(), Path(bundle).resolve()
    raw = (bundle / "manifest.json").read_bytes()
    signature = (bundle / "manifest.sig").read_bytes()
    public_bytes = (bundle / "public-key.der").read_bytes()
    public = serialization.load_der_public_key(public_bytes)
    if not isinstance(public, ec.EllipticCurvePublicKey) or not isinstance(public.curve, ec.SECP256R1):
        raise TypeError("Expected P-256 public key")
    public.verify(signature, raw, ec.ECDSA(hashes.SHA256()))
    manifest = json.loads(raw)
    script_hashes = protocol.validate_manifest(manifest)
    for path, info in manifest["files"].items():
        data = (bundle / "scripts" / path).read_bytes()
        if len(data) != info["size"] or protocol.digest(data) != info["sha256"]:
            raise ValueError("Corrupt package: " + path)
    launcher = inky / "examples/inkylauncher"
    # The root launcher must not shadow slot modules. Other legacy apps remain.
    for name in ("main.py", "launcher.py", "launcher.mpy", "weather.py", "weather.mpy", "inky_helper.py", "inky_helper.mpy"):
        (launcher / name).unlink(missing_ok=True)
    slot = launcher / "ota/a"
    if slot.exists():
        shutil.rmtree(slot)
    shutil.copytree(bundle / "scripts", slot)
    for name in ("manifest.json", "manifest.sig", "hashes.py"):
        shutil.copy2(bundle / name, slot / name)
    if (slot / "hashes.py").read_text() != protocol.hashes_source(manifest["root"], script_hashes):
        raise ValueError("Invalid hash metadata")
    (launcher / "ota/state.json").write_text('{"active":"a"}\n')
    (launcher / "main.py").write_text("import ota_boot\nota_boot.run()\n")
    if not (launcher / "weather_config.py").exists():
        shutil.copy2(CLIENT / "weather_config.py", launcher / "weather_config.py")
    native = inky / "ota_native"
    shutil.copytree(CLIENT / "native/ota_verify", native, dirs_exist_ok=True)
    (native / "ota_key.h").write_text("static const unsigned char ota_public_key[] = {"
        + ",".join(str(b) for b in public_bytes) + "};\n")
    frozen = inky / "modules/ota"
    frozen.mkdir(parents=True, exist_ok=True)
    for name in ("ota_boot.py", "ota_protocol.py"):
        shutil.copy2(CLIENT / name, frozen / name)
    cmake = inky / "boards/usermod-common.cmake"
    directive = '\ninclude(${CMAKE_CURRENT_LIST_DIR}/../ota_native/micropython.cmake)\n'
    if directive not in cmake.read_text():
        cmake.write_text(cmake.read_text() + directive)
    common = inky / "boards/manifest-common.py"
    directive = '\nfreeze("../modules/ota", ("ota_boot.py", "ota_protocol.py"))\n'
    if directive not in common.read_text():
        common.write_text(common.read_text() + directive)
    # Explicit nested paths let dir2uf2 create each real parent directory;
    # wildcard parents would otherwise create literal '**' directories.
    entries = ["*.py", "ota/state.json"]
    entries += sorted(str(p.relative_to(launcher)) for directory in (launcher / "lib", slot)
                      for p in directory.rglob("*") if p.is_file())
    for board in ("pico_w_inky", "pico2_w_inky"):
        (inky / "boards" / board / "manifest.txt").write_text("\n".join(entries))



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inky", type=Path)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    install(args.inky, args.bundle)
