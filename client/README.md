# Weather Dash client

This directory contains a client meant to run on the Pimoroni Inky-Frame
inkylauncher example at
https://github.com/pimoroni/inky-frame/tree/main/examples/inkylauncher

Weather refreshes at 7 am, 11 am, 3 pm, and 7 pm in America/Los_Angeles,
then sleeps overnight until 7 am. The server owns this schedule; edit
`REFRESH_HOURS` and `REFRESH_TIMEZONE` in `src/weather_dash/schedule.py` to
change it. It uses the pinned IANA `tzdata` package, including daylight saving
rules. Updating the server's timezone data needs no client firmware change.

Each boot or manual wake still fetches and draws immediately. After drawing
finishes, the script sets `UPDATE_INTERVAL` for the launcher's next sleep.
Wake times are rounded up to whole minutes; downloading and drawing take
additional time before the new image is visible.

The HTTPS image response contains `X-Weather-Time` (current Unix UTC seconds)
and `X-Weather-Next-Refresh` (the next scheduled instant, also Unix UTC seconds).
The server computes both after rendering and marks the response `no-store`.
The client sets its UTC clock from this response, then calculates the remaining
sleep after the panel finishes drawing. No timezone library or extra time
request is needed on the device. If drawing crosses the target, it retries in
one minute.

The client still accepts an HTTP `Date` header for clock synchronization.
Missing, invalid, past, or excessively distant wake timestamps, clock failures,
and failed downloads use the four-hour fallback. Older servers without schedule
headers also use that fallback. Install the updated server and client to enable
the schedule.

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
