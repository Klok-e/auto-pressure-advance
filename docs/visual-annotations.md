# Visual annotations for the PA inspector

Research date: 2026-09-26. This note proposes an experiment; it does not establish improved PA selection.

## What the evidence supports

- **Visual Sketchpad** lets a multimodal model call drawing and vision tools, then inspect their rendered output before answering. It reports improved GPT-4o and GPT-4 Turbo performance on math and vision benchmarks. Its vision setup also includes detection, segmentation, depth, crops, and zoom; the results do not isolate a benefit from drawing a few marks alone. See [paper, sections 3 and 5](https://arxiv.org/html/2406.09403v1).
- **Set-of-Mark prompting** overlays marks on regions produced by segmentation models and supplies the marked image to GPT-4V. It supports visual grounding through marked input, but does not test Luna drawing its own PA candidates. See [paper](https://arxiv.org/abs/2310.11441) and [authors' implementation](https://github.com/microsoft/SoM).
- **OpenAI image inputs** can include several images in a request. The official documentation warns that small text, precise localization, and counting can be difficult, and that images may be resized even with original detail. These limitations directly matter for printed PA labels and candidate-line ranks. See [Images and vision](https://developers.openai.com/api/docs/guides/images-vision).

These sources support trying a visual feedback loop. They do not establish an accuracy gain for `gpt-6-luna`, herringbone PA patterns, or this camera workflow.

## Two different capabilities

| Capability | What happens | What it establishes |
| --- | --- | --- |
| UI annotation | Luna returns coordinates; the UI paints an overlay. | Users can see the region or corner Luna meant. The model has not seen the painted image. |
| Visual scratchpad | Luna proposes marks; the application renders them; Luna receives the rendered image before deciding. | The model can inspect its own spatial references. Accuracy still needs measurement. |

The second is the mechanism relevant to Visual Sketchpad. Returning coordinates or a textual tool acknowledgment alone does not implement it.

## Smallest useful experiment

Recommendation: one bounded `inspect_region` function on the current observation, available within each existing phase. This is a design inference from the research, not a paper's tested PA protocol.

1. Keep the short phase question. Add one instruction: use marks when they help compare corners or indicate where a clearer view is needed.
2. Accept one normalized rectangle with a short label and clockwise rotation of 0, 90, 180, or 270 degrees. Rectangles can surround a corner, printed value, or requested view without covering the feature. Validate integer ordered bounds within `[0, 1000]`, label length, and rotation. Coordinates always refer to the original photo for the current step.
3. Render with the existing Pillow dependency onto a copy of the exact current observation. Always render from the original, so repeated calls replace marks instead of accumulating paint. The application executes the fixed renderer; the model supplies coordinates.
4. Complete the tool call with one clean detail PNG, enlarged toward a 1280-pixel long edge up to 4x and rotated as requested. Enlargement adds no physical detail. Retain the original image in the phase context. Standard function calling runs application code and continues with image tool results. See [Function calling](https://developers.openai.com/api/docs/guides/function-calling) and [image inputs](https://developers.openai.com/api/docs/guides/images-vision).
5. Allow up to three sequential inspection rounds per phase, within the session's existing call and cost budget. This lets Luna inspect labels after corners, then return the structured answer or request another camera view.
6. Show the marked source under “Inspected photo” in the UI, beside the exact detail sent to Luna. Bind both to the captured observation; do not paint their coordinates on a moving live preview. A replacement photograph needs fresh marks.

Keep the current phase/result vocabulary. No evidence IDs, hashes, segmentation service, image-generation model, or general code-execution tool is needed. The active protocol is `services/api/pa_eval/agent_protocol.py`. Response logs distinguish source and detail files by path, role, dimensions, and byte count while omitting base64. The clean source crop remains in the phase context.

Keep verification on a new unmarked observation. Pass saved printed flow and acceleration, but begin that phase without the earlier selected PA, marked image, or response chain; a prompt saying “independent” does not remove earlier context.

### Development check, 2026-09-26

For the reported second view, the original SDK request serialized a 954×1080 marked photo and a separate 172×336 crop, each byte-identical to its saved file. OpenAI's stored input listing also contained two tool image items, but did not return their image bytes. The old logs replaced both with identical placeholders. The revised continuation sends one detail image and records its file and dimensions.

A live run on the last upside-down photo exercised three crop/rotation rounds but returned an incomplete metadata answer that validation rejected. After clarifying that flow/acceleration settings are separate from the PA-label row, a second run requested a 180-degree crop and returned flow 3.79 and acceleration 2000. Logs are in `results/zoom-smoke-20260926/` and `results/zoom-smoke-20260926-metadata/`. This checks the tool mechanism on a development photo; it does not establish calibration accuracy.

## How to decide whether it helped

Compare the plain-image workflow with the crop/rotation continuation on the same development photographs and phase questions. Include a second-look control with the same call budget but no crop, so an improvement is not simply attributed to an extra model call. Inspect whether the marked UI targets land on the intended corners and whether the detail contains the requested labels. Record physical-line correctness, exact PA and metadata, appropriate requests for a new view, latency, and cost.

For a reliability claim, freeze the protocol and test fresh independently annotated patterns. The previous held-out cohort is consumed and its run failed; see [local feasibility results](vlm-feasibility.md#measured-pilot-on-2026-09-24). Useful UI annotations and improved calibration accuracy are separate outcomes.
