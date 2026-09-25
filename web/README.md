# Adaptive PA camera frontend

Install with `npm ci`, regenerate backend contracts with `npm run generate:api`, and build with `npm run build`. The build output is `dist/web/browser/`; the FastAPI service serves it on the same origin as `/api`.

Use HTTPS (or localhost) on a phone so the browser can open the rear camera. The service worker is enabled in production builds. Download diagnostics from the top-right button after a trial; the file includes bounded browser events and backend events but never the session secret.

This is an experimental camera interface. The existing visual feasibility gate has not passed on independent prints, so an inconclusive result is expected when the evidence is insufficient.
