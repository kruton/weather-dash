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

### Signed script updates

OTA firmware boots a fixed recovery module and selects `/ota/a` or `/ota/b`.
The launcher, weather app, helper, updater and mrequests dependency are portable
MicroPython 1.29.0 bytecode. Local `weather_config.py`, Wi-Fi `secrets.py`, SD
images and launcher selection remain outside these slots.

The normal screenshot request advertises `ota_profile=inky-v1-mpy6`. A compatible
server adds `X-Weather-OTA-Root`, computed from the compiled script bytes in its
own deployed GHCR image. Matching roots require no second request and do not
load the updater. On a mismatch, the frame sends its hash map to
`POST /api/ota/update`. The multipart response contains the complete signed
manifest and only changed files. Unchanged files are copied and rehashed; files
removed from the manifest are omitted from the new slot.

The frame uses 1 KiB reads, validates ECDSA P-256/SHA-256 signatures with a native
mbedTLS module, checks bytecode compatibility, paths, sizes and available space,
and verifies every script hash before committing a pending slot. Limits are
16 KiB for the manifest, 64 files, 128 KiB per file and 256 KiB of script data.
OTA reads have a 90 second time budget and a 30 second socket timeout.
An interrupted download leaves the active slot untouched and retries on the next
scheduled refresh. The updater never overwrites a currently running script.

Activation happens on the next wake. Battery sleep cuts power normally; USB sleep
resets the interpreter after the scheduled sleep returns. A trial is recorded
before importing the new launcher. The launcher confirms it after initialization
and a completed blocking panel draw. An exception resets to recovery; an
unconfirmed trial rolls back on the next boot and records its rejected root.
There is no watchdog in this version, so a hung trial needs a reset before
recovery runs. A previously signed version can be deployed deliberately to roll
back; there is no monotonic anti-rollback counter.

### Production setup

1. Generate a P-256 signing key and keep a secure backup:

   ```sh
   umask 077
   openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out ota-signing-key.pem
   gh secret set OTA_SIGNING_KEY < ota-signing-key.pem
   ```

2. CI compiles and signs one package. The container and both UF2 builds consume
   the **same artifact**. The public key from that package is compiled into the
   firmware verifier. Production main/tag builds fail if the secret is absent;
   pull requests use an ephemeral test key and cannot update production frames.
   Keep the signing key stable: changing the trust key or frozen recovery code
   requires reflashing firmware.
3. Flash the `with-filesystem.uf2` artifact once to install the initial slots and
   fixed bootstrap. Back up local settings first; filesystem UF2 flashing replaces
   the filesystem. Set `weather_config.py` for location, URL and display, restore
   `secrets.py`, and select Weather with button B. Subsequent deployments update
   scripts over the network while preserving these settings.
4. Test both battery and USB operation on a physical frame before deploying to
   your production fleet. Firmware or native module changes still require UF2.

The server validates signatures and file hashes at startup. No registry query is
made during a refresh. Source checkouts and locally built containers without an
`ota-dist` package omit the root header and return 404 for the OTA endpoint.
A stale target root or incompatible profile returns 409; identical hash maps
return 204. Image time and refresh headers retain their existing behavior.

To create a local test package (the default generates an ephemeral signing key):

```sh
uv run --project .. python build_ota.py \
  --source ~/git/inky-frame/examples/inkylauncher \
  --mrequests /path/to/mrequests/mrequests \
  --compiler /path/to/micropython/mpy-cross/build/mpy-cross \
  --output /tmp/ota-dist
uv run --project .. python install_ota.py /path/to/isolated/inky-frame /tmp/ota-dist
```

`install_ota.py` modifies only the checkout supplied as its argument. The normal
CI build uses an isolated, pinned Inky-Frame checkout; your launcher repository
does not need a separate patch commit. The package builder normalizes source
paths and retains assertions and diagnostics. CI checks deterministic bytecode,
Merkle roots, the native signature verifier and streaming installation using the
matching unix MicroPython runtime, in addition to host and API tests.

Changes to the frozen recovery/protocol contract must bump the firmware profile
and require a new initial UF2; they cannot silently change the API expected by
already deployed frames.
