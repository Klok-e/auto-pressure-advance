# Define the print and photo cohort

Type: grilling
Status: resolved

## Question

Which of the user's real OrcaSlicer 2.3+ prints and photographic conditions should form the development and held-out cohorts so that Phase 0 tests clear cases, adjacent values, ambiguity, varied viewing conditions, and multi-pattern identity without leaking the same physical print across splits?

## Answer

Use the user's nine existing physical calibration patterns from one batch print job. Assign six distinct patterns to development and three distinct patterns to a held-out check. Assign every photograph of a pattern to the same split. Choose the exact pattern IDs after independent annotations reveal which examples are clear or ambiguous, but freeze the allocation before any prompt or model tuning. Report the selection and all nine pattern IDs.

Capture, where physically available, a readable overview and paired corner/label close-ups of each pattern. Include deliberate variations in distance, angle, focus, glare, and lighting, with both usable and unusable views retained. Capture an all-pattern plate overview for the multi-pattern identity trial. During development, frame or mask that overview so held-out patterns are not exposed. After tuning is frozen, the full overview may be evaluated, with only the three held-out patterns scored as held out.

This cohort supports a within-job pilot only. All nine patterns share printing conditions, and a three-pattern held-out set cannot establish reliability across print jobs or printers. The go/no-go gate must state this limit explicitly; positive results may justify further research or prototype work but cannot establish production accuracy. If clear, ambiguous, or neighbouring-candidate examples are absent, report those cases as untested rather than inventing them.
