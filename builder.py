"""Turn an H3 Studio draft into a ComfyUI API prompt, based on workflow_api.json."""
import copy
import math
import random
import re
import time

MAX_REFS = 9
MAX_AUDIOS = 3  # MiniMaxH3ReferenceToVideo takes ref_audio_0..2
FPS = 24
RES_MULTIPLE = 32
OUTPUT_PREFIX = "video/H3Studio"

# Node ids in workflow_api.json
NODE_SAVE = "92"
NODE_RES = "115"
NODE_DECODE_AUDIO = "121"
NODE_DECODE_VIDEO = "122"
NODE_SAMPLER_SELECT = "123"
NODE_SCHEDULER = "124"
NODE_SAMPLER = "125"
NODE_GUIDER = "126"
NODE_REF = "136"
NODE_PROMPT = "138"
NODE_DURATION = "132"
NODE_SEED = "129"
NODE_VIDEO_VAE = "119"
NODE_UNET = "127"
NODE_MODEL_SWITCH = "141"
NODE_STEPS_FULL = "143"
NODE_STEPS_LORA = "144"
NODE_LORA = "145"
NODE_LORA_ON = "146"

UPSCALER_NODE = "MinimaxH3LatentUpscaler3D"
SAGE_ATTENTION = "sage (KJ patch)"
ATTENTION_BACKENDS = ("", "pytorch attention", "comfy kitchen attention", SAGE_ATTENTION)
SCHEDULERS = ("simple", "beta", "normal", "sgm_uniform", "karras", "exponential", "linear_quadratic", "kl_optimal")
UPSCALE_BY = ("mp", "scale")
SHIFT_AUDIO = 3.0
DEFAULT_LORA = "minimax_h3_ref2v_turbo_8step_v1.1_768p_comfyui_bf16.safetensors"
TILED_DECODE = {"tile_size": 512, "overlap": 64, "temporal_size": 64, "temporal_overlap": 8}

ASPECTS = {
    "9:16 (Portrait Widescreen)": (9, 16), "16:9 (Widescreen)": (16, 9), "1:1 (Square)": (1, 1),
    "3:4 (Portrait Standard)": (3, 4), "4:3 (Standard)": (4, 3), "2:3 (Portrait Photo)": (2, 3),
    "3:2 (Photo)": (3, 2), "21:9 (Ultrawide)": (21, 9),
}

DEFAULT_DRAFT = {
    "prompt": "",
    "refs": [],
    "audios": [],             # standalone reference audios, <Audio 1>..<Audio 3> in the prompt
    "duration": 5,
    "aspect": "9:16 (Portrait Widescreen)",
    "mp": 0.7,
    "lora": False,
    "loraName": DEFAULT_LORA,
    "steps": {"full": 20, "lora": 8},
    "refSize": "match",
    "seed": 0,
    "seedRandom": True,
    "shiftVideo": 0,          # 0 = keep the model's default sigma shift
    "attention": "",          # "" = keep ComfyUI's default attention
    "unetName": "",           # "" = the model in workflow_api.json
    "scheduler": "simple",
    "upscale": False,
    "upscaleModel": "",
    "upscaleBy": "mp",        # "mp": target megapixels, "scale": multiplier on the stage-1 size
    "upscaleMp": 0.9,
    "upscaleScale": 1.5,
    "splitSigmas": False,     # refine with the tail of the stage-1 schedule instead of a fresh partial denoise
    "refineSteps": 4,
    "refineDenoise": 0.5,
}


def lora_steps_hint(name):
    """Turbo LoRAs are distilled for a fixed step count, written in their file name."""
    m = re.search(r"(\d+)step", name or "")
    return int(m.group(1)) if m else None

_AT_TAG = re.compile(r"@image_?(\d+)", re.IGNORECASE)
_PICTURE_TAG = re.compile(r"<Picture\s*(\d+)>", re.IGNORECASE)
_AUDIO_TAG = re.compile(r"<Audio\s*(\d+)>", re.IGNORECASE)


class DraftError(ValueError):
    pass


def random_seed():
    return random.randrange(2 ** 48)


def frame_count(seconds):
    f = max(5, round(seconds * FPS))
    return f + (5 - f % 17) % 17


