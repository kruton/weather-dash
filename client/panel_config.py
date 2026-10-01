"""Server-owned settings cached outside signed OTA slots (MicroPython)."""

import binascii
import json
import os

import machine

PATH = "/panel_config.json"
DISPLAY = "inky-frame-spectra-7"
DISPLAYS = ("inky-frame-spectra-7", "inky-frame-5.7")
PROFILES = ("spectra6", "spectra6-boeber", "acep", "generic-2-color-eink", "none")
MAX_HEADER = 4096
current = None
try:
    from weather_config import HARDWARE_DISPLAY
except ImportError:
    HARDWARE_DISPLAY = DISPLAY
if HARDWARE_DISPLAY not in DISPLAYS:
    raise ValueError("Unsupported hardware display")
active_display = HARDWARE_DISPLAY


def normalize(value):
    # MicroPython's JSON decoder leaves ASCII-escaped UTF-16 pairs separate.
    # Combine them before validating length or persisting UTF-8 location names.
    if not isinstance(value, dict) or not isinstance(value.get("config"), dict):
        return value
    name = value["config"].get("name")
    if not isinstance(name, str):
        return value
    output = []
    index = 0
    while index < len(name):
        code = ord(name[index])
        if 0xD800 <= code <= 0xDBFF:
            index += 1
            if index >= len(name) or not 0xDC00 <= ord(name[index]) <= 0xDFFF:
                raise ValueError("Unpaired Unicode surrogate")
            code = 0x10000 + ((code - 0xD800) << 10) + ord(name[index]) - 0xDC00
        elif 0xDC00 <= code <= 0xDFFF:
            raise ValueError("Unpaired Unicode surrogate")
        output.append(chr(code))
        index += 1
    value["config"]["name"] = "".join(output)
    return value


def valid(value):
    if not isinstance(value, dict) or set(value) != {"schema", "version", "config"}:
        return False
    version = value["version"]
    config = value["config"]
    if (
        value["schema"] != 1
        or not isinstance(version, str)
        or len(version) != 64
        or any(c not in "0123456789abcdef" for c in version)
        or not isinstance(config, dict)
        or set(config)
        != {
            "configured",
            "display",
            "panel_profile",
            "name",
            "lat",
            "long",
            "battery_type",
            "battery_cells",
        }
        or type(config["configured"]) is not bool
        or config["display"] not in DISPLAYS
        or config["panel_profile"] not in PROFILES
        or (config["panel_profile"] == "acep" and config["display"] != "inky-frame-5.7")
        or (config["panel_profile"] == "none" and config["display"] == "inky-frame-5.7")
        or (config["panel_profile"] in ("spectra6", "spectra6-boeber")
            and config["display"] != DISPLAY)
        or not isinstance(config["name"], str)
        or len(config["name"]) > 160
        or config["battery_type"] not in ("unknown", "alkaline", "li-poly", "li-ion")
        or type(config["battery_cells"]) is not int
        or not 1 <= config["battery_cells"] <= 4
        or (
            config["battery_type"] in ("li-poly", "li-ion")
            and config["battery_cells"] != 1
        )
    ):
        return False
    if config["configured"]:
        lat, longitude = config["lat"], config["long"]
        return (
            type(lat) in (int, float)
            and -90 <= lat <= 90
            and type(longitude) in (int, float)
            and -180 <= longitude <= 180
        )
    return config["lat"] is None and config["long"] is None


def load():
    global current, active_display
    current = None
    try:
        with open(PATH) as f:
            raw = f.read(MAX_HEADER + 1)
        value = normalize(json.loads(raw)) if len(raw) <= MAX_HEADER else None
        if valid(value) and value["config"]["display"] == HARDWARE_DISPLAY:
            current = value
    except (OSError, ValueError, TypeError):
        pass
    active_display = HARDWARE_DISPLAY
    return current


def display_driver():
    load()
    if HARDWARE_DISPLAY == "inky-frame-5.7":
        from picographics import DISPLAY_INKY_FRAME
        return DISPLAY_INKY_FRAME
    from picographics import DISPLAY_INKY_FRAME_SPECTRA_7
    return DISPLAY_INKY_FRAME_SPECTRA_7


def apply(headers):
    global current
    try:
        values = [
            header.split(b":", 1)[1].strip()
            for header in headers
            if header.split(b":", 1)[0].lower() == b"x-weather-config"
        ]
        if not values:
            return False
        if len(values) != 1 or len(values[0]) > MAX_HEADER:
            return False
        value = normalize(json.loads(values[0].decode()))
        if (not valid(value) or value["config"]["display"] != HARDWARE_DISPLAY
                or value == current):
            return False
        with open(PATH + ".tmp", "w") as f:
            json.dump(value, f)
        if hasattr(os, "sync"):
            os.sync()
        os.rename(PATH + ".tmp", PATH)
        if hasattr(os, "sync"):
            os.sync()
        current = value
        return True
    except (OSError, ValueError, TypeError, KeyError):
        return False


def request_headers(battery=None):
    headers = {
        b"accept": (b"application/octet-stream" if HARDWARE_DISPLAY == "inky-frame-5.7"
                    else b"image/png"),
        b"X-Weather-Device-ID": binascii.hexlify(machine.unique_id()),
        b"X-Weather-Display": HARDWARE_DISPLAY.encode(),
    }
    if current:
        headers[b"X-Weather-Config-Version"] = current["version"].encode()
    if battery:
        voltage, source = battery
        headers[b"X-Weather-Battery-Voltage"] = f"{voltage:.3f}".encode()
        if source:
            headers[b"X-Weather-Power-Source"] = source.encode()
    return headers


def battery_reading():
    """Read VSYS before Wi-Fi is enabled; its ADC pin shares the radio bus.

    Reports volts, not a chemistry-dependent estimate of percentage remaining.
    See Pimoroni's Inky Frame battery example by helgibbons.
    """
    try:
        source = "usb" if machine.Pin("WL_GPIO2", machine.Pin.IN).value() else "battery"
        machine.Pin(25, machine.Pin.OUT, value=1)
        adc = machine.ADC(29)
        adc.read_u16()  # Discard the first sample after enabling the divider.
        voltage = sum(adc.read_u16() for _ in range(8)) * (3 * 3.3 / 65535 / 8)
        return (voltage, source) if 1 <= voltage <= 6 else None
    except (AttributeError, OSError, ValueError, TypeError):
        return None


def reset_if_display_changed():
    if current and current["config"]["display"] != active_display:
        machine.reset()


load()
