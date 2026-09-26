# Try the camera prototype

This is an experimental camera interface. The earlier three-pattern visual pilot failed, and no new independent print cohort or physical calibration check has passed. A scan can correctly end with no exportable row.

## Run on the local network

Find the computer's LAN IPv4 address with `ip -4 addr show`. Substitute it for `YOUR_LAN_IP` in the certificate command and phone URLs. The phone and computer must be on the same local network. Firefox for Android will load a LAN HTTP page but will not give it camera access; the camera trial needs HTTPS. From the repository root:

```bash
uv pip install --python .venv/bin/python -r requirements.txt
cd web && npm ci && npm run generate:api && npm run build && cd ..
set -a
. results/live.env
set +a
scripts/create-lan-certificate.sh 192.168.0.102
.venv/bin/uvicorn app:app --app-dir services/api --host 0.0.0.0 \
  --ssl-certfile results/lan-tls/server.crt --ssl-keyfile results/lan-tls/server.key
```

The server reads `OPENAI_API_KEY` from the environment. `results/live.env` is the existing ignored local file; use an equivalent environment setting if it is absent. Keep it out of screenshots and diagnostic attachments. The app stores selected stills and session events locally under `results/app/` for up to 14 days, or until you delete the session. It does not upload the continuous video preview. The provider also stores Responses for this experiment under its own retention policy; deleting the local session does not delete provider-side Responses.

To trust the local certificate on the Android phone, serve **only** its public CA file from a second terminal:

```bash
python3 -m http.server 8001 --bind 0.0.0.0 --directory results/lan-tls/public
```

On the phone, download `http://YOUR_LAN_IP:8001/ca.cer`, then use Android Settings to install it as a CA certificate. Stop the temporary file server after the download. Open `https://YOUR_LAN_IP:8000` in Firefox and tap Start. `0.0.0.0` listens on every IPv4 interface, so use the computer's firewall if access must be limited to the LAN. If Firefox still rejects the certificate, open **Settings → About Firefox**, tap the Firefox logo until the debug menu is enabled, then open **Secret settings** and enable **Use third party CA certificates**; fully restart Firefox. If the computer's LAN address changes, remove `results/lan-tls/`, regenerate the certificate for the new address, and reinstall its CA certificate on the phone. Remove the local CA from Android when you finish testing. [Mozilla says current Firefox can use Android's third-party CAs](https://support.mozilla.org/en-US/kb/setting-certificate-authorities-firefox); [camera access requires a secure context](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia). Phone behavior has not yet been validated in this repository.

## Scan and report feedback

Tap **Start new scan** and grant camera permission. The app then captures stills automatically when the view is stable, sharp, and adequately lit. Follow the visual framing, distance, light, and hold cue in the compact bar below the camera preview. Guidance stays clear of the print. Small hand shifts are tolerated: motion checking aligns preview samples within three pixels before judging movement. Two clear samples, 450 ms apart, are enough to capture; blur, poor light, and larger motion still wait. A ring fills as a steady frame becomes ready, then the status changes to taking a photo, sending it, and Luna’s current task. Once captured, the app does not ask you to hold still while Luna works. The elapsed time shows that a slow model request is still pending. The optional Stop control stays available. Sharpness, light, and motion readings are in diagnostics. There is no shutter or Next step. When it stops, inspect the candidate rows; they are experimental until checked against a real print. If the view is inconclusive, try another physical print or angle rather than treating the missing row as a PA recommendation.

Luna works through four focused steps for each matched pattern: identify, read printed flow and acceleration, select a labelled PA line by comparing nearby corners, and independently check the line on another photo. The first three steps use the same useful photo, unless Luna needs another view. Luna can inspect up to three areas per step, zooming and rotating the clean crops before answering. Each tool reply sends only the newly requested detail. Below the live preview, the app shows that exact detail alongside its marked source photo. The annotations stay on their saved image; they do not track your moving camera. Saved flow and acceleration remain available in later matched views. If matching fails, the app retains the settings and asks for the same whole pattern, instead of restarting it as a new print. The final check starts a fresh model context with those settings but without the earlier PA choice or marks. The app keeps capture IDs and image digests out of Luna's prompt and reply schema. Exact duplicate uploads reuse the first observation; local image digests are used only for that bookkeeping.

After **Move closer**, bring the phone toward the indicated area while keeping the same print in view. The next automatic photo waits for a likely enlargement, followed by the usual two clear samples. Brightness changes, hand tremor, and elapsed time do not release this wait. The estimate compares the live view with the preview accompanying the analyzed still; large rotations or perspective changes may prevent a match. After resuming without that reference, move closer from the first clear view after resume.

Download diagnostics with the arrow button at the top right. Send the JSON file along with the phone/browser model, a short description of what the cue showed, what you did, and what the print actually showed. The file includes camera dimensions, quality samples with raw and motion-compensated differences, specific capture blockers and their durations, capture/fallback and upload timing, displayed activity transitions and annotation targets, the active agent phase, guidance revisions, response IDs, validation failures, and analysis errors. `closer_gate` records the estimated enlargement, match correlation, and release criteria. Server events include the crop and response-log paths, inspection round, rotation, and detail dimensions. Response logs preserve the question, tool calls and continuations, schema, answer, timing, and usage; each omitted image identifies its saved file, role, dimensions, and byte count. **Delete session and images** removes locally stored stills and response records for that session and clears the saved browser session.

Current limitations: Luna’s drawing tool has not been shown to improve PA accuracy. It makes the selected area visible and gives the model a clean zoomed view to inspect. The live preview does not register an earlier target onto moving video; only the saved reference photo carries the mark. The phone's capture gate checks stability, sharpness, light, repeated views, and likely enlargement after closer; pattern detection happens on the backend after upload. Automatic capture and scan progression are implemented, but their usefulness on real phones and prints remains to be measured.
