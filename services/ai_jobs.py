"""AI text/image -> 3D generation (Meshy): per-user quota and prepaid credits,
reference-image persistence, and the job state machine
(advance / finalize / refund) shared by the poll route, the Meshy webhook,
the admin tools and worker.py's reconciliation sweep.

Extracted from app.py. Callers should reference these through the module
(``services.ai_jobs.X``) so tests can monkeypatch them.
"""

import base64
import logging
import os
import shutil

from flask import current_app

from models import AIGenerationJob, User, db
from services.email_verification import is_verified
from services.time_utils import datetime
from services.upload_pipeline import register_glb_as_model
from services.webhooks import dispatch_webhook_event
from site_settings import setting_int

logger = logging.getLogger(__name__)


def _stash_texture_reference(job_id, data_uri):
    """Persist a refine-stage texture reference image to a temp file so it
    survives between the initial request and the later async refine call
    (texture_prompt/texture_image_url only apply once refine starts).
    Never stored inline as base64 in the DB. Cleaned up by the reconciliation
    sweep alongside abandoned jobs."""
    if not isinstance(data_uri, str) or not data_uri.startswith("data:image/"):
        return None
    tmp_dir = os.path.join(current_app.config["TEMP_FOLDER"], "ai_texture")
    os.makedirs(tmp_dir, exist_ok=True)
    path = os.path.join(tmp_dir, f"{job_id}.txt")
    with open(path, "w") as f:
        f.write(data_uri)
    return path


def _load_texture_reference(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return f.read()


_AI_SOURCE_IMAGE_EXTS = {
    "image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg", "image/webp": "webp",
}


def _persist_ai_source_image(job_id, data_uri):
    """Decode an image->3D source image (inline data URI) to a real file under
    UPLOAD_FOLDER/ai_sources so it persists for admin audit. Returns the path,
    or None if the input isn't a supported image data URI. Never stores base64
    in the DB (mirrors _stash_texture_reference's convention). job_id is a
    server-generated UUID and the extension is whitelisted, so the path is safe."""
    if not isinstance(data_uri, str) or not data_uri.startswith("data:image/"):
        return None
    header, _, b64 = data_uri.partition(",")
    if not b64:
        return None
    mime = header[len("data:"):].split(";", 1)[0].strip().lower()
    ext = _AI_SOURCE_IMAGE_EXTS.get(mime)
    if not ext:
        return None
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception:
        return None
    dest_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], "ai_sources")
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, f"{job_id}.{ext}")
    with open(path, "wb") as f:
        f.write(raw)
    return path


def _ai_quota_state(user_id):
    """Per-user monthly (rolling 30-day) AI generation quota. Counts
    AIGenerationJob rows -- text/image generation spends real Meshy credits,
    so an admin setting ai_monthly_limit to 0 to disable Meshy usage entirely
    must cover it."""
    from datetime import timedelta
    from services.plans import effective_ai_monthly_limit
    since = datetime.utcnow() - timedelta(days=30)
    # Admin-editable override; falls back to the env default when unset.
    # The user's plan (services/plans.py) sets the per-tier monthly ceiling.
    global_default_limit = setting_int("ai_monthly_limit", current_app.config.get("AI_GEN_MONTHLY_LIMIT", 0))
    user = db.session.get(User, user_id) if user_id else None
    limit = effective_ai_monthly_limit(user, global_default_limit)
    trial = _free_ai_trial_allowance(user, limit)
    if trial and is_verified(user):
        # Free trial: a lifetime (not monthly) allowance, so count every job.
        used = AIGenerationJob.query.filter(
            AIGenerationJob.user_id == user_id,
            AIGenerationJob.status != "failed",  # a failed generation doesn't use up a trial
        ).count()
        return (used >= trial), used, trial
    count = AIGenerationJob.query.filter(
        AIGenerationJob.user_id == user_id,
        AIGenerationJob.created_at >= since,
        AIGenerationJob.status != "failed",  # failed generations don't use up the quota
    ).count()
    return (count >= limit), count, limit


def _free_ai_trial_allowance(user, monthly_limit):
    """Lifetime trial generations a Free account gets when its plan monthly AI
    limit is 0 (admin setting free_ai_trial_count, default 3); 0 otherwise.
    Using it additionally requires a verified email (see is_verified)."""
    from services.plans import plan_name
    if user is None or monthly_limit != 0 or plan_name(user) != "free":
        return 0
    return max(0, setting_int("free_ai_trial_count", 3))


