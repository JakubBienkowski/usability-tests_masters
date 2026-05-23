# UX Tracking Platform

## Fast start

Run one script from the project root:

```bash
sh scripts/start_app.sh
```

Use Python `3.12` for this project. `scripts/start_app.sh` now expects `python3.12` and will stop early if your interpreter or existing `.venv` is on another version. The desktop `opencv_mediapipe` gaze provider is not compatible with the current Python `3.13` environment used here.

This script will:

- create a local Python virtual environment,
- install Python dependencies,
- download the required MediaPipe face-landmarker model automatically if missing,
- download the ETH-XGaze desktop gaze checkpoint automatically if missing,
- install and build the browser extension,
- start PostgreSQL, RabbitMQ, API, and worker with Docker,
- start the desktop agent for outside-browser capture.

## What you do after the script

The only manual browser step is installing the extension once:

1. Open Chrome or Edge.
2. Go to the extensions page.
3. Enable Developer Mode.
4. Choose `Load unpacked`.
5. Select:

```text
ux-test-platform/dist
```

Then open the extension popup and click `Start`.

## What should be running

- API: `http://localhost:8000`
- PostgreSQL: `localhost:5432`
- RabbitMQ UI: `http://localhost:15672`
- Desktop agent: started automatically by the script

## Current desktop gaze mode

The desktop agent now defaults to a local Python webcam/CV provider:

- provider: `opencv_mediapipe`
- camera capture: OpenCV
- face/iris landmarks: MediaPipe Face Mesh

If that provider is unavailable on a machine, you can explicitly fall back to:

- `mouse_proxy`
- `pygaze`

When the desktop agent is running, it also exposes a local gaze bridge for browser consumers at:

```text
http://127.0.0.1:8790
ws://127.0.0.1:8790/ws/gaze
```

The frontend tracker now prefers this local bridge first and only falls back to browser `webgazer` when the agent bridge is unavailable.

On a new machine, the desktop provider now:

- detects the current screen geometry,
- keeps a machine-specific local calibration profile,
- exposes calibration endpoints over the local bridge,
- can be calibrated from the browser UI without manual env edits.

You can override it with:

```bash
UX_GAZE_PROVIDER=mouse_proxy sh scripts/start_app.sh
```

or:

```bash
UX_GAZE_PROVIDER=pygaze sh scripts/start_app.sh
```

If you need to tune the local CV mapping on a machine, set:

```bash
UX_GAZE_X_MIN=0.32
UX_GAZE_X_MAX=0.68
UX_GAZE_Y_MIN=0.25
UX_GAZE_Y_MAX=0.75
UX_GAZE_Y_OFFSET=-0.28
UX_SCREEN_WIDTH=1920
UX_SCREEN_HEIGHT=1080
sh scripts/start_app.sh
```

## Stop everything

```bash
sh scripts/stop_app.sh
```

## Important limitation

The startup script can build the extension and prepare everything else, but it cannot silently auto-install the browser extension. Browsers do not allow that for security reasons.
