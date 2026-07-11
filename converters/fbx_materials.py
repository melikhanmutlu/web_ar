"""Material/transparency post-processing for FBX-derived GLBs. Split out of
fbx_converter.py (Faz 5 refactor) — pure functions, no converter instance
state, reusable by anything that has a loaded GLTF2 object.
"""


def _gltf_image_bytes(gltf, image_index):
    """Return the raw bytes of a glTF image (data URI or buffer view), or None."""
    import base64

    if image_index is None or not gltf.images or image_index >= len(gltf.images):
        return None
    img = gltf.images[image_index]
    if img.uri and img.uri.startswith("data:"):
        try:
            return base64.b64decode(img.uri.split(",", 1)[1])
        except Exception:
            return None
    if img.bufferView is not None:
        blob = gltf.binary_blob()
        if not blob:
            return None
        bv = gltf.bufferViews[img.bufferView]
        offset = bv.byteOffset if bv.byteOffset else 0
        return blob[offset : offset + bv.byteLength]
    return None


def _analyze_alpha_channel(image_bytes):
    """Inspect an encoded image's alpha channel.

    Returns (has_transparency, mostly_binary):
    - has_transparency: any meaningfully transparent pixel exists
    - mostly_binary: alpha is essentially on/off (foliage cutout) rather than
      gradual (glass/fades), so MASK renders it better than BLEND
    """
    from PIL import Image as PILImage
    import io

    pil = PILImage.open(io.BytesIO(image_bytes))
    if pil.mode not in ("RGBA", "LA", "PA") and "transparency" not in pil.info:
        return False, False
    alpha = pil.convert("RGBA").getchannel("A")
    lo, _ = alpha.getextrema()
    if lo >= 250:
        return False, False
    hist = alpha.histogram()
    total = sum(hist) or 1
    partial = sum(hist[16:240])  # neither fully transparent nor fully opaque
    # Foliage cutouts are dominated by fully-transparent/fully-opaque texels;
    # partial alpha appears only on antialiased edges (typically 5-15%). Truly
    # gradual textures (glass, fades) have large smooth partial regions. MASK
    # must win for cutouts: BLEND disables depth sorting, so dense foliage
    # blends against the background instead of the leaves behind it and the
    # whole canopy washes out.
    return True, (partial / total) < 0.25


def fix_material_transparency(gltf, log=None):
    """Alpha-correctness pass for FBX-derived materials.

    FBX exporters and FBX2glTF disagree about opacity semantics, which shows up
    in two broken ways:
    1. Cutout textures (foliage) arrive with alphaMode=OPAQUE, so the texture's
       alpha channel is ignored and leaves render as solid quads.
    2. A bogus FBX TransparencyFactor arrives as baseColorFactor alpha < 1
       (often 0). Harmless while OPAQUE (spec says alpha is ignored), but fatal
       if anything later switches the material to BLEND — the mesh disappears.

    The fix is driven by what the base-color texture actually contains, not by
    material names. Returns True if any material was modified.

    Also normalizes metallic/roughness on textured materials: glTF defaults
    metallicFactor to 1.0 when omitted, so an FBX2glTF material that leaves it
    unset renders fully metallic — the texture is replaced by grey environment
    reflection and the model washes out. Traditional FBX (lambert/phong)
    materials have no metalness concept, so when there is no
    metallicRoughnessTexture the factor is dialect noise, not artist intent.
    """
    log = log or (lambda msg, level="INFO": None)
    changed = False
    for mat in gltf.materials or []:
        pbr = mat.pbrMetallicRoughness
        if pbr is None:
            continue

        # Any base-color-textured material: kill the metallic sheen. metallicFactor
        # multiplies the metallic-roughness texture's metal channel, so forcing it
        # to 0 removes the unwanted golden/chrome look even when FBX2glTF emitted an
        # MR texture (e.g. Sperm_Wet at ~0.4 metallic). Traditional FBX (lambert/
        # phong) has no real metalness, so this is dialect noise, not artist intent.
        if pbr.baseColorTexture is not None:
            metallic = pbr.metallicFactor if pbr.metallicFactor is not None else 1.0
            roughness = pbr.roughnessFactor if pbr.roughnessFactor is not None else 1.0
            if metallic > 0.2 or roughness < 0.5:
                pbr.metallicFactor = 0.0 if metallic > 0.2 else metallic
                pbr.roughnessFactor = 0.9 if roughness < 0.5 else roughness
                changed = True
                log(
                    f"Normalized PBR factors on textured material '{mat.name}': "
                    f"metallic {metallic:.2f} → {pbr.metallicFactor:.2f}, "
                    f"roughness {roughness:.2f} → {pbr.roughnessFactor:.2f}"
                )
        factor = pbr.baseColorFactor
        factor_alpha = factor[3] if factor and len(factor) == 4 else 1.0

        has_alpha = mostly_binary = False
        if pbr.baseColorTexture is not None and gltf.textures:
            tex_idx = pbr.baseColorTexture.index
            if tex_idx is not None and tex_idx < len(gltf.textures):
                data = _gltf_image_bytes(gltf, gltf.textures[tex_idx].source)
                if data:
                    try:
                        has_alpha, mostly_binary = _analyze_alpha_channel(data)
                    except Exception as exc:
                        log(f"Alpha analysis failed for material '{mat.name}': {exc}", "WARNING")

        if has_alpha:
            # Binary cutouts (foliage) must use MASK even when FBX2glTF already
            # marked them BLEND: BLEND disables depth sorting, so dense leaves
            # blend against the background and the canopy washes out.
            target = "MASK" if mostly_binary else "BLEND"
            if mat.alphaMode != target and mat.alphaMode != "MASK":
                mat.alphaMode = target
                if target == "MASK":
                    mat.alphaCutoff = 0.5
                changed = True
            if mat.doubleSided is not True:
                mat.doubleSided = True
                changed = True
            if factor_alpha < 1.0:
                # Let the texture drive transparency; a stray <1 factor alpha
                # would dim the whole surface.
                pbr.baseColorFactor = [factor[0], factor[1], factor[2], 1.0]
                changed = True
            log(
                f"Transparency fix → material '{mat.name}': "
                f"alphaMode={mat.alphaMode}, doubleSided=True"
            )
        elif factor_alpha < 1.0:
            mode = mat.alphaMode or "OPAQUE"
            if mode == "OPAQUE" or (mode == "BLEND" and factor_alpha < 0.05):
                # FBX opacity import bug: clamp instead of going translucent.
                pbr.baseColorFactor = [factor[0], factor[1], factor[2], 1.0]
                if mode == "BLEND":
                    mat.alphaMode = "OPAQUE"
                changed = True
                log(
                    f"Clamped bogus baseColorFactor alpha {factor_alpha:.3f} → 1.0 "
                    f"on material '{mat.name}' (no texture alpha)"
                )
    return changed
