import gc
import uos
import machine
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
UPDATE_INTERVAL = 240  # Number of minutes between updates


graphics = None
WIDTH = None
HEIGHT = None


gc.collect()  # We're really gonna need that RAM!

FILENAME = "/sd/weather.png"

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
    return "".join(c if c.isalpha() or c.isdigit() else "%%%02x" % ord(c) for c in s)


def update():
    location = url_escape(NAME)
    url = f"https://weather-dash.their.net/api/screenshot?lat={LAT}&long={LONG}&name={location}&width={WIDTH}&height={HEIGHT}"
    print(f"weather update to {FILENAME} from {url}")

    r = requests.get(url, headers={b"accept": b"image/png"})
    if r.status_code == 200:
        buf = bytearray(1024)
        r.save(FILENAME, buf=buf)
        print(f"Image saved to '{FILENAME}'.")
    else:
        print(f"Request failed. Status: {r.status_code}")

    r.close()
    print(f"finished fetching image to {FILENAME}")
    gc.collect()  # We really are tight on RAM!


def draw():
    print(f"Calling draw() for weather {FILENAME}")
    gc.collect()  # For good measure...

    j = pngdec.PNG(graphics)

    graphics.set_pen(1)
    graphics.clear()

    try:
        j.open_file(FILENAME)
        j.decode()
    except RuntimeError:
        graphics.set_pen(4)
        graphics.rectangle(0, (HEIGHT // 2) - 20, WIDTH, 40)
        graphics.set_pen(1)
        graphics.text("Unable to display image!", 5, (HEIGHT // 2) - 15, WIDTH, 2)
        graphics.text(
            "Check your network settings in secrets.py", 5, (HEIGHT // 2) + 2, WIDTH, 2
        )

    graphics.update()
