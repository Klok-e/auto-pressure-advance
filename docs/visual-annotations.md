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
2. Accept one normalized rectangle with short labels. Rectangles can surround a corner, printed value, or requested view without covering the feature. Validate finite coordinates, ordered bounds within an integer `[0, 1000]` grid, label length, and a one-mark limit.
3. Render with the existing Pillow dependency onto a copy of the exact current observation. Always render from the original, so repeated calls replace marks instead of accumulating paint. The application executes the fixed renderer; the model supplies coordinates.
4. Complete the tool call and send the rendered PNG as an actual image input in the continuation. Retain the original image in the phase context and identify overlay labels as model annotations, never printed text. Standard function calling runs application code and continues with tool results; image input supplies the rendered view. See [Function calling](https://developers.openai.com/api/docs/guides/function-calling) and [image inputs](https://developers.openai.com/api/docs/guides/images-vision).
5. Start with at most one render-and-reinspect round per phase, then return the existing structured answer or request another camera view. This bounds latency while testing the mechanism.
6. Show that same rendered image under “Inspected photo” in the UI, beside an unmodified detail crop. Bind it to the captured observation; do not paint its coordinates on a moving live preview. A replacement photograph needs fresh marks.

Keep the current phase/result vocabulary. No evidence IDs, hashes, segmentation service, image-generation model, or general code-execution tool is needed. The active protocol at `services/api/pa_eval/agent_protocol.py` now implements this experiment with one `inspect_region` call and image-bearing continuation per phase. The clean source crop remains in the phase context. Exact provider support for the proposed loop must be exercised before claiming it works with Luna.

Keep verification on a new unmarked observation. If independent verification is desired, begin that phase without the earlier selected PA or marked image; a prompt saying “independent” does not remove earlier context.

## How to decide whether it helped

Compare the existing plain-image workflow with the marked-image continuation on the same development photographs and phase questions. Include a second-look control with the same call budget but no marks, so an improvement is not simply attributed to an extra model call. Inspect whether marks land on the intended corners and whether they hide printed labels. Record physical-line correctness, exact PA and metadata, appropriate requests for a new view, latency, and cost.

For a reliability claim, freeze the protocol and test fresh independently annotated patterns. The previous held-out cohort is consumed and its run failed; see [local feasibility results](vlm-feasibility.md#measured-pilot-on-2026-09-24). Useful UI annotations and improved calibration accuracy are separate outcomes.
