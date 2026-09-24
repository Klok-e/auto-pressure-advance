# Verify OrcaSlicer pattern and metadata semantics

Type: research
Status: resolved

## Question

What do current primary OrcaSlicer documentation and generator code establish about the 2.3+ PA Pattern geometry, printed PA labels, flow/acceleration markings, batch layout, and export units? Which details must the experiment confirm on the user's actual prints rather than assume from documentation?

Research asset: [OrcaSlicer pattern semantics](../research/orca-pattern-semantics.md).

## Answer

OrcaSlicer documents that version 2.2+ prints flow and acceleration metadata on the test sample, and version 2.3+ generates a PA Pattern test for each configured speed/acceleration pair. Its recommended PA step is 0.001, but the step is configurable. Adaptive PA rows use PA, volumetric flow in mm³/s, and acceleration in mm/s². The full evidence and links to OrcaSlicer's documentation and generator source are in the research asset.

The feasibility dataset must verify the exact OrcaSlicer build and settings, printed label-to-line mapping, legibility, metadata values, and pattern identity on the user's actual prints. The documentation does not guarantee a stable machine-readable label layout or that phone images can distinguish adjacent PA values. A VLM must not infer missing candidate values or ground truth from those general documentation claims.

## Comments

- A later source check of [OrcaSlicer's PA Pattern generator](https://github.com/OrcaSlicer/OrcaSlicer/blob/main/src/libslic3r/calib.cpp) confirms that PA increments for every physical pattern line while printed number glyphs appear only at even indices. The user confirms the `0.005` offsets from visible `0.01` labels are real unlabelled test lines in this batch. Project or G-code files are optional cross-checks if the visible mapping conflicts.
