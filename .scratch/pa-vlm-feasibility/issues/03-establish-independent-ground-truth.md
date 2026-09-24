# Establish independent ground truth

Type: grilling
Status: resolved
Blocked by: 01, 02

## Question

How will the user record the verified generator settings, printed line-to-PA mapping, flow, acceleration, acceptable PA range, preferred value if justified, and ambiguous or invalid status for each physical print independently of the VLM? What evidence and review rule settle annotation disagreements?

## Supplied values awaiting provenance

The user supplied nine `PA,flow,acceleration` triplets, grouped by acceleration. The PA values are the user's preferred selections from physical inspection, independent of any VLM; the first column happens to be sorted in ascending PA order and does not encode a tie-break rule. Some patterns had more than one acceptable line, but the ranges were not recorded and will remain unknown. Flow and acceleration were read from the printed pattern. The PA choices were derived from the physical lines using printed labels as anchors, including selected lines that have no adjacent printed number:

```text
0.03,15.1,4000
0.035,7.57,4000
0.04,3.79,4000
0.045,15.1,2000
0.055,7.57,2000
0.06,3.79,2000
0.065,15.1,1000
0.07,7.57,1000
0.075,3.79,1000
```

## Answer

Use the user's physical inspection as the independent visual reference for this pilot. Record the nine supplied PA values as preferred values, paired with the flow and acceleration printed on each pattern. OrcaSlicer's [PA Pattern generator](https://github.com/OrcaSlicer/OrcaSlicer/blob/main/src/libslic3r/calib.cpp) increments PA for every pattern line but prints a number only at even line indices; an unlabelled line can therefore have a valid PA between two visible labels. The user confirms these values and the alternate-line rule for this batch. Use the physical line order and visible labels to evaluate the model's mapping; consult project or G-code files only if those observations conflict. Do not use a VLM prediction to fill a missing setting or settle a conflict.

Keep acceptable PA ranges unknown. The user recalls that some patterns had multiple acceptable lines but does not have their ranges recorded and chose not to annotate them now. Exact agreement with the nine preferred values may be measured as a pilot metric; agreement with the true acceptable range, ambiguity detection against a verified range, and full label-association accuracy cannot be claimed until those annotations exist. Do not interpret the ascending list of preferred values as a tie-break rule.

If the user's later physical inspection disputes a preferred value, mark that pattern ambiguous for exact-value scoring and preserve both observations. If a printed marking conflicts with the user-supplied triplet or the confirmed line order, mark the affected mapping unresolved until its provenance is checked. A pattern with unresolved identity or metadata is not a verified calibration example.

## Comments

- The user supplied ten photographs. See the [photo inventory](../research/photo-inventory.md) for source paths and hashes. Photo-to-pattern identity within the close-ups remains to be recorded.
- The user clarified that OrcaSlicer prints about half as many PA numbers as pattern lines. Values such as `0.045` refer to selected, unlabelled physical lines, not midpoints chosen between two printed lines. Current [generator code](https://github.com/OrcaSlicer/OrcaSlicer/blob/main/src/libslic3r/calib.cpp) supports that mapping. The user's confirmed values are the pilot reference; generator files are an optional cross-check.
