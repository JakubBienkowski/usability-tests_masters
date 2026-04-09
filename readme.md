# UX Tracking Platform

## Fast start

Run one script from the project root:

```bash
sh scripts/start_app.sh
```

This script will:

- create a local Python virtual environment,
- install Python dependencies,
- install and build the browser extension,
- start RabbitMQ, API, and worker with Docker,
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
- RabbitMQ UI: `http://localhost:15672`
- Desktop agent: started automatically by the script

## Stop everything

```bash
sh scripts/stop_app.sh
```

## Important limitation

The startup script can build the extension and prepare everything else, but it cannot silently auto-install the browser extension. Browsers do not allow that for security reasons.
