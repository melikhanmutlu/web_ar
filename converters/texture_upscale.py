import io
import os

from PIL import Image
from pygltflib import GLTF2


class TextureUpscaleError(RuntimeError):
    pass


def upscale_embedded_textures(source_path, output_path, *, factor=2, max_dimension=4096):
    factor = int(factor)
    if factor not in {2, 4}:
        raise TextureUpscaleError("Upscale factor must be 2 or 4")
    gltf = GLTF2().load(source_path)
    blob = gltf.binary_blob() or b""
    replacements = {}
    details = []
    for image in gltf.images or []:
        if image.bufferView is None:
            continue
        view = gltf.bufferViews[image.bufferView]
        start = view.byteOffset or 0
        payload = blob[start:start + view.byteLength]
        try:
            texture = Image.open(io.BytesIO(payload))
            width, height = texture.size
            target = (min(max_dimension, width * factor), min(max_dimension, height * factor))
            if target == (width, height):
                continue
            texture = texture.resize(target, Image.Resampling.LANCZOS)
            output = io.BytesIO()
            fmt = "JPEG" if (image.mimeType == "image/jpeg") else "PNG"
            if fmt == "JPEG" and texture.mode not in ("RGB", "L"):
                texture = texture.convert("RGB")
            texture.save(output, format=fmt, quality=92, optimize=True)
            replacements[image.bufferView] = output.getvalue()
            details.append({"from": [width, height], "to": list(target), "mime_type": image.mimeType})
        except Exception:
            continue
    if not replacements:
        raise TextureUpscaleError("No upscalable embedded textures were found")

    rebuilt = bytearray()
    for index, view in enumerate(gltf.bufferViews or []):
        while len(rebuilt) % 4:
            rebuilt.append(0)
        start = view.byteOffset or 0
        content = replacements.get(index, blob[start:start + view.byteLength])
        view.byteOffset = len(rebuilt)
        view.byteLength = len(content)
        rebuilt.extend(content)
    gltf.set_binary_blob(bytes(rebuilt))
    if gltf.buffers:
        gltf.buffers[0].byteLength = len(rebuilt)
    gltf.save(output_path)
    return {"textures_upscaled": len(details), "textures": details, "factor": factor}
