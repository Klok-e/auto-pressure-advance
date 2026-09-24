# Frozen Phase 0 photograph cohort

`fixtures/manifest.json` fixes the ten project-copy JPEG hashes, nine physical pattern IDs, a six-pattern development split, a three-pattern held-out split, and the planned first and second image bundles. `fixtures/reference.json` is the independent answer key. It must be loaded only for scoring, never for localization, matching, prompt construction, or provider input. The JPEGs have orientation-only EXIF; all reference boxes use pixels after applying that orientation.

The IDs follow the full-plate photograph `20260924_191535` in rows from top to bottom and left to right. The printed flow and acceleration marks identify each pattern individually; neither value follows a simple row or column order. Detail marks and cross-view registration corroborate the verified memberships below. The user's physical inspection in the Phase 0 spec establishes preferred PA; no model output was used to assign it. The numbered labels advance by 0.01 and intervening physical lines by 0.005. A line relation in the answer key states the expected physical line order, while `pixel_anchor: null` means that no precise line coordinate was independently marked.

| ID | Printed flow | Printed acceleration | Split | Dedicated detail selected for frozen bundle |
| --- | ---: | ---: | --- | --- |
| p01 | 15.1 | 1000 | development | 191559 |
| p02 | 3.79 | 2000 | held-out | 191551 |
| p03 | 3.79 | 4000 | held-out | 191541 |
| p04 | 7.57 | 1000 | held-out | 191602 |
| p05 | 7.57 | 2000 | development | 191553 |
| p06 | 15.1 | 2000 | development | 191544 |
| p07 | 15.1 | 4000 | development | 191604 |
| p08 | 7.57 | 4000 | development | 191556 |
| p09 | 3.79 | 1000 | development | none |

The numeric detail suffixes in the table abbreviate the full `20260924_` observation IDs. The direct identity of `191547` remains unresolved against the overview; it is listed as an unresolved observation in the answer key and has no scored bundle. Other detail frames include partial neighboring patterns. Their peripheral fragments are not promoted to dedicated views or asserted as independently matched observations; the reference records only verified central memberships. p09 has no complete verified dedicated detail. Its preferred physical line position remains unresolved from the overview alone.

The overview contains all nine patterns. The evaluator must automatically isolate one physical pattern before any provider request and prevent pixels from neighboring patterns from entering the request. The approximate full-pattern boxes in the answer key are scoring references only. They cannot supply detector crops or settle an uncertain automatic match. If localization or matching fails, the affected bundle remains incomplete. The prepared split and bundle sequence were selected from photograph coverage before any model trial and must not be changed after development or held-out exposure.

`acceptable_pa_values` remains unknown for all nine. The preferred PA triplets are the print owner's reference, but the photographs alone cannot establish an acceptable range or a precise pixel location of every selected physical line. The three held-out patterns have independently traceable numbered-line apexes, recorded as approximate oriented-pixel points with 55-pixel tolerance in their detail views. These anchors allow the held-out physical-line check. Other selected lines have no verified pixel anchor in this preparation pass and must not be scored as verified line localization. The complete printed numbered-label set is 0.03 through 0.09 at 0.01 increments; intervening candidate lines increase by 0.005.
