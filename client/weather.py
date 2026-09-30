import gc
import uos
import machine
import time
import pngdec
import sdcard
import mrequests as requests

"""
Weather

You *must* insert an SD card into Inky Frame!
We need somewhere to save the jpg for display.
"""

from weather_config import NAME, LAT, LONG, URL

FALLBACK_UPDATE_INTERVAL = 240  # Minutes between updates if time sync fails
UPDATE_INTERVAL = FALLBACK_UPDATE_INTERVAL  # Launcher reads this after draw()
clock_synced = False
next_refresh = None
# HTTP timestamps use Unix seconds; older MicroPython builds use a 2000 epoch.
UNIX_EPOCH_OFFSET = 946684800 if time.gmtime(0)[0] == 2000 else 0


graphics = None
WIDTH = None
HEIGHT = None


gc.collect()  # We're really gonna need that RAM!

FILENAME = "/sd/weather.png"

err_string = None
sd_spi = machine.SPI(
    0,
    sck=machine.Pin(18, machine.Pin.OUT),
    mosi=machine.Pin(19, machine.Pin.OUT),
    miso=machine.Pin(16, machine.Pin.OUT),
)
sd = sdcard.SDCard(sd_spi, machine.Pin(22))
uos.mount(sd, "/sd")
gc.collect()  # Claw back some RAM!

def url_escape(s):
    return ''.join(c if c.isalpha() or c.isdigit() else '%%%02x' % ord(c) for c in s)


def sync_clock(headers):
    # Reuse the image response: no separate NTP request or connection.
    date = None
    server_time = None
    age = 0
    try:
        for header in headers:
            name, value = header.split(b":", 1)
            if name.lower() == b"date":
                date = value.strip().split()
            elif name.lower() == b"x-weather-time":
                server_time = int(value.strip()) - UNIX_EPOCH_OFFSET
            elif name.lower() == b"age":
                age = max(0, int(value.strip()))
        if server_time is not None:
            tm = time.gmtime(server_time + age)
            if not 2024 <= tm[0] < 2100:
                return False
            machine.RTC().datetime((tm[0], tm[1], tm[2], tm[6] + 1,
                                    tm[3], tm[4], tm[5], 0))
            return True
        if date is None or len(date) != 6 or date[5] != b"GMT":
            return False
        months = (b"Jan", b"Feb", b"Mar", b"Apr", b"May", b"Jun",
                  b"Jul", b"Aug", b"Sep", b"Oct", b"Nov", b"Dec")
        year, month, day = int(date[3]), months.index(date[2]) + 1, int(date[1])
        hour, minute, second = (int(part) for part in date[4].split(b":"))
        days = (31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
                else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
        if not (year >= 2024 and 1 <= day <= days[month - 1]
                and 0 <= hour < 24 and 0 <= minute < 60 and 0 <= second < 60):
            return False
        timestamp = time.mktime((year, month, day, hour, minute, second, 0, 0))
        tm = time.gmtime(timestamp + age)
        machine.RTC().datetime((tm[0], tm[1], tm[2], tm[6] + 1,
                                tm[3], tm[4], tm[5], 0))
        return True
    except (ValueError, TypeError, OSError, OverflowError):
        return False


def response_next_refresh(headers, now):
    try:
        for header in headers:
            name, value = header.split(b":", 1)
            if name.lower() == b"x-weather-next-refresh":
                timestamp = int(value.strip()) - UNIX_EPOCH_OFFSET
                if 0 < timestamp - now <= 26 * 3600:
                    return timestamp
                return None
    except (ValueError, TypeError, OverflowError):
        pass
    return None


def minutes_until_refresh(now):
    if next_refresh is None:
        return FALLBACK_UPDATE_INTERVAL
    # If drawing crossed the target, retry in one minute rather than sleeping
    # through the morning refresh. Otherwise round up to whole RTC minutes.
    return max(1, int((next_refresh - now + 59) // 60))


def update():
    global err_string, clock_synced, next_refresh

    clock_synced = False
    next_refresh = None

    location = url_escape(NAME)
    url = f"{URL}/api/screenshot?lat={LAT}&long={LONG}&name={location}&width={WIDTH}&height={HEIGHT}"
    print(f"weather update to {FILENAME} from {url}")

    ota_root = None
    ota_enabled = False
    try:
        import ota_boot
        from ota_protocol import PROFILE
        ota_enabled = ota_boot.state is not None
        if ota_enabled:
            url += "&ota_profile=" + PROFILE
    except ImportError:
        pass  # Existing, non-OTA firmware keeps working.
    r = None
    try:
        r = requests.get(url, headers={b"accept": b"image/png"}, save_headers=True)
        clock_synced = sync_clock(r.headers)
        if not clock_synced:
            print("No valid response time; using four-hour refresh interval")
        if r.status_code == 200:
            target = response_next_refresh(r.headers, time.time()) if clock_synced else None
            buf = bytearray(1024)
            r.save(FILENAME, buf=buf)
            next_refresh = target
            for header in r.headers:
                name, value = header.split(b":", 1)
                if name.lower() == b"x-weather-ota-root":
                    ota_root = value.strip().decode()
            print(f"Image saved to '{FILENAME}'.")
        else:
            print(f"Request failed. Status: {r.status_code}")
    except:
        err_string = "Error fetching"
        print("Error fetching")
    finally:
        if r is not None:
            r.close()
    print(f"finished fetching image to {FILENAME}")
    gc.collect()  # We really are tight on RAM!
    if (ota_root is not None and ota_enabled
            and ota_root != ota_boot.root_hash
            and ota_root != ota_boot.state.get("rejected")
            and not ota_boot.state.get("pending")):
        try:
            import ota
            ota.check(ota_root, URL)
        except Exception as error:
            print("OTA unavailable:", error)
        finally:
            # Release the updater before decoding and allocating panel buffers.
            import sys
            sys.modules.pop("ota", None)
            gc.collect()


def draw():
    global err_string, UPDATE_INTERVAL

    print(f"Calling draw() for weather {FILENAME}")
    gc.collect()  # For good measure...

    j = pngdec.PNG(graphics)

    graphics.set_pen(1)
    graphics.clear()

    try:
        j.open_file(FILENAME)
        j.decode()
    except RuntimeError:
        err_string = "Unable to fetch"

    if err_string:
        err_width = graphics.measure_text(err_string, 2)
        graphics.set_pen(4)
        graphics.rectangle(0, HEIGHT - 20, err_width + 15, 20)
        graphics.set_pen(1)
        graphics.text(err_string, 5, HEIGHT - 15, 0, 2)
        err_string = None

    # The launcher sleeps after draw() returns; wait for every colour pass first.
    graphics.set_blocking(True)
    graphics.update()

    # Account for time spent fetching, decoding and refreshing the panel.
    UPDATE_INTERVAL = (
        minutes_until_refresh(time.time())
        if clock_synced else FALLBACK_UPDATE_INTERVAL
    )
    print(f"Next weather update in {UPDATE_INTERVAL} minutes")
