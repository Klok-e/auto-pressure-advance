# Define multi-image and active-observation trials

Type: grilling
Status: resolved
Blocked by: 03, 04

## Question

How should the feasibility experiment pair overviews with close-ups, test preservation and correction of line identity, and score whether a proposed target region actually resolves uncertainty rather than merely sounding plausible? What evidence distinguishes new visual information from repeated inference on the same image?

The eventual app must request specific camera movements and may try the phone light when supported. Phase 0 should test the usefulness of requested views; the live camera feedback controller is a later implementation concern.

## Answer

Run a frozen sequence for each eligible physical pattern: (1) show Luna an overview or intentionally incomplete image without the human preferred PA; (2) record its identified pattern, visible line-label associations, observations, unresolved candidates, and one proposed target region; (3) show it a preselected detail image of the same pattern when one exists, retaining the earlier response as context; (4) record whether it preserves verified identity, corrects an earlier interpretation only when new evidence supports the correction, and converges or stays inconclusive. Use image IDs and hashes so an identical image cannot count as an independent view. Do not let images containing held-out patterns enter development prompts.

The user will directly judge each proposed follow-up by inspecting the requested region on the physical print. Record `useful`, `unhelpful`, or `uncertain`, with a brief reason tied to the remaining candidate distinction: whether the region exists on that pattern, whether it contains relevant corner/transition detail or a needed label, whether it is obscured in the original view, and whether a clearer view could separate the candidates. An instruction that merely sounds plausible is not scored useful. Record repeated or already well-observed targets as unhelpful. This manual review does not itself prove that the eventual camera controller can acquire the view; live before/after capture remains a later test.

When available, a newly captured view can also be run through the same frozen model protocol to test actual resolution of the named uncertainty. Keep that as additional evidence, separate from the user's direct utility judgment. Do not infer increased certainty from rerunning the same image.

For each multi-image trial, record the predicted line identities before and after the new view, any explicit contradiction, the evidence frame IDs, and whether the final value agrees exactly with the independent preferred PA. Since acceptable ranges were left unknown, do not score convergence to an acceptable range.
