# Weather Dash client

This directory contains a client meant to run on the Pimoroni Inky-Frame
inkylauncher example at
https://github.com/pimoroni/inky-frame/tree/main/examples/inkylauncher

Weather refreshes at 7 am, 11 am, 3 pm, and 7 pm in America/Los_Angeles,
then sleeps overnight until 7 am. Edit `REFRESH_HOURS` in `weather.py` to
change these times. Pacific daylight saving time follows US rules since 2007.

Each boot or manual wake still fetches and draws immediately. After drawing
finishes, the script sets `UPDATE_INTERVAL` for the launcher's next sleep.
Wake times are rounded up to whole minutes; downloading and drawing take
additional time before the new image is visible.

The script synchronizes its UTC clock using the existing HTTPS image response's
`Date` header, including `Age` if served from a cache. It makes no extra time
request. If that header is missing or invalid, it refreshes again in four hours
rather than scheduling from an unreliable clock.

This reduces scheduled refreshes from six to four per day. Actual battery
savings depend on download time, panel refresh consumption, and manual wakes.

## Preparing the launcher

The firmware build runs `prepare_launcher.py` to apply `launcher.patch` and
copy `weather.py`. The patch selects Weather for button B, reconnects Wi-Fi
before each update (including successive updates on USB), and disables Wi-Fi
and all LEDs before drawing. The panel still completes its full refresh.
For sleeps longer than the countdown timer's 255-minute limit, the patch copies
the synchronized clock into the external RTC and uses its alarm. The overnight
schedule requires this patch.

To prepare files locally without changing your Inky-Frame checkout:

```sh
python3 client/prepare_launcher.py ~/git/inky-frame/examples/inkylauncher \
  --output /tmp/weather-launcher
```

Upload the generated launcher files with your usual Wi-Fi credentials. The
patch command must be installed on the build host. Repeated preparation is
supported; incompatible upstream launcher changes fail the build.

Run client checks with `python3 -m unittest discover -s client/tests`.