def resolution(aspect, mp):
    w, h = ASPECTS.get(aspect, (1, 1))
    scale = math.sqrt(mp * 1024 * 1024 / (w * h))
    return round(w * scale / RES_MULTIPLE) * RES_MULTIPLE, round(h * scale / RES_MULTIPLE) * RES_MULTIPLE


def prompt_for_model(text):
    """The model understands <Picture N>; @image_N is accepted as shorthand."""
    return _AT_TAG.sub(lambda m: f"<Picture {m.group(1)}>", text)


def validate(draft, has_upscaler=False):
    if not str(draft.get("prompt", "")).strip():
        raise DraftError("Prompt đang trống.")
    refs = draft.get("refs") or []
    if len(refs) > MAX_REFS:
        raise DraftError(f"Tối đa {MAX_REFS} ảnh tham chiếu.")
    if any(r.get("uploading") or not r.get("name") for r in refs):
        raise DraftError("Có ảnh tham chiếu chưa tải lên xong.")
    if draft.get("aspect") not in ASPECTS:
        raise DraftError(f"Tỉ lệ không hợp lệ: {draft.get('aspect')}")
    used = {int(n) for n in _PICTURE_TAG.findall(prompt_for_model(draft["prompt"]))}
    bad = sorted(n for n in used if n < 1 or n > len(refs))
    if bad:
        raise DraftError("Prompt nhắc tới ảnh không tồn tại: " + ", ".join(f"<Picture {n}>" for n in bad))
    audios = draft.get("audios") or []
    if len(audios) > MAX_AUDIOS:
        raise DraftError(f"Tối đa {MAX_AUDIOS} audio tham chiếu.")
    if any(a.get("uploading") or not a.get("name") for a in audios):
        raise DraftError("Có audio tham chiếu chưa tải lên xong.")
    used = {int(n) for n in _AUDIO_TAG.findall(draft["prompt"])}
    bad = sorted(n for n in used if n < 1 or n > len(audios))
    if bad:
        raise DraftError("Prompt nhắc tới audio không tồn tại: " + ", ".join(f"<Audio {n}>" for n in bad))
    if draft.get("attention", "") not in ATTENTION_BACKENDS:
        raise DraftError(f"Attention không hợp lệ: {draft.get('attention')}")
    if draft.get("scheduler", "simple") not in SCHEDULERS:
        raise DraftError(f"Scheduler không hợp lệ: {draft.get('scheduler')}")
    if draft.get("upscale"):
        if draft.get("upscaleBy", "mp") not in UPSCALE_BY:
            raise DraftError(f"Kiểu upscale không hợp lệ: {draft.get('upscaleBy')}")
        if draft.get("upscaleBy") == "scale" and not 1 <= float(draft.get("upscaleScale", 0)) <= 4:
            raise DraftError("Hệ số upscale phải trong khoảng 1–4.")
        if not has_upscaler:
            raise DraftError(f"Chưa cài node {UPSCALER_NODE} (Comfyui_Minimax_h3_latent_Upscaler), không upscale được.")
        if not draft.get("upscaleModel"):
            raise DraftError("Chưa chọn model upscaler.")
        if not 0 < float(draft.get("refineDenoise", 0)) <= 1:
            raise DraftError("Denoise của bước làm nét phải trong khoảng (0, 1].")


def _patch_model_chain(p, draft):
    """Insert optional sigma shift / attention nodes after the LoRA switch. Returns the final model link."""
    model = [NODE_MODEL_SWITCH, 0]
    if float(draft.get("shiftVideo") or 0) > 0:
        p["h3shift"] = {"class_type": "MiniMaxH3SigmaShift", "_meta": {"title": "Sigma Shift"},
                        "inputs": {"model": model, "shift_video": float(draft["shiftVideo"]), "shift_audio": SHIFT_AUDIO}}
        model = ["h3shift", 0]
    if draft.get("attention") == SAGE_ATTENTION:
        p["h3attn"] = {"class_type": "MiniMaxH3MemoryEfficientSageAttentionPatch", "_meta": {"title": "Sage Attention"},
                       "inputs": {"model": model}}
        model = ["h3attn", 0]
    elif draft.get("attention"):
        p["h3attn"] = {"class_type": "ModelAttentionBackend", "_meta": {"title": "Attention Backend"},
                       "inputs": {"model": model, "attention": draft["attention"]}}
        model = ["h3attn", 0]
    # the scheduler must see the shifted model so its sigmas match
    p[NODE_GUIDER]["inputs"]["model"] = model
    p[NODE_SCHEDULER]["inputs"]["model"] = model
    return model


