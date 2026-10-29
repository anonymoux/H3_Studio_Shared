# H3 Studio

A compact web UI for the MiniMax H3 Ref2VA workflow in ComfyUI, served by ComfyUI itself at `http://127.0.0.1:8188/h3studio`.

- Prompt editor with `<Picture N>` / `@image_N` tags that renumber when references are reordered
- Up to 9 reference images: drag-and-drop upload, reorder, enlarged preview on hover
- Settings: duration, aspect ratio, resolution, seed, model (UNet), Turbo LoRA, sigma shift, scheduler, attention (incl. Sage via KJNodes), ref image size
- Optional two-stage latent upscale (`MinimaxH3LatentUpscaler3D`) with split sigmas and tiled decode
- Results panel with live progress, status badges, details dialog (queue/render timings) and a native-size video lightbox
- Draft and job list are stored on the server (`user/h3studio_state.json`) and pushed to open pages over the ComfyUI websocket, so scripts and the page share the same state

## Install

Copy this folder into `ComfyUI/custom_nodes/` and restart ComfyUI. `workflow_api.json` is the API-format MiniMax H3 Ref2VA workflow the page builds on; re-export it if your base workflow changes.

Optional nodes: `Comfyui_Minimax_h3_latent_Upscaler` (upscale), `ComfyUI-KJNodes` (Sage attention).

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/h3studio/options` | available models, LoRAs, upscaler, attention backends |
| GET | `/h3studio/state` | draft + jobs (job statuses refreshed from ComfyUI) |
| PUT | `/h3studio/state` | `{draft: {...partial}, source}` |
| POST | `/h3studio/queue` | queue the current draft, returns the job |
| POST | `/h3studio/jobs/{id}/cancel` | interrupt or dequeue a job |
| DELETE | `/h3studio/jobs/{id}` | hide a job from the list (file is kept) |
| GET | `/h3studio/upscale/options` | SeedVR2 / RTX availability, DiT models, defaults |
| POST | `/h3studio/upscale` | `{video: {filename, subfolder, type}, options, parent?, source?}` → job with `summary.kind = "upscale"` |

## Video upscale

Every finished video card has an upscale button. It queues a separate job that runs SeedVR2 (detail restore to a target short edge, default 1080p, 7B fp16 with block swap) and/or NVIDIA RTX Video Super Resolution (fast ×1.5–×4), then saves `output/video/H3Upscale_*.mp4` with the source frame rate and audio. Needs `seedvr2_videoupscaler` and/or `Nvidia_RTX_Nodes_ComfyUI`; SeedVR2 downloads its models to `models/SEEDVR2` on first use.
