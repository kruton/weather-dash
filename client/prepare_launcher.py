"""Build a weather launcher from an Inky-Frame checkout (host Python only)."""

import argparse
from pathlib import Path
import shutil
import subprocess


def prepare(source, output):
    client = Path(__file__).resolve().parent
    source, output = Path(source).resolve(), Path(output).resolve()
    if source != output:
        shutil.copytree(source, output, dirs_exist_ok=True)
    patch = client / "launcher.patch"
    command = ["patch", "--batch", "--forward", "-p1", "-i", str(patch)]
    check = subprocess.run(command + ["--dry-run"], cwd=output, capture_output=True)
    if check.returncode == 0:
        subprocess.run(command, cwd=output, check=True)
    else:
        # Allow repeated builds, but fail if upstream changed the patch context.
        reverse = subprocess.run(
            ["patch", "--batch", "--reverse", "--dry-run", "-p1", "-i", str(patch)],
            cwd=output, capture_output=True,
        )
        if reverse.returncode != 0:
            raise RuntimeError("Launcher patch does not match this checkout:\n"
                               + check.stdout.decode() + check.stderr.decode())
    shutil.copy2(client / "weather.py", output / "weather.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="examples/inkylauncher directory")
    parser.add_argument("--output", type=Path, required=True,
                        help="Output directory; may equal source for CI builds")
    args = parser.parse_args()
    prepare(args.source, args.output)
