# weather-dash

A dashboard for the weather to be displayed on the ePaper display.

## Panel fleet

Open `/admin` to manage panels. Each panel reports its hardware ID automatically
with every weather request, appears in the fleet list, and displays setup
instructions until its location is configured. The fleet page manages the panel
name, location, hardware profile, rendering palette, battery chemistry, and cell
count. This version supports the existing 7.3-inch Spectra 6 Inky Frame driver.

The client needs only `URL` in `weather_config.py`; Wi-Fi credentials remain in
`secrets.py`. Server settings are cached in `/panel_config.json` outside OTA
slots. An unchanged configuration produces no flash write or config payload.
Changes arrive at the next check-in and replace the complete cached managed
section. Existing local location, palette, and display settings are ignored by
the upgraded client. Older clients can continue using the query-based endpoint.

Fleet requests send `X-Weather-Device-ID` and, once cached,
`X-Weather-Config-Version`. Changed configuration is returned as compact JSON in
`X-Weather-Config`, containing `schema`, `version`, and `config`. Image responses
retain fresh clock, refresh, and OTA headers. `X-Weather-Image-Time` identifies
when the cached image was rendered. New, unconfigured panels retry in five
minutes rather than waiting for a scheduled weather refresh.

The server prepares images five minutes before the 7 am, 11 am, 3 pm, and 7 pm
America/Los_Angeles check-ins. Identical rendering settings share one image.
Startup and configuration changes warm the cache. Cache hits read an indexed PNG
from disk without launching Chrome or fetching weather. If preparation fails or
an image is missing, the request waits for a fresh render; a failed render returns
503 and the client retains its previous image. Successful PNGs are published
atomically, and obsolete configuration images are removed.

`WEATHER_DATA_DIR` selects persistent storage (default `./data`); Docker Compose
mounts a named volume at `/data`. Use one server process and replica so the
preparation worker and SQLite database have one owner. `WEATHER_PUBLIC_URL` sets
the external dashboard origin behind a reverse proxy, including the setup link
and same-origin checks on browser management writes.

Management endpoints are `GET /admin/api/panels`,
`GET /admin/api/panels/{id}`, and `PUT /admin/api/panels/{id}/config`.
Authentication is enforced by ingress: the beta-cluster manifests protect the
entire `/admin` prefix with Envoy Gateway OIDC and Authelia two-factor login,
including the API and callback. Public weather and OTA routes remain accessible
to panels. Local development serves the admin page without an identity provider.
The cluster additions also provision Longhorn storage, VolSync backups, and
Prometheus alerts; deploy the server and these manifests before updated clients.

