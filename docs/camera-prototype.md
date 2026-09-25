# Try the camera prototype

This is an experimental camera interface. The earlier three-pattern visual pilot failed, and no new independent print cohort or physical calibration check has passed. A scan can correctly end with no exportable row.

## Run locally

From the repository root:

```bash
uv pip install --python .venv/bin/python -r requirements.txt
cd web && npm ci && npm run generate:api && npm run build && cd ..
set -a
. results/live.env
set +a
.venv/bin/uvicorn app:app --app-dir services/api --host 127.0.0.1 --port 8000
```

The server reads `OPENAI_API_KEY` from the environment. `results/live.env` is the existing ignored local file; use an equivalent environment setting if it is absent. Keep it out of screenshots and diagnostic attachments. The service stores provider Responses for this experiment. The app stores selected stills and session events locally under `results/app/` for up to 14 days, or until you delete the session. It does not upload the continuous video preview.

For an Android phone connected by USB, run `adb reverse tcp:8000 tcp:8000` in another terminal and open `http://localhost:8000` in the phone browser. Browser camera access requires a secure context; localhost qualifies. For other phones, serve the same origin through trusted HTTPS. Phone behavior has not yet been validated in this repository.

## Scan and report feedback

Tap **Start new scan** and grant camera permission. The app then captures stills automatically when the view is stable, sharp, and adequately lit. Follow the large framing, distance, light, and hold cues over the preview. There is no shutter or Next step. When it stops, inspect the results and copy only rows shown as verified. If the view is inconclusive, try another physical print or angle rather than treating the missing row as a PA recommendation.

Download diagnostics with the arrow button at the top right. Send the JSON file along with the phone/browser model, a short description of what the cue showed, what you did, and what the print actually showed. The file includes camera dimensions, quality samples, capture and upload events, guidance revisions, response IDs, validation failures, and analysis errors. Review it before sharing if the print or account details are sensitive. **Delete session and images** removes server-side stills and responses for that session and clears the saved browser session.

Current limitations: the live preview does not yet register an inspection target from an earlier still, so it uses conservative framing/distance cues instead of a directional arrow to a physical line. Automatic capture and scan progression are implemented, but their usefulness on real phones and prints remains to be measured.
