"""Build a weather launcher from an Inky-Frame checkout (host Python only)."""

import argparse
import shutil
import subprocess
from pathlib import Path


def prepare(source, output):
    client = Path(__file__).resolve().parent
    source, output = Path(source).resolve(), Path(output).resolve()
    if source != output:
        shutil.copytree(source, output, dirs_exist_ok=True)
    old = (
        "from picographics import \\\n"
        '    DISPLAY_INKY_FRAME_SPECTRA_7 as DISPLAY  # 7.3" Spectra'
    )
    replacement = "import panel_config\nDISPLAY = panel_config.display_driver()"
    launcher_path = output / "main.py"
    original = launcher_path.read_text()
    normalized = original.replace(replacement, old)
    normalized = normalized.replace(
        "        ih.app.BATTERY = panel_config.battery_reading()\n", ""
    )
    normalized = normalized.replace("    panel_config.reset_if_display_changed()\n", "")
    launcher_path.write_text(normalized)
    patch = client / "launcher.patch"
    command = ["patch", "--batch", "--forward", "-p1", "-i", str(patch)]
    check = subprocess.run(
        command + ["--dry-run"], cwd=output, capture_output=True, check=False
    )
    if check.returncode == 0:
        subprocess.run(command, cwd=output, check=True)
    else:
        # Allow repeated builds, but fail if upstream changed the patch context.
        reverse = subprocess.run(
            ["patch", "--batch", "--reverse", "--dry-run", "-p1", "-i", str(patch)],
            cwd=output,
            capture_output=True,
            check=False,
        )
        if reverse.returncode != 0:
            launcher_path.write_text(original)
            raise RuntimeError(
                "Launcher patch does not match this checkout:\n"
                + check.stdout.decode()
                + check.stderr.decode()
            )
    launcher_path = output / "main.py"
    launcher = launcher_path.read_text()
    if old in launcher:
        launcher = launcher.replace(old, replacement)
    elif replacement not in launcher:
        raise ValueError("Unknown launcher display configuration")
    launcher = launcher.replace(
        "        ih.app.BATTERY = panel_config.battery_reading()\n", ""
    )
    launcher = launcher.replace("    panel_config.reset_if_display_changed()\n", "")
    launcher = launcher.replace(
        "        if WIFI_SSID is not None:\n",
        "        ih.app.BATTERY = panel_config.battery_reading()\n        if WIFI_SSID is not None:\n",
    )
    launcher = launcher.replace(
        "    ih.sleep(ih.app.UPDATE_INTERVAL)\n",
        "    ih.sleep(ih.app.UPDATE_INTERVAL)\n    panel_config.reset_if_display_changed()\n",
    )
    launcher_path.write_text(launcher)
    shutil.copy2(client / "weather.py", output / "weather.py")
    shutil.copy2(client / "panel_config.py", output / "panel_config.py")
    if not (output / "weather_config.py").exists():
        shutil.copy2(client / "weather_config.py", output / "weather_config.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="examples/inkylauncher directory")
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output directory; may equal source for CI builds",
    )
    args = parser.parse_args()
    prepare(args.source, args.output)
