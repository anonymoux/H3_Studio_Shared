"""H3 Studio: a simple web page for the MiniMax H3 Ref2VA workflow, served at /h3studio.

The page's draft (prompt, refs, settings) and job list live on the server in
user/h3studio_state.json, so any client (the page, curl, scripts) sees and edits
the same state. Every change is pushed to open pages over ComfyUI's websocket as
an "h3studio.state" event.

API
  GET    /h3studio/options            -> available LoRAs, upscaler node/models, attention backends
  GET    /h3studio/state              -> {rev, draft, jobs}  (job statuses refreshed)
  PUT    /h3studio/state              body {draft?: {...partial}, source?}  -> state
  POST   /h3studio/queue              body {source?}  queue the current draft -> job
  POST   /h3studio/jobs/{id}/cancel   interrupt / dequeue a job
  DELETE /h3studio/jobs/{id}          hide a job from the list (file is kept)
  GET    /h3studio/upscale/options    SeedVR2 / RTX availability, models and defaults
  POST   /h3studio/upscale            body {video: {filename, subfolder, type}, options, parent?} -> job
"""
import asyncio
import json
import logging
import os
import time

import aiohttp
from aiohttp import web

import folder_paths
import nodes
from server import PromptServer

from . import builder, upscale

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

_HERE = os.path.dirname(os.path.abspath(__file__))
_INDEX = os.path.join(_HERE, "web", "index.html")
_WORKFLOW = os.path.join(_HERE, "workflow_api.json")
_STATE_FILE = os.path.join(folder_paths.get_user_directory(), "h3studio_state.json")
_MAX_JOBS = 60
_ACTIVE = ("queued", "running")
_VIDEO_EXT = (".mp4", ".webm", ".mkv", ".mov")
_EVENT = "h3studio.state"

log = logging.getLogger("H3Studio")
routes = PromptServer.instance.routes
_lock = asyncio.Lock()


# ---------- console noise ----------
def _quiet_connection_resets(loop):
    """Windows' proactor loop logs a full traceback whenever a browser aborts a request (video range
    requests, reloads). Drop only that case; every other loop error still reaches the default handler."""
    previous = loop.get_exception_handler()

    def handler(lp, context):
        if isinstance(context.get("exception"), ConnectionResetError) and "_call_connection_lost" in str(context.get("handle", "")):
            return
        if previous:
            previous(lp, context)
        else:
            lp.default_exception_handler(context)

    loop.set_exception_handler(handler)


if os.name == "nt":
    _quiet_connection_resets(PromptServer.instance.loop)


# ---------- state store ----------
def _load_state():
    try:
        with open(_STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError) as e:
        log.error("Cannot read %s: %s", _STATE_FILE, e)
        data = {}
    saved = data.get("draft") or {}
    draft = {**builder.DEFAULT_DRAFT, **saved}
    if saved and "loraName" not in saved:
        # drafts from before the LoRA picker used the 4-step v0.1 count; match the new default LoRA
        draft["steps"] = {**draft["steps"], "lora": builder.lora_steps_hint(builder.DEFAULT_LORA)}
    if not draft.get("seed"):
        draft["seed"] = builder.random_seed()
    return {"rev": int(data.get("rev", 0)), "draft": draft, "jobs": list(data.get("jobs") or [])}


def _save_state(state):
    tmp = _STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _STATE_FILE)


_state = _load_state()


def _commit(source):
    """Persist the in-memory state and notify every open page. Caller holds _lock."""
    global _state
    _state = {**_state, "rev": _state["rev"] + 1, "jobs": _state["jobs"][:_MAX_JOBS]}
    _save_state(_state)
    PromptServer.instance.send_sync(_EVENT, {"rev": _state["rev"], "source": source})


def _replace_job(job_id, patch):
    global _state
    _state = {**_state, "jobs": [{**j, **patch} if j.get("id") == job_id else j for j in _state["jobs"]]}


# ---------- job status ----------
def _videos(outputs):
    found = []
    for out in (outputs or {}).values():
        for items in out.values():
            if not isinstance(items, list):
                continue
            for f in items:
                if isinstance(f, dict) and str(f.get("filename", "")).lower().endswith(_VIDEO_EXT):
                    found.append({"filename": f["filename"], "subfolder": f.get("subfolder", ""), "type": f.get("type", "output")})
    return found