def ai_trial_needs_verification(user):
    """True when `user` would get Free AI trial generations if only their
    email were verified -- drives the "verify your email" 403 message."""
    if user is None or is_verified(user):
        return False
    from services.plans import effective_ai_monthly_limit
    global_default_limit = setting_int("ai_monthly_limit", current_app.config.get("AI_GEN_MONTHLY_LIMIT", 0))
    return _free_ai_trial_allowance(
        user, effective_ai_monthly_limit(user, global_default_limit)) > 0


def ai_quota_summary(user):
    """What the Studio AI tab needs to render the right message/CTA.

    state: "ok" (can generate), "needs_verification" (a Free trial exists but
    the email isn't verified), "trial_exhausted" (verified Free user used the
    lifetime trial) or "exhausted" (monthly quota used up, no credits).
    kind: "trial" (lifetime allowance) or "monthly" (rolling 30 days).
    """
    from services.plans import effective_ai_monthly_limit
    _exceeded, used, limit = _ai_quota_state(user.id)
    monthly = effective_ai_monthly_limit(
        user, setting_int("ai_monthly_limit", current_app.config.get("AI_GEN_MONTHLY_LIMIT", 0)))
    trial_total = _free_ai_trial_allowance(user, monthly)
    needs_verification = ai_trial_needs_verification(user)
    kind = "trial" if trial_total and not needs_verification else "monthly"
    remaining = max(0, limit - used)
    credits = user.ai_credit_balance or 0
    if remaining > 0 or credits > 0:
        state = "ok"
    elif needs_verification:
        state = "needs_verification"
    elif kind == "trial":
        state = "trial_exhausted"
    else:
        state = "exhausted"
    return {
        "used": used, "limit": limit, "remaining": remaining, "credits": credits,
        "kind": kind, "state": state, "trial_total": trial_total,
    }


def _consume_ai_allowance(user):
    """Decide whether an AI generation may proceed for `user`, consuming one
    prepaid overage credit when the monthly plan quota is exhausted.

    Call this while holding a row lock on `user` (SELECT ... FOR UPDATE) so
    concurrent requests can't each spend the same last credit. When the plan
    quota is used up but a credit is spent, the balance is decremented on the
    session but NOT committed -- it rides with the caller's job-creation
    commit, so a failed generation doesn't burn a credit.

    Returns (allowed, count, limit): `count`/`limit` are the monthly plan
    quota state (for the error message); allowance may still be granted via a
    credit even when count >= limit.
    """
    exceeded, count, limit = _ai_quota_state(user.id)
    if not exceeded:
        return True, count, limit
    if (user.ai_credit_balance or 0) > 0:
        user.ai_credit_balance -= 1
        return True, count, limit
    return False, count, limit


def _refund_ai_credit(user_id):
    """Return one overage credit consumed by _consume_ai_allowance when the
    generation failed to start. Used by generate_3d, which now commits the
    decrement early (to release the per-user row lock before the slow Meshy
    HTTP call) and must refund on failure to preserve the original
    charge-only-if-started guarantee."""
    user = db.session.query(User).filter_by(id=user_id).with_for_update().one_or_none()
    if user is not None:
        user.ai_credit_balance = (user.ai_credit_balance or 0) + 1
        db.session.commit()




def _refund_ai_job_credit(job):
    """Give back the prepaid credit a failed job consumed, exactly once: the
    job's credit_spent flag is claimed with a conditional UPDATE, so a poll,
    webhook, sweep and admin action racing on the same job refund only once."""
    if not job.credit_spent or not job.user_id:
        return
    claimed = AIGenerationJob.query.filter_by(id=job.id, credit_spent=True).update(
        {"credit_spent": False}, synchronize_session=False)
    if claimed:
        user = db.session.query(User).filter_by(id=job.user_id).with_for_update().one_or_none()
        if user is not None:
            user.ai_credit_balance = (user.ai_credit_balance or 0) + 1
    db.session.commit()
    db.session.refresh(job)


def _claim_ai_stage(job_id, expect_stage, new_stage):
    """Atomically move a job between stages with UPDATE ... WHERE stage=...

    The state machine is advanced by client polls; two concurrent polls of
    the same job (multiple tabs/devices) could otherwise both see a finished
    preview and both call start_refine — burning duplicate Meshy credits —
    or both finalize and register duplicate models. Exactly one poll wins
    this claim; the loser just reports current progress.
    """
    claimed = AIGenerationJob.query.filter_by(
        id=job_id, stage=expect_stage
    ).update({"stage": new_stage}, synchronize_session=False)
    db.session.commit()
    return bool(claimed)


