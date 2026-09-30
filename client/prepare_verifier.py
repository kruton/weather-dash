"""Prepare a native verifier for a unix MicroPython test build."""
import argparse
import shutil
from pathlib import Path


def prepare(bundle, output):
    output = Path(output) / "ota_verify"
    shutil.copytree(Path(__file__).parent / "native/ota_verify", output, dirs_exist_ok=True)
    public = (Path(bundle) / "public-key.der").read_bytes()
    (output / "ota_key.h").write_text("static const unsigned char ota_public_key[] = {"
        + ",".join(str(b) for b in public) + "};\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(args.bundle, args.output)