def _status_from_history(entry):
    status = entry.get("status") or {}
    messages = status.get("messages") or []
    # in-memory history keeps (event, data) tuples; the JSON API turns them into lists
    kinds = {m[0]: m[1] for m in messages if isinstance(m, (list, tuple)) and len(m) == 2}
    # ComfyUI stamps each execution message with epoch milliseconds
    end = next((kinds[k] for k in ("execution_success", "execution_error", "execution_interrupted") if k in kinds), {})
    times = {"startedAt": (kinds.get("execution_start") or {}).get("timestamp"), "finishedAt": end.get("timestamp")}
    times = {k: v for k, v in times.items() if v}
    if "execution_interrupted" in kinds:
        return {"status": "cancelled", **times}
    if status.get("status_str") == "error" or "execution_error" in kinds:
        err = kinds.get("execution_error") or {}
        return {"status": "error", **times,
                "error": f"{err.get('node_type', '')}: {err.get('exception_message', 'Lỗi khi chạy workflow.')}".strip()}
    return {"status": "done", "videos": _videos(entry.get("outputs")), **times}


def _refresh_jobs():
    """Sync active jobs with ComfyUI's queue/history. Returns True if anything changed. Caller holds _lock."""
    queue = PromptServer.instance.prompt_queue
    changed = _backfill_times(queue)
    active = [j for j in _state["jobs"] if j.get("status") in _ACTIVE]
    if not active:
        return changed
    running, pending = queue.get_current_queue_volatile()
    running_ids = {item[1] for item in running}
    pending_ids = {item[1] for item in pending}
    for job in active:
        jid = job["id"]
        if jid in running_ids:
            patch = {"status": "running"}
        elif jid in pending_ids:
            patch = {"status": "queued"}
        else:
            entry = queue.get_history(prompt_id=jid).get(jid)
            patch = _status_from_history(entry) if entry else {
                "status": "error", "error": "Không tìm thấy job trong ComfyUI (có thể ComfyUI đã khởi động lại)."}
        if any(job.get(k) != v for k, v in patch.items()):
            _replace_job(jid, patch)
            changed = True
    return changed


def _backfill_times(queue):
    """Jobs finished before timings were recorded: take them from ComfyUI's history once, while it still has them."""
    changed = False
    for job in _state["jobs"]:
        if job.get("status") in _ACTIVE or "finishedAt" in job or job.get("timesChecked"):
            continue
        entry = queue.get_history(prompt_id=job.get("id")).get(job.get("id"))
        patch = {k: v for k, v in _status_from_history(entry).items() if k in ("startedAt", "finishedAt")} if entry else {}
        _replace_job(job["id"], {**patch, "timesChecked": True})
        changed = True
    return changed


# ---------- helpers ----------
def _has_upscaler():
    return builder.UPSCALER_NODE in nodes.NODE_CLASS_MAPPINGS


def _model_list(folder, contains=""):
    try:
        names = folder_paths.get_filename_list(folder)
    except KeyError:
        return []
    return sorted(n for n in names if contains in n.lower())


def _load_template():
    with open(_WORKFLOW, encoding="utf-8") as f:
        return json.load(f)


def _local_base_url():
    port = getattr(PromptServer.instance, "port", 8188)
    return f"http://127.0.0.1:{port}"


async def _json_body(request):
    try:
        body = await request.json()
    except (ValueError, aiohttp.ContentTypeError):
        raise web.HTTPBadRequest(text=json.dumps({"error": "Body phải là JSON."}), content_type="application/json")
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text=json.dumps({"error": "Body phải là object JSON."}), content_type="application/json")
    return body


def _error(message, status=400):
    return web.json_response({"error": message}, status=status)


_DRAFT_KEYS = set(builder.DEFAULT_DRAFT)


def _clean_draft_patch(patch):
    unknown = set(patch) - _DRAFT_KEYS
    if unknown:
        raise builder.DraftError("Trường không hợp lệ: " + ", ".join(sorted(unknown)))
    if "refs" in patch:
        refs = patch["refs"]
        if not isinstance(refs, list) or len(refs) > builder.MAX_REFS:
            raise builder.DraftError(f"refs phải là danh sách tối đa {builder.MAX_REFS} ảnh.")
        patch = {**patch, "refs": [{k: r[k] for k in ("id", "name", "subfolder", "label") if k in r}
                                   for r in refs if isinstance(r, dict) and r.get("name")]}
    if "steps" in patch:
        patch = {**patch, "steps": {**_state["draft"]["steps"], **patch["steps"]}}
    return patch


