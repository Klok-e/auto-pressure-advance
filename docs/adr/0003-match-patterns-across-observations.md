# Match physical patterns across observations before VLM analysis

Phase 0 automatically associates pattern regions across overview and detail observations before composing a multi-image Luna request. It may use local visual registration and independently verified printed metadata, but not plate position alone or human pairing in a scored run. This adds another measurable local-vision failure mode, yet protects the calibration pattern's identity as the camera moves. Uncertain matches remain unresolved; observations from different physical patterns must never be merged to force a PA result.
