"""Build a ComfyUI API prompt that upscales a finished video: SeedVR2 (detail) and/or RTX Video Super Resolution (2x),
keeping the source frame rate and audio."""
import os
import time

SEEDVR2_NODES = ("SeedVR2LoadDiTModel", "SeedVR2LoadVAEModel", "SeedVR2VideoUpscaler")
RTX_NODE = "RTXVideoSuperResolution"
OUTPUT_PREFIX = "video/H3Upscale"

COLOR_CORRECTIONS = ("lab", "wavelet", "wavelet_adaptive", "hsv", "adain", "none")
RTX_QUALITIES = ("ULTRA", "HIGH", "MEDIUM", "LOW")
SEEDVR2_ATTENTION = ("sdpa", "sageattn_2")
MAX_BLOCK_SWAP = 36

DEFAULTS = {
    "seedvr2": True,
    "ditModel": "seedvr2_ema_7b_fp16.safetensors",
    "resolution": 1080,         # target short edge after SeedVR2
    "batchSize": 33,            # frames per batch, 4n+1
    "colorCorrection": "lab",
    "blocksToSwap": 36,         # 7B fp16 only fits a 24 GB card with block swap
    "attention": "sdpa",
    "seed": 42,
    "rtx": False,
    "rtxScale": 2.0,
    "rtxQuality": "ULTRA",
}


class UpscaleError(ValueError):
    pass


def normalize(opts, dit_models):
    o = {**DEFAULTS, **{k: v for k, v in (opts or {}).items() if k in DEFAULTS}}
    if not o["seedvr2"] and not o["rtx"]:
        raise UpscaleError("Bật ít nhất một bước: SeedVR2 hoặc RTX Super Resolution.")
    if o["seedvr2"]:
        if o["ditModel"] not in dit_models:
            raise UpscaleError(f"Model SeedVR2 không hợp lệ: {o['ditModel']}")
        if int(o["batchSize"]) % 4 != 1:
            raise UpscaleError("Batch size phải có dạng 4n+1 (5, 9, 17, 33…).")
        if not 256 <= int(o["resolution"]) <= 2160:
            raise UpscaleError("Độ phân giải SeedVR2 phải trong khoảng 256–2160.")
        if o["colorCorrection"] not in COLOR_CORRECTIONS:
            raise UpscaleError(f"Color correction không hợp lệ: {o['colorCorrection']}")
        if o["attention"] not in SEEDVR2_ATTENTION:
            raise UpscaleError(f"Attention không hợp lệ: {o['attention']}")
        o["blocksToSwap"] = max(0, min(MAX_BLOCK_SWAP, int(o["blocksToSwap"])))
    if o["rtx"]:
        if not 1.0 <= float(o["rtxScale"]) <= 4.0:
            raise UpscaleError("Hệ số RTX phải trong khoảng 1–4.")
        if o["rtxQuality"] not in RTX_QUALITIES:
            raise UpscaleError(f"Chất lượng RTX không hợp lệ: {o['rtxQuality']}")
    return o


def target_size(src_w, src_h, o):
    """Final frame size, mirroring SeedVR2's short-edge resize (even sizes) and the RTX multiplier."""
    w, h = src_w, src_h
    if o["seedvr2"]:
        k = int(o["resolution"]) / min(w, h)
        w, h = round(w * k / 2) * 2, round(h * k / 2) * 2
    if o["rtx"]:
        w, h = round(w * float(o["rtxScale"])), round(h * float(o["rtxScale"]))
    return w, h