# ---------- routes ----------
@routes.get("/h3studio")
async def h3studio_page(request):
    return web.FileResponse(_INDEX, headers={"Cache-Control": "no-store"})


@routes.get("/h3studio/workflow")
async def h3studio_workflow(request):
    try:
        return web.json_response(_load_template())
    except (OSError, ValueError) as e:
        return _error(f"Cannot read workflow_api.json: {e}", 500)


@routes.get("/h3studio/options")
async def h3studio_options(request):
    return web.json_response({
        "unets": _model_list("diffusion_models", "minimax_h3"),
        "defaultUnet": _load_template()[builder.NODE_UNET]["inputs"]["unet_name"],
        "loras": _model_list("loras", "minimax_h3"),
        "upscaler": _has_upscaler(),
        "upscaleModels": _model_list("latent_upscale_models"),
        "attention": [a for a in builder.ATTENTION_BACKENDS
                      if a != builder.SAGE_ATTENTION or "MiniMaxH3MemoryEfficientSageAttentionPatch" in nodes.NODE_CLASS_MAPPINGS],
        "schedulers": list(builder.SCHEDULERS),
    })


@routes.get("/h3studio/state")
async def h3studio_get_state(request):
    async with _lock:
        if _refresh_jobs():
            _commit("server")
        return web.json_response(_state)


@routes.put("/h3studio/state")
async def h3studio_put_state(request):
    global _state
    body = await _json_body(request)
    async with _lock:
        try:
            patch = _clean_draft_patch(body.get("draft") or {})
        except builder.DraftError as e:
            return _error(str(e))
        if "jobs" in body and isinstance(body["jobs"], list):
            # one-time migration from the page's old localStorage: keep jobs we don't know yet
            known = {j.get("id") for j in _state["jobs"]}
            extra = [j for j in body["jobs"] if isinstance(j, dict) and j.get("id") and j["id"] not in known]
            _state = {**_state, "jobs": sorted(_state["jobs"] + extra, key=lambda j: j.get("created", 0), reverse=True)}
        _state = {**_state, "draft": {**_state["draft"], **patch}}
        _commit(str(body.get("source") or "api"))
        return web.json_response(_state)


@routes.post("/h3studio/queue")
async def h3studio_queue(request):
    global _state
    body = await _json_body(request) if request.can_read_body else {}
    source = str(body.get("source") or "api")
    async with _lock:
        draft = _state["draft"]
        if draft.get("upscale") and not draft.get("upscaleModel"):
            models = _model_list("latent_upscale_models")
            draft = {**draft, "upscaleModel": models[0] if models else ""}
        seed = builder.random_seed() if draft.get("seedRandom") else int(draft.get("seed") or 0)
        try:
            prompt = builder.build(_load_template(), draft, seed, _has_upscaler())
        except builder.DraftError as e:
            return _error(str(e))
        except (OSError, ValueError, KeyError) as e:
            return _error(f"Không dựng được workflow: {e}", 500)
        result = await _submit_prompt(prompt)
        if isinstance(result, web.Response):
            return result
        job = {"id": result["prompt_id"], "created": int(time.time() * 1000), "status": "queued",
               "summary": builder.summary(draft, seed), "prompt": draft["prompt"]}
        _state = {**_state, "draft": {**draft, "seed": seed}, "jobs": [job] + _state["jobs"]}
        _commit(source)
        return web.json_response(job)


async def _submit_prompt(prompt):
    """POST a prompt to this ComfyUI. Returns its JSON result, or an error response to send back as-is."""
    # no client_id: ComfyUI then broadcasts progress events to every open page
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{_local_base_url()}/prompt", json={"prompt": prompt}) as resp:
                result = await resp.json(content_type=None)
                if resp.status != 200:
                    return web.json_response({"error": "ComfyUI từ chối workflow.", "details": result}, status=resp.status)
                return result
    except aiohttp.ClientError as e:
        return _error(f"Không gửi được tới ComfyUI: {e}", 502)


# ---------- video upscale (SeedVR2 / RTX) ----------
def _upscale_available():
    return {"seedvr2": all(n in nodes.NODE_CLASS_MAPPINGS for n in upscale.SEEDVR2_NODES),
            "rtx": upscale.RTX_NODE in nodes.NODE_CLASS_MAPPINGS}