# Hosts Meshy serves generated GLBs/textures from. Used to allowlist the
# remote-texture embed (SSRF guard) so we only fetch texture images referenced
# by a Meshy-authored GLB, never an arbitrary URL.
MESHY_TEXTURE_HOSTS = ["meshy.ai", "amazonaws.com", "cloudfront.net"]


def _finalize_ai_job(job, task):
    """Download finished GLB (+USDZ), register as model, mark job ready.

    Pure job-mutation + commit (no HTTP response built here) -- shared by the
    client-poll route, the webhook receiver and the reconciliation sweep.
    Returns the created UserModel, or None if Meshy returned no GLB (job is
    marked failed in that case instead)."""
    import ai_generator

    model_urls = task.get("model_urls") or {}
    glb_url = model_urls.get("glb")
    if not glb_url:
        job.status = "failed"
        job.error = "Generation finished but returned no GLB"
        db.session.commit()
        _refund_ai_job_credit(job)
        dispatch_webhook_event("ai_generation.failed", job.user_id, {
            "job_id": job.id, "error": job.error,
        })
        return None

    tmp_dir = os.path.join(current_app.config["TEMP_FOLDER"], "ai_" + job.id)
    os.makedirs(tmp_dir, exist_ok=True)
    glb_tmp = os.path.join(tmp_dir, "model.glb")
    ai_generator.download(glb_url, glb_tmp)

    # Diagnose + self-heal textures BEFORE registration (which runs a pygltflib
    # round-trip). Logs exactly what Meshy returned (so an untextured result is
    # one-glance diagnosable), then embeds any externally-referenced (CDN/signed
    # URL) textures so the model is self-contained -- otherwise it renders
    # untextured under CSP/CORS or once Meshy's signed URLs expire. Never fails
    # the job.
    try:
        from converters.glb_quality import (
            attach_base_color_texture_files, embed_remote_textures,
            has_embedded_base_color_textures, inspect_texture_state,
        )
        logger.info(
            "[generate-3d] job=%s texture state: %s | model_urls=%s | texture_urls=%d",
            job.id, inspect_texture_state(glb_tmp), sorted(model_urls.keys()),
            len(task.get("texture_urls") or []),
        )
        if embed_remote_textures(glb_tmp, allowed_hosts=MESHY_TEXTURE_HOSTS):
            logger.info("[generate-3d] job=%s embedded remote Meshy textures", job.id)
        # Some successful image-to-3D tasks return a texture-less GLB and expose
        # the artwork only through texture_urls. There is no image URI for
        # embed_external_textures to resolve in that case, so download Meshy's
        # base-color maps and explicitly bind/embed them into the GLB.
        if not has_embedded_base_color_textures(glb_tmp) and task.get("texture_urls"):
            from urllib.parse import urlparse as _urlparse
            texture_entries = task["texture_urls"]
            if isinstance(texture_entries, dict):
                texture_entries = [texture_entries]
            base_color_files = []
            base_color_keys = {"base_color", "basecolor", "albedo", "diffuse", "diffuse_color"}
            for index, tex in enumerate(texture_entries):
                if not isinstance(tex, dict):
                    continue
                map_url = next((
                    value for key, value in tex.items()
                    if str(key).lower().replace("-", "_") in base_color_keys
                    and isinstance(value, str)
                    and value.lower().startswith(("http://", "https://"))
                ), None)
                if not map_url:
                    continue
                parsed = _urlparse(map_url)
                host = (parsed.hostname or "").lower()
                if not any(host == allowed or host.endswith("." + allowed)
                           for allowed in MESHY_TEXTURE_HOSTS):
                    logger.warning("[generate-3d] skipped untrusted texture host: %s", host)
                    continue
                suffix = os.path.splitext(parsed.path)[1].lower()
                if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
                    suffix = ".png"
                destination = os.path.join(tmp_dir, f"meshy_base_color_{index}{suffix}")
                try:
                    if ai_generator.download(map_url, destination):
                        base_color_files.append(destination)
                except Exception as texture_exc:
                    logger.warning("[generate-3d] base-color download failed: %s", texture_exc)
            if attach_base_color_texture_files(glb_tmp, base_color_files):
                logger.info(
                    "[generate-3d] job=%s attached %d Meshy base-color texture(s)",
                    job.id, len(base_color_files),
                )
    except Exception as exc:
        logger.warning("[generate-3d] job=%s texture diagnose/heal skipped: %s", job.id, exc)

    usdz_tmp = None
    if model_urls.get("usdz"):
        try:
            usdz_tmp = os.path.join(tmp_dir, "model.usdz")
            ai_generator.download(model_urls["usdz"], usdz_tmp)
        except Exception as e:
            logger.warning(f"[generate-3d] USDZ download failed: {e}")
            usdz_tmp = None

    model = register_glb_as_model(
        glb_tmp, user_id=job.user_id, source=f"ai-{job.kind}",
        prompt=job.prompt, usdz_src_path=usdz_tmp,
    )
    try:
        shutil.rmtree(tmp_dir)
    except Exception:
        pass

    job.status = "ready"
    job.progress = 100
    job.model_id = model.id
    db.session.commit()
    dispatch_webhook_event("ai_generation.completed", job.user_id, {
        "job_id": job.id, "model_id": model.id,
    })
    return model


