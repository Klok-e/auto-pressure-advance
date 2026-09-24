# Phase 0 PA image feasibility evaluator

The command at `services/api/scripts/evaluate_vlm.py` reads a frozen manifest, finds pattern regions in the original oriented photographs, registers overview and detail views, sends isolated crops to a replaceable Responses API adapter, validates structured observations, and writes per-trial records and a report. It does not produce a printer setting for use in an application.

## Inputs

- `fixtures/manifest.json` fixes observation IDs, SHA-256 hashes, the six-pattern development and three-pattern held-out split, and the two-step bundles. Every view of a physical pattern stays in one split.
- `fixtures/reference.json` is the independent answer key. The evaluator reads it only after local detection and registration, to score results and prevent a development crop from exposing a held-out region. The provider request contains only detector crop geometry, image bytes, observation IDs, and their hashes.
- `fixtures/protocol/prompt-v1.txt` and `schema-v1.json` preserve the first development baseline. The active `prompt-v2.txt` and `schema-v2.json` add explicit crop bounds after v1 returned invalid inspection targets. The command records the active hashes in each report, and saved responses retain the exact request.
- A recorded provider file is a JSON array of Responses objects or normalized envelopes in call order. Synthetic responses are suitable for command tests, not feasibility evidence.

## Run

Install `requirements.txt` in a virtual environment, then run a development replay:

```sh
python services/api/scripts/evaluate_vlm.py \
  --manifest fixtures/manifest.json \
  --reference fixtures/reference.json \
  --split development \
  --provider recorded --responses path/to/recorded-responses.json \
  --output-dir results/development
```

For the live pilot, provide `OPENAI_API_KEY` in the process environment and use `--provider live`. Run development first. Freeze any changes to detector or protocol before one held-out run with `--split held_out`. A live request uses `gpt-6-luna`, medium reasoning, stored Responses, no tools, and original-detail crop input. It never silently changes to a different image-detail setting. A provider rejection or unavailable model is an incomplete trial.

The command stops at 30 attempted model calls or US$5 of recorded cost. Usage-based cost is known only after a provider response; if cost cannot be accounted, the live run stops incomplete. An HTTP failure may have an unknown charge. The provider adapter does not retry with modified inputs.

The output directory contains `trials.json`, `report.json`, exact provider envelopes under `responses/`, derived oriented PNGs under `crops/`, and `review.html`. The provider envelopes include the exact request body and input hashes. `--delete-crops` removes working PNG copies after the run; the source observation hashes and crop coordinates remain in trial records.

## Review follow-up targets

Open `review.html` locally. It displays each valid inspection target on the corresponding EXIF-oriented source photograph. Rate whether a clearer physical view of that marked region could distinguish the named remaining candidates. Ratings are saved in browser local storage. Select **Download ratings.json**, then update the existing report without making another model call:

```sh
python services/api/scripts/evaluate_vlm.py \
  --output-dir results/heldout --ratings-only \
  --ratings path/to/ratings.json
```

The command joins ratings by target and observation ID and preserves the saved reference scoring. If a reference is supplied for a new run, its SHA-256 must match the saved one. Ratings do not prove that a newly acquired view resolved uncertainty.

## Reading the result

The report separates localization, matching, provider, validation, inconclusive, and incorrect-selection outcomes. A missing view, unresolved reference, provider error, or budget limit never counts as a pass. Exact PA and agreement within one physical increment are separate metrics. Correct physical-line selection is scored against an independently annotated apex where available. Unknown acceptable PA ranges remain unknown.

The within-job pass requires all three held-out patterns to localize, match, show exact printed metadata, select the correct physical line and exact preferred PA, with at least two useful incomplete-view targets. A pass permits a small interactive camera prototype only. Reliability across print jobs, acceptable-range accuracy, unsupported-pattern specificity, and live camera guidance remain untested by this cohort.

## Measured pilot on 2026-09-24

The first live development baseline used protocol v1. Eight API calls completed for five development patterns; p09 had no dedicated detail. Five responses failed validation because inspection targets extended beyond their source crops. Prompt v2 added explicit normalized crop bounds before the held-out run. The saved v1 responses remain under `results/development-live-network/`.

The v2 development replay used nine calls and US$0.02655 of usage-based cost. All six overview regions localized; the five patterns with dedicated detail views matched automatically. The evaluator at that time skipped p09 because it lacked a detail image. Four of five attempted patterns were recognized as supported, none had exact flow, acceleration, or preferred PA, and seven trial steps were inconclusive. One response reported a contradiction and one failed target-coordinate validation. The report is `results/development-v2/report.json`. The evaluator now isolates the overview-only region by excluding automatically registered sibling regions, but this correction has no live response in the saved pilot.

The single held-out v2 run used five calls and US$0.01293 of usage-based cost. All three overview regions localized and matched their dedicated details. Supported-pattern recognition was 2/3; exact flow, acceleration, selected physical line, and preferred PA were each 0/3. The p03 overview had an invalid inspection-target box, preventing its detail step; p04's detail response reported a contradiction. Two valid incomplete-overview targets were generated, so the required three-target usefulness check is not complete. The print owner has not rated them. The report and visual page are `results/heldout-v2/report.json` and `results/heldout-v2/review.html`.

The within-job pass rule failed on recognition, metadata, physical-line, and PA selection, independently of the pending usefulness ratings. A post-run visual audit also found partial neighbouring print strips in some detail crops. The detector was tightened afterward using development images; the saved live results describe the earlier detector and cannot certify the revised detector on an untouched held-out set. The next experiment should investigate legibility and crop coverage on development images under a new protocol. This held-out cohort is now consumed and must not be treated as an untouched test after further tuning.