def _seedvr2_models():
    cls = nodes.NODE_CLASS_MAPPINGS.get("SeedVR2LoadDiTModel")
    try:
        spec = cls.INPUT_TYPES()["required"]["model"]
        return list(spec[1]["options"]) if isinstance(spec[0], str) else list(spec[0])
    except Exception:  # node missing or its schema changed: offer nothing rather than fail the page
        return []


@routes.get("/h3studio/upscale/options")
async def h3studio_upscale_options(request):
    return web.json_response({
        "available": _upscale_available(), "ditModels": _seedvr2_models(), "defaults": upscale.DEFAULTS,
        "colorCorrections": list(upscale.COLOR_CORRECTIONS), "rtxQualities": list(upscale.RTX_QUALITIES),
        "attention": list(upscale.SEEDVR2_ATTENTION),
    })


@routes.post("/h3studio/upscale")
async def h3studio_upscale(request):
    """Body: {video: {filename, subfolder, type}, options: {...upscale.DEFAULTS}, parent?: job id, source?}"""
    global _state
    body = await _json_body(request)
    avail = _upscale_available()
    try:
        opts = upscale.normalize(body.get("options"), _seedvr2_models())
        if opts["seedvr2"] and not avail["seedvr2"]:
            raise upscale.UpscaleError("Node SeedVR2 chưa nạp được trong ComfyUI.")
        if opts["rtx"] and not avail["rtx"]:
            raise upscale.UpscaleError("Node RTX Video Super Resolution chưa được cài.")
        video = body.get("video") or {}
        path = upscale.resolve_source(video, folder_paths)
        src_w, src_h, fps, frames = upscale.probe(path)
    except upscale.UpscaleError as e:
        return _error(str(e))
    except Exception as e:  # unreadable video file
        return _error(f"Không đọc được video nguồn: {e}")
    async with _lock:
        if opts["seedvr2"]:
            # SeedVR2 loads its own models outside ComfyUI's memory manager: drop idle H3 models first
            running, pending = PromptServer.instance.prompt_queue.get_current_queue_volatile()
            if not running and not pending:
                try:
                    async with aiohttp.ClientSession() as session:
                        await session.post(f"{_local_base_url()}/free", json={"unload_models": True, "free_memory": True})
                except aiohttp.ClientError:
                    log.warning("Could not ask ComfyUI to free memory before upscaling")
        result = await _submit_prompt(upscale.build(path, opts))
        if isinstance(result, web.Response):
            return result
        w, h = upscale.target_size(src_w, src_h, opts)
        summary = {"kind": "upscale", "w": w, "h": h, "srcW": src_w, "srcH": src_h, "fps": round(fps, 3),
                   "frames": frames, "duration": round(frames / fps, 2) if fps else None,
                   "source": video.get("filename"), "parent": body.get("parent"), "options": opts}
        job = {"id": result["prompt_id"], "created": int(time.time() * 1000), "status": "queued",
               "summary": summary, "prompt": ""}
        _state = {**_state, "jobs": [job] + _state["jobs"]}
        _commit(str(body.get("source") or "api"))
        return web.json_response(job)


@routes.post("/h3studio/jobs/{job_id}/cancel")
async def h3studio_cancel(request):
    job_id = request.match_info["job_id"]
    queue = PromptServer.instance.prompt_queue
    async with _lock:
        if not any(j.get("id") == job_id for j in _state["jobs"]):
            return _error("Không có job này.", 404)
        if queue.delete_queue_item(lambda item: item[1] == job_id):
            _replace_job(job_id, {"status": "cancelled"})
            _commit("server")
            return web.json_response({"cancelled": "pending"})
    running, _ = queue.get_current_queue_volatile()
    if any(item[1] == job_id for item in running):
        nodes.interrupt_processing()
        return web.json_response({"cancelled": "interrupt-sent"})
    return _error("Job không còn trong hàng đợi.", 409)


@routes.delete("/h3studio/jobs/{job_id}")
async def h3studio_hide_job(request):
    global _state
    job_id = request.match_info["job_id"]
    async with _lock:
        jobs = [j for j in _state["jobs"] if j.get("id") != job_id]
        if len(jobs) == len(_state["jobs"]):
            return _error("Không có job này.", 404)
        _state = {**_state, "jobs": jobs}
        _commit(str(request.query.get("source") or "api"))
        return web.json_response({"hidden": job_id})


print("[H3 Studio] UI available at /h3studio")