def build(video_path, o):
    p = {
        "load": {"class_type": "VHS_LoadVideoPath", "_meta": {"title": "Source video"},
                 "inputs": {"video": video_path, "force_rate": 0, "custom_width": 0, "custom_height": 0,
                            "frame_load_cap": 0, "skip_first_frames": 0, "select_every_nth": 1, "format": "None"}},
        "info": {"class_type": "VHS_VideoInfoLoaded", "_meta": {"title": "Source info"},
                 "inputs": {"video_info": ["load", 3]}},
    }
    frames = ["load", 0]
    if o["seedvr2"]:
        offload = "cpu" if o["blocksToSwap"] > 0 else "none"
        p["dit"] = {"class_type": "SeedVR2LoadDiTModel", "_meta": {"title": "SeedVR2 DiT"},
                    "inputs": {"model": o["ditModel"], "device": "cuda:0", "blocks_to_swap": o["blocksToSwap"],
                               "swap_io_components": o["blocksToSwap"] > 0, "offload_device": offload,
                               "cache_model": False, "attention_mode": o["attention"]}}
        p["vae"] = {"class_type": "SeedVR2LoadVAEModel", "_meta": {"title": "SeedVR2 VAE"},
                    "inputs": {"model": "ema_vae_fp16.safetensors", "device": "cuda:0",
                               "encode_tiled": True, "encode_tile_size": 1024, "encode_tile_overlap": 128,
                               "decode_tiled": True, "decode_tile_size": 768, "decode_tile_overlap": 128,
                               "tile_debug": "false", "offload_device": "cpu", "cache_model": False}}
        p["seedvr2"] = {"class_type": "SeedVR2VideoUpscaler", "_meta": {"title": "SeedVR2 upscale"},
                        "inputs": {"image": frames, "dit": ["dit", 0], "vae": ["vae", 0], "seed": int(o["seed"]),
                                   "resolution": int(o["resolution"]), "max_resolution": 0,
                                   "batch_size": int(o["batchSize"]), "uniform_batch_size": False,
                                   "color_correction": o["colorCorrection"], "temporal_overlap": 3,
                                   "prepend_frames": 0, "input_noise_scale": 0.0, "latent_noise_scale": 0.0,
                                   "offload_device": "cpu", "enable_debug": False}}
        frames = ["seedvr2", 0]
    if o["rtx"]:
        p["rtx"] = {"class_type": RTX_NODE, "_meta": {"title": "RTX Video Super Resolution"},
                    "inputs": {"images": frames, "resize_type": "scale by multiplier",
                               "resize_type.scale": float(o["rtxScale"]), "quality": o["rtxQuality"],
                               "strength": 1.0, "image_encoding": "8-bit RGB"}}
        frames = ["rtx", 0]
    # VHS_VideoCombine numbers files from the highest one on disk: a timestamp keeps names new after deletions
    prefix = f"{OUTPUT_PREFIX}_{time.strftime('%Y%m%d-%H%M%S')}"
    p["save"] = {"class_type": "VHS_VideoCombine", "_meta": {"title": "Save upscaled video"},
                 "inputs": {"images": frames, "audio": ["load", 2], "frame_rate": ["info", 0], "loop_count": 0,
                            "filename_prefix": prefix, "format": "video/h264-mp4", "pix_fmt": "yuv420p",
                            "crf": 17, "save_metadata": True, "trim_to_audio": False, "pingpong": False,
                            "save_output": True}}
    return p


def probe(path):
    """(width, height, fps, frames) of a video, read with PyAV (bundled with ComfyUI)."""
    import av
    with av.open(path) as c:
        v = c.streams.video[0]
        fps = float(v.average_rate) if v.average_rate else 24.0
        frames = v.frames or int(round(float(c.duration or 0) / 1e6 * fps))
        return v.codec_context.width, v.codec_context.height, fps, frames


def resolve_source(source, folder_paths):
    """Map {filename, subfolder, type} from ComfyUI's /view convention to a real file inside output/ or input/."""
    kind = source.get("type", "output")
    base = {"output": folder_paths.get_output_directory(), "input": folder_paths.get_input_directory()}.get(kind)
    if not base:
        raise UpscaleError(f"Loại nguồn không hợp lệ: {kind}")
    path = os.path.abspath(os.path.join(base, source.get("subfolder") or "", source.get("filename") or ""))
    if os.path.commonpath([path, os.path.abspath(base)]) != os.path.abspath(base):
        raise UpscaleError("Đường dẫn video nằm ngoài thư mục cho phép.")
    if not os.path.isfile(path):
        raise UpscaleError(f"Không tìm thấy video: {source.get('filename')}")
    return path
