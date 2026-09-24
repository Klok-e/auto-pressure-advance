# PA Pattern VLM Feasibility Plan

Label: wayfinder:map

## Destination

A decision-ready [Phase 0 feasibility spec](spec.md) for testing whether a configurable VLM can interpret real OrcaSlicer 2.3+ adaptive PA herringbone patterns, preserve line identity across images, and request useful follow-up views. The spec defines the dataset, independent ground truth, experiment, held-out metrics, and go/no-go gate needed before planning the full application.

## Notes

- Use `grilling` and `domain-modeling` while resolving human decisions; ask one decision at a time.
- The user will supply photographs of their own prints and independently annotate the physical samples. Do not treat VLM output as ground truth.
- The available cohort is nine patterns from one batch print job; no additional print job is planned. Treat conclusions as a within-job pilot.
- Ten supplied photographs are indexed in the [photo inventory](research/photo-inventory.md); the original images remain in Downloads.
- Follow the camera-only user interaction and no-fabricated-PA constraints in the supplied product brief.
- The eventual app must interactively request specific camera movements, automatically reassess the view, and may use the phone light when supported; a still-image Phase 0 trial must assess whether requested follow-up views would help.
- This map records the resolved decisions; [spec.md](spec.md) is the execution handoff. The application is outside these tickets.
- Tracker operations: `docs/agents/issue-tracker.md`. Child tickets are files under `issues/`; `Blocked by` records dependencies.

## Decisions so far

- [Verify OrcaSlicer pattern and metadata semantics](issues/01-verify-pattern-and-metadata-semantics.md): The official format and version behavior are known; exact label mapping and legibility require checks on the user's prints.
- [Define the print and photo cohort](issues/02-define-print-and-photo-cohort.md): Six patterns are for development and three for a held-out within-job check; all views of a pattern stay together.
- [Establish independent ground truth](issues/03-establish-independent-ground-truth.md): Nine human-selected preferred PAs are paired with printed flow and acceleration; alternate candidate lines are unlabelled and acceptable ranges remain unknown.
- [Choose the model experiment](issues/04-choose-model-experiment.md): Start with GPT-6 Luna using a fixed, blind, structured still-image protocol; record provenance and costs before considering alternatives.
- [Define multi-image and active-observation trials](issues/06-define-multi-image-and-planning-trials.md): Pair overview and detail views; the user will judge follow-up target utility against the physical print and record repeated or irrelevant targets.
- [Define the evaluation and go/no-go gate](issues/05-define-evaluation-and-gate.md): Require exact results on all three held-out patterns and useful follow-ups on two; a pass permits an interactive prototype only.

## Not yet specified

Nothing else needs a decision before running the Phase 0 experiment.

## Out of scope

- Building the Angular PWA, camera guidance controller, persistent calibration backend, batch export, and physical verification prints belongs to later implementation efforts after the feasibility gate.
- Support for pre-2.3 OrcaSlicer, non-herringbone tests, and other generators is outside this feasibility plan.
- A specialized vision redesign or full application plan depends on the measured Phase 0 failure or success and belongs to a subsequent effort.