Panels sample VSYS before enabling Wi-Fi, report voltage and power source, and
preserve the last battery reading when USB powered. Missing readings leave the
last known measurement intact. The fleet page shows its timestamp. Select battery
chemistry and cells in series for an approximate charge percentage: alkaline
uses 1.0–1.6 V per cell, while single-cell lithium polymer/ion uses 3.0–4.2 V.
These are voltage estimates, affected by load, battery age, and discharge curve;
unknown chemistry shows voltage only. Sampling follows the
[Pimoroni Inky Frame battery
example](https://gist.github.com/helgibbons/3ce1a3b6eb24ca6f27a66455caba9809).

Monitor `weather_dash_prerender_failures_total`,
`weather_dash_prerender_failed_targets`, `weather_dash_render_duration_seconds`,
and `weather_dash_image_cache_requests_total`. The cluster PrometheusRule alerts
on active failures and failures in the preceding fifteen minutes, including those
that subsequently recovered during a check-in. Bump `RENDERER_VERSION` when
changing image-affecting renderer code so existing prepared images are rebuilt.

## E-ink rendering

`GET /api/screenshot?width=800&height=480&lat=37.7749&long=-122.4194&panel_profile=spectra6`
renders the dashboard in Chrome and processes its screenshot with
[epdoptimize](https://github.com/paperlesspaper/epdoptimize). `panel_profile`
uses the library's palette identifiers:

| Profile | Output |
| --- | --- |
| `spectra6` (default) | Six native colors for the 7.3-inch Spectra 6 Inky Frame |
| `spectra6-boeber` | Böber's alternative Spectra 6 calibration, with brighter white, blue, and red |
| `generic-2-color-eink` | Black and white, with distinct chart lines and outlined bars |
| `none` | Original full-color screenshot |

Panel screenshots use the library's readable recommendations, LAB matching,
serpentine Floyd–Steinberg dithering, display-range fitting with white preservation,
and text-edge preservation. Neutral pixels
(RGB channel spread at most 16) use the library's monochrome processing to keep
gray text edges and icons free of colored speckles. The Spectra 6
palette is an initial calibration, not a measurement of every individual panel.
Small text, borders, and chart strokes receive panel-specific styling; ordinary
browser visits retain their existing appearance.

The browser maps calibrated colors to native device colors. Python then repacks
the result as an indexed PNG without changing its pixels. The Inky client uses
`PNG_POSTERISE`, avoiding a second dither pass and Spectra's raw palette-index
ordering differences. Future monochrome devices need their own hardware driver.

The old `color`, `brightness`, `black`, and `quantize` screenshot options have
been removed. Set `panel_profile=none` for unprocessed output. Location parameters
and refresh/OTA response headers continue to work as before.

Run `pnpm build` in `frontend/`, then `uv run playwright install --only-shell chromium`
and `EINK_BROWSER_TESTS=1 uv run pytest tests/test_eink_browser.py` to exercise
the production frontend and epdoptimize in Chrome. CI runs these browser tests
against the frontend extracted from the built container.

## Trying it out

A [`run.sh`](./run.sh) utility is provided for quickly building the image and
starting a container.  This script demonstrates best practices for developing
using the container, using bind mounts for the project and virtual environment
directories.

To build and run the web application in the container using `docker run`:

```console
$ ./run.sh
```

Then, check out [`http://localhost:8000`](http://localhost:8000) to see the
website.

To build and run the web application using Docker compose:

```
docker compose up --watch
```

By default, the image is set up to start the web application. However, a
command-line interface is provided for demonstration purposes as well.

To run the command-line entrypoint in the container:

```console
$ ./run.sh hello
```

## Project overview

### Dockerfile

The [`Dockerfile`](./Dockerfile) defines the image and includes:

- Installation of uv
- Installing the project dependencies and the project separately for optimal
  image build caching
- Placing environment executables on the `PATH`
- Running the web application

### Dockerignore file

The [`.dockerignore`](./.dockerignore) file includes an entry for the `.venv`
directory to ensure the `.venv` is not included in image builds. Note that the
`.dockerignore` file is not applied to volume mounts during container runs.

### Run script

The [`run.sh`](./run.sh) script includes an example of invoking `docker run`
for local development, mounting the source code for the project into the
container so that edits are reflected immediately.

### Docker compose file

The [compose.yml](./compose.yml) file includes a Docker compose definition for
the web application.  It includes a [`watch`
directive](https://docs.docker.com/compose/file-watch/#compose-watch-versus-bind-mounts)
for Docker compose, which is a best-practice method for updating the container
on local changes.

### Application code

The Python application code for the project is at
[`src/weather_dash/__init__.py`](./src/weather_dash/__init__.py) — there's a
command line entrypoint and a basic FastAPI application — both of which just
display "hello world" output.

### Project definition

The project at [`pyproject.toml`](./pyproject.toml) includes Ruff as an example
development dependency, includes FastAPI as a dependency, and defines a `hello`
entrypoint for the application.

## Useful commands

To check that the environment is up-to-date after image builds:

```console
$ ./run.sh uv sync --locked
Audited 2 packages ...
```

To enter a `bash` shell in the container:

```console
$ ./run.sh /bin/bash
```

To build the image without running anything:

```console
$ docker build .
```
