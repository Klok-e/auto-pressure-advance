# Choose the model experiment

Type: grilling
Status: resolved
Blocked by: 01, 02

## Question

Which configurable multimodal model candidates and allowed data-handling conditions should Phase 0 compare, and what fixed prompt, image inputs, inference settings, provenance, cost, and retry rules make those comparisons reproducible?

## Answer

Use `gpt-6-luna` as the first VLM candidate, through the OpenAI Responses API. [OpenAI Docs](https://developers.openai.com/api/docs/models/gpt-6-luna) lists image input and structured outputs for this model. This is a first-candidate experiment, not an assumption that it can judge PA correctly; consider another model or specialized vision only after scoring Luna's specific failures. Model access for this account has not yet been tested, and no API call has been made.

Freeze one baseline before querying any held-out pattern:

- Use a versioned prompt and a strict JSON output schema for visible labels, line associations, observed defects, uncertainty, source image IDs, and proposed next observation. Keep preferred PA reference values, acceptable-range information, and print-quality judgments out of model input.
- Set `reasoning.effort` to `medium`, disable tools, and record the exact model identifier, API endpoint, prompt/schema versions and hashes, input image hashes, request parameters, provider response ID, token usage, latency, and errors for each call.
- Apply EXIF orientation deterministically. Preserve the original JPEGs and image dimensions. Send selected still images at `detail: original` where the model accepts it; if the provider rejects that detail level, record the failure and start a separately versioned `high`-detail protocol rather than silently changing settings. [OpenAI's image guide](https://developers.openai.com/api/docs/guides/images-vision) recommends original detail for fine text and spatial tasks where supported.
- Make one analysis request for each predefined image bundle. An overview-only trial and a later overview-plus-close-up trial are distinct bundles, with both image IDs recorded. Repeating a response to the same photograph does not add visual evidence. Retry only failed transport or provider requests with the same inputs; do not retry an uncertain assessment in search of a more certain answer.
- Track actual token usage and cost; cap the initial pilot at 30 model calls and stop before exceeding US$5 in recorded API spend. A cap ends the experiment as incomplete; it never turns an inconclusive result into a success.
- Treat the ten supplied photographs as selected still-image inputs only. Do not stream video. The full nine-pattern overview cannot be used in development model inputs while held-out patterns remain visible; frame or mask it as specified in [Define the print and photo cohort](02-define-print-and-photo-cohort.md). Original photo paths and hashes are in the [inventory](../research/photo-inventory.md).

The user accepted this fixed baseline. Camera movement and optional phone-light control are requirements for the later interactive app, while Phase 0 tests whether the model's requested view would be useful.