def _add_upscale_pass(p, draft, model, seed):
    """Upscale the stage-1 latent in latent space, refine it with a short partial-denoise pass, then decode tiled."""
    # with split sigmas stage 1 stops mid-schedule, so its raw output is still noisy: upscale the denoised prediction
    out_slot = 1 if draft.get("splitSigmas") else 0
    p["h3split"] = {"class_type": "LTXVSeparateAVLatent", "_meta": {"title": "Split AV latent"},
                    "inputs": {"av_latent": [NODE_SAMPLER, out_slot]}}
    if draft.get("upscaleBy") == "scale":
        size = {"mode": "scale by multiplier", "mode.scale": float(draft["upscaleScale"])}
    else:
        size = {"mode": "megapixels", "mode.megapixels": float(draft["upscaleMp"])}
    p["h3upscale"] = {"class_type": UPSCALER_NODE, "_meta": {"title": "Latent Upscale"},
                      "inputs": {"latent": ["h3split", 0], "model_name": draft["upscaleModel"], **size,
                                 "align": RES_MULTIPLE, "enable_temporal_chunking": True, "force_unload": True,
                                 "device": "cuda", "precision": "fp16"}}
    p["h3concat"] = {"class_type": "LTXVConcatAVLatent", "_meta": {"title": "Join AV latent"},
                     "inputs": {"video_latent": ["h3upscale", 0], "audio_latent": ["h3split", 1]}}
    if draft.get("splitSigmas"):
        # one schedule for both passes: stage 1 takes the first N steps, the refine pass the low-noise tail
        stage1_steps = int(draft["steps"]["lora" if draft["lora"] else "full"])
        p[NODE_SCHEDULER]["inputs"]["steps"] = stage1_steps + int(draft["refineSteps"])
        p["h3sigmas"] = {"class_type": "SplitSigmas", "_meta": {"title": "Split sigmas"},
                         "inputs": {"sigmas": [NODE_SCHEDULER, 0], "step": stage1_steps}}
        p[NODE_SAMPLER]["inputs"]["sigmas"] = ["h3sigmas", 0]
        noise, sigmas = [NODE_SEED, 0], ["h3sigmas", 1]
    else:
        p["h3sched2"] = {"class_type": "BasicScheduler", "_meta": {"title": "Refine schedule"},
                         "inputs": {"scheduler": draft.get("scheduler", "simple"), "steps": int(draft["refineSteps"]),
                                    "denoise": float(draft["refineDenoise"]), "model": model}}
        p["h3noise2"] = {"class_type": "RandomNoise", "_meta": {"title": "Refine noise"},
                         "inputs": {"noise_seed": int(seed) + 1}}
        noise, sigmas = ["h3noise2", 0], ["h3sched2", 0]
    p["h3refine"] = {"class_type": "SamplerCustomAdvanced", "_meta": {"title": "Refine"},
                     "inputs": {"noise": noise, "guider": [NODE_GUIDER, 0], "sampler": [NODE_SAMPLER_SELECT, 0],
                                "sigmas": sigmas, "latent_image": ["h3concat", 0]}}
    p[NODE_DECODE_VIDEO] = {"class_type": "VAEDecodeTiled", "_meta": {"title": "VAE Decode (Tiled)"},
                            "inputs": {"samples": ["h3refine", out_slot], "vae": [NODE_VIDEO_VAE, 0], **TILED_DECODE}}
    p[NODE_DECODE_AUDIO]["inputs"]["samples"] = ["h3refine", out_slot]


