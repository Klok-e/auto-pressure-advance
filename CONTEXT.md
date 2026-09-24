# Adaptive PA Calibration

Language for interpreting photographed OrcaSlicer Adaptive Pressure Advance calibration prints.

## Language

**Print job**:
A physical print run that produces one or more PA test patterns under shared printer, material, and environmental conditions.
_Avoid_: Pattern, image

**Calibration pattern**:
One physical PA sweep for a specific configured speed and acceleration pair, containing candidate PA marks and printed calibration metadata.
_Avoid_: Print job, photograph

**Candidate line**:
One herringbone test line in a calibration pattern with its own generated PA value. OrcaSlicer may print a numeric label for only every other candidate line.
_Avoid_: Printed label

**Observation**:
A photograph of one or more calibration patterns from a particular camera view. Several observations may show the same physical pattern.
_Avoid_: Pattern, measurement

**Pattern region**:
The area of an observation occupied by one physical calibration pattern, whether or not that pattern's identity has been verified.
_Avoid_: Calibration pattern, observation

**Pattern identity**:
The association of pattern regions in different observations with the same physical calibration pattern, supported by visible geometry or verified printed metadata.
_Avoid_: Camera position, pattern region

**Inspection target**:
A region of a specific observation proposed for a closer or clearer view to resolve stated visual uncertainty.
_Avoid_: Camera instruction, calibration result

**Preferred PA**:
The single PA value a human selects for a calibration pattern after inspecting its physical print.
_Avoid_: Acceptable PA range

**Acceptable PA range**:
The set of candidate PA values judged visually acceptable for one physical calibration pattern; it may contain more than the preferred PA.
_Avoid_: Preferred PA