def _advance_ai_job(job):
    """Advance a 'generating' AIGenerationJob by one step using whatever
    Meshy task state is available right now: poll the active Meshy task, and
    if it just finished, either kick off the next stage (preview -> refine)
    or finalize (download + register the model).

    Shared by the client-poll route (generate_3d_status), the Meshy webhook
    receiver, and worker.py's reconciliation sweep -- all three call this
    identically, so the existing _claim_ai_stage atomic claim prevents any
    two of them from double-starting a refine or double-registering a model
    for the same job (e.g. a webhook firing while a browser tab is also
    polling). Mutates and commits `job`; raises on transient failures
    (ai_generator.MeshyError etc.) so callers can decide how to react
    (poll route -> 502 to the client, sweep/webhook -> log and move on).
    """
    import ai_generator

    if job.status in ("ready", "failed"):
        return

    if job.kind == "image":
        if job.stage == "image":
            t = ai_generator.get_task("image", job.meshy_image_id)
            job.progress = min(99, t["progress"])
            if t["status"] == ai_generator.SUCCEEDED:
                if not _claim_ai_stage(job.id, "image", "finalizing"):
                    db.session.refresh(job)  # another poll is finalizing
                else:
                    try:
                        _finalize_ai_job(job, t)
                        return
                    except Exception:
                        # let the next poll retry the download/registration
                        _claim_ai_stage(job.id, "finalizing", "image")
                        raise
            elif t["status"] in (ai_generator.FAILED, ai_generator.CANCELED):
                job.status = "failed"
                job.error = t.get("task_error") or "Generation failed"
    else:
        if job.stage == "preview":
            t = ai_generator.get_task("text", job.meshy_preview_id)
            job.progress = min(49, t["progress"] // 2)
            if t["status"] == ai_generator.SUCCEEDED:
                if not _claim_ai_stage(job.id, "preview", "refining"):
                    db.session.refresh(job)  # another poll started refine
                else:
                    job_options = job.options or {}
                    texture_image_url = _load_texture_reference(job.texture_ref)
                    try:
                        refine_id = ai_generator.start_refine(
                            job.meshy_preview_id,
                            texture_prompt=job_options.get("texture_prompt"),
                            texture_image_url=texture_image_url,
                            moderation=job_options.get("moderation"),
                            remove_lighting=job_options.get("remove_lighting"))
                    except Exception:
                        # release the claim so the next poll retries
                        _claim_ai_stage(job.id, "refining", "preview")
                        raise
                    job.meshy_refine_id = refine_id
                    job.stage = "refine"
                    job.progress = 50
                    if job.texture_ref:
                        try:
                            os.remove(job.texture_ref)
                        except OSError:
                            pass
                        job.texture_ref = None
            elif t["status"] in (ai_generator.FAILED, ai_generator.CANCELED):
                job.status = "failed"
                job.error = t.get("task_error") or "Preview failed"
        elif job.stage == "refine":
            t = ai_generator.get_task("text", job.meshy_refine_id)
            job.progress = min(99, 50 + t["progress"] // 2)
            if t["status"] == ai_generator.SUCCEEDED:
                if not _claim_ai_stage(job.id, "refine", "finalizing"):
                    db.session.refresh(job)
                else:
                    try:
                        _finalize_ai_job(job, t)
                        return
                    except Exception:
                        _claim_ai_stage(job.id, "finalizing", "refine")
                        raise
            elif t["status"] in (ai_generator.FAILED, ai_generator.CANCELED):
                job.status = "failed"
                job.error = t.get("task_error") or "Texturing failed"

    db.session.commit()
    if job.status == "failed":
        _refund_ai_job_credit(job)
        dispatch_webhook_event("ai_generation.failed", job.user_id, {
            "job_id": job.id, "error": job.error,
        })