def build(template, draft, seed, has_upscaler=False):
    validate(draft, has_upscaler)
    p = copy.deepcopy(template)
    ref_node = p[NODE_REF]["inputs"]
    for key in [k for k in ref_node if k.startswith("ref_images.")]:
        link = ref_node.pop(key)
        if isinstance(link, list):
            p.pop(link[0], None)
    for i, r in enumerate(draft["refs"]):
        node_id = f"h3ref{i}"
        image = f"{r['subfolder']}/{r['name']}" if r.get("subfolder") else r["name"]
        p[node_id] = {"class_type": "LoadImage", "inputs": {"image": image}, "_meta": {"title": f"Ref {i + 1}"}}
        ref_node[f"ref_images.ref_image_{i}"] = [node_id, 0]
    for key in [k for k in ref_node if k.startswith("ref_audios.")]:
        ref_node.pop(key)
    for i, a in enumerate(draft.get("audios") or []):
        node_id = f"h3aud{i}"
        audio = f"{a['subfolder']}/{a['name']}" if a.get("subfolder") else a["name"]
        p[node_id] = {"class_type": "LoadAudio", "inputs": {"audio": audio}, "_meta": {"title": f"Audio {i + 1}"}}
        ref_node[f"ref_audios.ref_audio_{i}"] = [node_id, 0]
    ref_node["ref_image_size"] = draft["refSize"]
    p[NODE_PROMPT]["inputs"]["value"] = prompt_for_model(draft["prompt"])
    p[NODE_DURATION]["inputs"]["value"] = float(draft["duration"])
    p[NODE_RES]["inputs"]["aspect_ratio"] = draft["aspect"]
    p[NODE_RES]["inputs"]["megapixels"] = float(draft["mp"])
    p[NODE_LORA_ON]["inputs"]["value"] = bool(draft["lora"])
    p[NODE_LORA]["inputs"]["lora_name"] = draft.get("loraName") or DEFAULT_LORA
    p[NODE_STEPS_FULL]["inputs"]["value"] = int(draft["steps"]["full"])
    p[NODE_STEPS_LORA]["inputs"]["value"] = int(draft["steps"]["lora"])
    p[NODE_SEED]["inputs"]["noise_seed"] = int(seed)
    # SaveVideo numbers files from the highest one on disk, so deleting results reuses old names and the browser
    # shows its cached copy of the old video: a timestamp in the prefix keeps every name new
    p[NODE_SAVE]["inputs"]["filename_prefix"] = f"{OUTPUT_PREFIX}_{time.strftime('%Y%m%d-%H%M%S')}"
    if draft.get("unetName"):
        p[NODE_UNET]["inputs"]["unet_name"] = draft["unetName"]
    p[NODE_SCHEDULER]["inputs"]["scheduler"] = draft.get("scheduler", "simple")
    model = _patch_model_chain(p, draft)
    if draft.get("upscale"):
        _add_upscale_pass(p, draft, model, seed)
    return p


def summary(draft, seed):
    w, h = resolution(draft["aspect"], float(draft["mp"]))
    out = {
        "duration": draft["duration"], "frames": frame_count(float(draft["duration"])), "w": w, "h": h,
        "lora": bool(draft["lora"]), "steps": draft["steps"]["lora" if draft["lora"] else "full"],
        "seed": seed, "refs": len(draft["refs"]),
    }
    if draft.get("audios"):
        out["audios"] = len(draft["audios"])
    if draft["lora"]:
        out["loraName"] = draft.get("loraName") or DEFAULT_LORA
    if float(draft.get("shiftVideo") or 0) > 0:
        out["shift"] = float(draft["shiftVideo"])
    if draft.get("unetName"):
        out["unet"] = draft["unetName"]
    if draft.get("scheduler", "simple") != "simple":
        out["scheduler"] = draft["scheduler"]
    if draft.get("attention"):
        out["attention"] = draft["attention"]
    if draft.get("upscale"):
        # stage-1 size stays in w/h; the final file is roughly the upscale target
        if draft.get("upscaleBy") == "scale":
            k = float(draft["upscaleScale"])
            out["upscaleTo"] = [round(w * k / RES_MULTIPLE) * RES_MULTIPLE, round(h * k / RES_MULTIPLE) * RES_MULTIPLE]
        else:
            out["upscaleTo"] = list(resolution(draft["aspect"], float(draft["upscaleMp"])))
        out["refine"] = (f"{int(draft['refineSteps'])} split steps" if draft.get("splitSigmas")
                         else f"{int(draft['refineSteps'])} steps @ {float(draft['refineDenoise'])}")
    return out
