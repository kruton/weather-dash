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

# Configure these items to match.

NAME = "San Francisco, California"  # Location name
LAT = "37.7749"  # Latitude for weather
LONG = "-122.4194"  # Longitude for weather
FALLBACK_UPDATE_INTERVAL = 240  # Minutes between updates if time sync fails
UPDATE_INTERVAL = FALLBACK_UPDATE_INTERVAL  # Launcher reads this after draw()
REFRESH_HOURS = (7, 11, 15, 19)  # America/Los_Angeles, including daylight saving
clock_synced = False


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
    age = 0
    try:
        for header in headers:
            name, value = header.split(b":", 1)
            if name.lower() == b"date":
                date = value.strip().split()
            elif name.lower() == b"age":
                age = max(0, int(value.strip()))
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
    except (ValueError, TypeError, OSError):
        return False


def pacific_offset(timestamp):
    # US daylight saving rules since 2007: March's second Sunday at 10 UTC
    # through November's first Sunday at 09 UTC. Keep the device clock in UTC.
    year, month, day, hour, minute, second, weekday, yearday = time.gmtime(timestamp)
    if 3 < month < 11:
        return -7 * 3600
    if month == 3 or month == 11:
        first_weekday = (weekday - day + 1) % 7
        first_sunday = 1 + (6 - first_weekday) % 7
        if month == 3:
            if (day, hour) >= (first_sunday + 7, 10):
                return -7 * 3600
        elif (day, hour) < (first_sunday, 9):
            return -7 * 3600
    return -8 * 3600


def minutes_until_refresh(now):
    # Check UTC hour boundaries to handle both DST transitions automatically.
    candidate = (int(now) // 3600 + 1) * 3600
    for _ in range(49):
        local_hour = time.gmtime(candidate + pacific_offset(candidate))[3]
        if local_hour in REFRESH_HOURS:
            # The launcher's RTC timer accepts whole minutes. Round up so an
            # early wake cannot cause a duplicate refresh before the target.
            return max(1, int((candidate - now + 59) // 60))
        candidate += 3600
    return FALLBACK_UPDATE_INTERVAL


def update():
    global err_string, clock_synced

    clock_synced = False

    location = url_escape(NAME)
    url = f"https://weather-dash.their.net/api/screenshot?lat={LAT}&long={LONG}&name={location}&width={WIDTH}&height={HEIGHT}"
    print(f"weather update to {FILENAME} from {url}")

    r = None
    try:
        r = requests.get(url, headers={b"accept": b"image/png"}, save_headers=True)
        clock_synced = sync_clock(r.headers)
        if not clock_synced:
            print("No valid response time; using four-hour refresh interval")
        if r.status_code == 200:
            buf = bytearray(1024)
            r.save(FILENAME, buf=buf)
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
