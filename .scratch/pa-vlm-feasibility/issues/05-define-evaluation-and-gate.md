# Define the evaluation and go/no-go gate

Type: grilling
Status: resolved
Blocked by: 03, 04

## Question

What held-out quantitative thresholds and failure costs should govern pattern detection, line-label association, metadata extraction, exact PA agreement, one-increment agreement, ambiguity detection, and follow-up-view utility? Given that the available cohort is one print job with three held-out patterns and no annotated acceptable ranges, which metrics can be reported as pilot evidence, which remain untestable, and what result is sufficient to proceed to further research, narrow scope, or investigate specialized vision?

The user will directly score proposed follow-up targets against the physical print as useful, unhelpful, or uncertain; see [Define multi-image and active-observation trials](06-define-multi-image-and-planning-trials.md). This does not establish that the app's future camera controller can acquire the requested view.

## Candidate mapping evidence

The visible numbers advance in 0.01 PA increments, while the user confirms there are twice as many pattern lines as printed labels. [OrcaSlicer's PA Pattern generator](https://github.com/OrcaSlicer/OrcaSlicer/blob/main/src/libslic3r/calib.cpp) applies `start + index × step` to every line and prints a glyph only for even indices. The user's values ending in `0.005` are real, unlabelled candidate lines in this batch. A model may derive an unlabelled line's value from the visible labels and identifiable physical sequence, never from an unsupported guess.

## Answer

Use the user's confirmed nine triplets as the independent pilot reference, with the photographed labels and alternate physical lines as the candidate mapping. Freeze the six development pattern IDs, three held-out IDs, prompt, schema, inference settings, and image bundles before running a held-out image. Do not use any held-out pattern in prompt tuning, including as a visible neighbour in the full-plate overview. Score the held-out set once; retuning after seeing its results makes those patterns development data. Consult the OrcaSlicer project or G-code only if the printed evidence conflicts with the reference.

Report counts and denominators, with exact PA agreement and agreement within one physical candidate-line increment (`0.005` for this batch) as separate numbers. Report pattern recognition, exact flow/acceleration extraction, selected physical line identity, schema/semantic validation failures, contradictory assessments, and manual follow-up utility separately. An unlabelled line is valid when its value follows from the printed anchors and physical line sequence. Report token usage, cost, and resource-limit terminations; a limit or provider failure is not a successful calibration.

The strict **within-job pilot pass rule** is:

1. All three held-out patterns are recognized as supported and assigned the correct flow and acceleration.
2. After their allowed overview/detail sequence, all three have the exact user-preferred PA and correct physical candidate line, including any unlabelled line. A one-line error is reported but does not pass this rule.
3. There are zero invented PA values, nonexistent image references, silent changes to verified pattern identity, or forced confirmed results from unresolved contradictory evidence.
4. For three intentionally incomplete held-out views, at least two proposed follow-up regions are judged `useful` by the user against the physical print. An absent, repeated, irrelevant, or `uncertain` target does not count as useful.

This rule is an exploratory screen, not a statistical reliability claim: the held-out set has only three patterns from one print job. Acceptable PA ranges, independently verified ambiguous outcomes, unsupported-pattern false positives, broader lighting/material/printer variation, and live camera acquisition are not established by this dataset. Report those as untested, never as passing.

If the pilot passes, proceed only to a small interactive camera prototype, preserving the camera-movement and conditional phone-light requirements. The full application remains gated on broader independent print jobs, annotated acceptable and inconclusive cases, and physical validation. If the pilot fails, report which task failed and investigate that component before considering another VLM or specialized vision; do not relax the held-out gate after inspecting its errors. The user approved this scope and strict pilot rule.
