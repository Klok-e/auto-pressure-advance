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
scripts/create-lan-certificate.sh YOUR_LAN_IP
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

Tap **Start new scan** and grant camera permission. The app then captures stills automatically when the view is stable, sharp, and adequately lit. Follow the large framing, distance, light, and hold cues over the preview. There is no shutter or Next step. When it stops, inspect the candidate rows; they are experimental until checked against a real print. If the view is inconclusive, try another physical print or angle rather than treating the missing row as a PA recommendation.

Download diagnostics with the arrow button at the top right. Send the JSON file along with the phone/browser model, a short description of what the cue showed, what you did, and what the print actually showed. The file includes camera dimensions, quality samples, capture and upload events, guidance revisions, response IDs, validation failures, and analysis errors. Review it before sharing if the print or account details are sensitive. **Delete session and images** removes locally stored stills and response records for that session and clears the saved browser session.

Current limitations: the live preview does not yet register an inspection target from an earlier still, so it uses conservative framing/distance cues instead of a directional arrow to a physical line. The phone's capture gate checks stability, sharpness, light, and repeated views; pattern detection happens on the backend after upload. Automatic capture and scan progression are implemented, but their usefulness on real phones and prints remains to be measured.
