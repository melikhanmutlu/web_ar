"""Post-conversion GLB repair steps for the FBX pipeline: zero-geometry
rescue and external-texture embedding. Split out of fbx_converter.py
(Faz 5 refactor) as a mixin — these methods lean on FBXConverter instance
state (self.log_operation, self.max_dimension, self._fbx_vertices/_fbx_faces/
_fbx_material_textures set during convert()'s pyassimp probe step), so they
stay methods rather than becoming free functions.
"""

import os

import numpy as np
import trimesh
from pygltflib import Image, PbrMetallicRoughness, Texture, TextureInfo

from .base_converter import safe_join_within
from .fbx_materials import fix_material_transparency


class FBXPostProcessMixin:
    """Zero-geometry rescue + texture-embedding steps used by FBXConverter.convert()."""

    def _glb_has_geometry(self, glb_path: str) -> bool:
        """True if the GLB has at least one mesh with non-zero extents."""
        try:
            obj = trimesh.load(glb_path)
            bounds = getattr(obj, "bounds", None)
            if bounds is None:
                return False
            extents = bounds[1] - bounds[0]
            return bool(np.any(extents > 1e-9))
        except Exception as e:
            self.log_operation(f"Warning: geometry check failed: {e}", "WARNING")
            # Be permissive on checker errors — don't fail a possibly-valid model.
            return True

    def _rescue_zero_geometry(self, output_path: str, color, original_dimensions) -> bool:
        """Rebuild the GLB from pyassimp-read FBX data when FBX2glTF emitted
        degenerate (zero-extent) geometry. Returns True if a rescue happened.
        """
        try:
            scene_or_mesh = trimesh.load(output_path)
            if isinstance(scene_or_mesh, trimesh.Scene):
                bounds = scene_or_mesh.bounds
            else:
                bounds = scene_or_mesh.bounds
            if bounds is not None:
                extents = bounds[1] - bounds[0]
                if np.any(extents > 1e-9):
                    return False  # geometry is fine
            del scene_or_mesh
        except Exception as e:
            self.log_operation(f"Warning: zero-geometry check failed: {e}", "WARNING")
            return False

        if getattr(self, "_fbx_vertices", None) is None or getattr(self, "_fbx_faces", None) is None:
            self.log_operation(
                "WARNING: FBX2glTF GLB has zero geometry and no pyassimp data to rescue from",
                "WARNING",
            )
            return False

        self.log_operation(
            "WARNING: FBX2glTF GLB has zero geometry - rebuilding from original FBX data"
        )
        mesh = trimesh.Trimesh(vertices=self._fbx_vertices, faces=self._fbx_faces)
        if original_dimensions and self.max_dimension > 0 and original_dimensions["max"] > 0:
            scale_factor = self.max_dimension / original_dimensions["max"]
            mesh.apply_scale(scale_factor)
            self.log_operation(f"Applied scale factor {scale_factor:.4f} to rescued mesh")
        if color:
            self.apply_color(mesh, color)
        if os.path.exists(output_path):
            os.remove(output_path)
        mesh.export(output_path, file_type="glb")
        self.log_operation(
            f"Rescued mesh exported: {len(mesh.vertices)} vertices, "
            f"{os.path.getsize(output_path)} bytes"
        )
        return True

    def _embed_external_textures_gltf(self, gltf, fbx_path: str) -> None:
        """Embed external texture files into an already-loaded GLTF object.
        This version works with a gltf object that's already in memory.
        """
        try:
            import base64

            fbx_dir = os.path.dirname(fbx_path)

            # --- AGGRESSIVE TEXTURE RECOVERY ---
            # If pyassimp found textures that aren't in the GLB, add them now
            if (
                hasattr(self, "_fbx_material_textures")
                and self._fbx_material_textures
                and gltf.materials
            ):
                self.log_operation(
                    f"Attempting aggressive texture recovery for {len(gltf.materials)} materials"
                )
                def material_key(name):
                    # FBX exporters frequently prepend a namespace such as
                    # "Material::" while FBX2glTF omits it. Match the stable
                    # leaf name case-insensitively before giving up.
                    leaf = str(name or "").replace("\\", "/").split("::")[-1]
                    return "".join(char for char in leaf.lower() if char.isalnum())

                texture_sources = self._fbx_material_textures
                texture_sources_by_key = {
                    material_key(name): source
                    for name, source in texture_sources.items()
                    if material_key(name)
                }
                for mat in gltf.materials:
                    mat_name = mat.name
                    tex_source = (
                        texture_sources.get(mat_name)
                        or texture_sources_by_key.get(material_key(mat_name))
                    )
                    # A single-material FBX with one extracted texture has no
                    # meaningful material-name ambiguity; recover it even if
                    # the two importers chose different names.
                    if not tex_source and len(texture_sources) == len(gltf.materials) == 1:
                        tex_source = next(iter(texture_sources.values()))
                    if tex_source:
                        # Found a mapping from pyassimp

                        # If baseColorTexture is missing or points to a non-existent image
                        has_texture = False
                        if (
                            mat.pbrMetallicRoughness
                            and mat.pbrMetallicRoughness.baseColorTexture
                        ):
                            has_texture = True

                        if not has_texture:
                            # Find the texture file. tex_source comes from the
                            # uploaded FBX's material data and may be absolute or
                            # contain '..'; constrain every candidate to stay
                            # within the upload dirs (no arbitrary file read).
                            texture_file = None
                            search_paths = [
                                safe_join_within(fbx_dir, tex_source),
                                safe_join_within(
                                    os.path.join(fbx_dir, "textures"), tex_source
                                ),
                                safe_join_within(os.path.dirname(fbx_path), tex_source),
                            ]

                            for path in search_paths:
                                if path and os.path.exists(path):
                                    texture_file = path
                                    break

                            if texture_file:
                                # Add new image, embedded immediately as a data
                                # URI — a bare filename URI would leave the GLB
                                # with a dangling external reference.
                                with open(texture_file, "rb") as tf:
                                    tex_bytes = tf.read()
                                ext = os.path.splitext(texture_file)[1].lower()
                                mime = {
                                    ".png": "image/png",
                                    ".jpg": "image/jpeg",
                                    ".jpeg": "image/jpeg",
                                    ".webp": "image/webp",
                                }.get(ext, "image/png")
                                img_idx = len(gltf.images) if gltf.images else 0
                                new_img = Image(
                                    uri=f"data:{mime};base64,{base64.b64encode(tex_bytes).decode('utf-8')}"
                                )
                                if gltf.images is None:
                                    gltf.images = []
                                gltf.images.append(new_img)

                                # Add new texture
                                tex_idx = len(gltf.textures) if gltf.textures else 0
                                new_tex = Texture(source=img_idx)
                                if gltf.textures is None:
                                    gltf.textures = []
                                gltf.textures.append(new_tex)

                                # Assign to material
                                if mat.pbrMetallicRoughness is None:
                                    mat.pbrMetallicRoughness = PbrMetallicRoughness()
                                mat.pbrMetallicRoughness.baseColorTexture = TextureInfo(
                                    index=tex_idx
                                )
                                self.log_operation(
                                    f"  ✅ Recovered texture for material '{mat_name}': {os.path.basename(texture_file)}"
                                )

            if gltf.images:
                # Convert buffer-embedded images to data URIs
                binary_blob = gltf.binary_blob()
                for i, img in enumerate(gltf.images):
                    if binary_blob and img.bufferView is not None:
                        try:
                            buffer_view = gltf.bufferViews[img.bufferView]
                            offset = buffer_view.byteOffset if buffer_view.byteOffset else 0
                            length = buffer_view.byteLength

                            image_data = binary_blob[offset : offset + length]

                            # Determine MIME type
                            mime_type = "image/png"
                            if image_data[:4] == b"\x89PNG":
                                mime_type = "image/png"
                            elif image_data[:2] == b"\xff\xd8":
                                mime_type = "image/jpeg"

                            # Convert to data URI
                            data_uri = f"data:{mime_type};base64,{base64.b64encode(image_data).decode('utf-8')}"
                            img.uri = data_uri
                            img.bufferView = None
                            self.log_operation(f"Converted image {i} to data URI")
                        except Exception as e:
                            self.log_operation(
                                f"Warning: Could not convert image {i}: {e}", "WARNING"
                            )
            else:
                self.log_operation("No images found in GLB to embed")

            # Alpha-correctness pass (cutout → MASK, bogus factor alpha → clamp).
            # Runs after image conversion so the texture bytes are inspectable.
            fix_material_transparency(gltf, self.log_operation)

        except Exception as e:
            self.log_operation(f"Warning: Could not embed textures: {e}", "WARNING")

    def _embed_external_textures(self, glb_path: str, fbx_path: str) -> None:
        """Embed external texture files into GLB."""
        try:
            from pygltflib import GLTF2
            import base64

            # LOG: FBX directory contents (textures that came with FBX)
            fbx_dir = os.path.dirname(fbx_path)
            self.log_operation(f"📁 FBX Directory: {fbx_dir}")
            self.log_operation(f"📁 Scanning for texture files in FBX directory...")

            texture_extensions = {
                ".png",
                ".jpg",
                ".jpeg",
                ".tga",
                ".bmp",
                ".tif",
                ".tiff",
                ".webp",
            }
            found_textures = []

            try:
                for file in os.listdir(fbx_dir):
                    file_path = os.path.join(fbx_dir, file)
                    if os.path.isfile(file_path):
                        ext = os.path.splitext(file)[1].lower()
                        if ext in texture_extensions:
                            size = os.path.getsize(file_path)
                            found_textures.append((file, size, ext))
                            self.log_operation(
                                f"  🖼️  Found: {file} ({size} bytes, {ext})"
                            )

                if not found_textures:
                    self.log_operation(f"  ⚠️  No texture files found in FBX directory")
                else:
                    self.log_operation(
                        f"  ✅ Total textures found: {len(found_textures)}"
                    )
            except Exception as e:
                self.log_operation(f"  ⚠️  Error scanning FBX directory: {e}")

            self.log_operation(f"Loading GLB to embed textures: {glb_path}")
            gltf = GLTF2().load(glb_path)

            if not gltf.images:
                self.log_operation(
                    "No images found in GLB - FBX2glTF may have discarded textures"
                )
                # This is the critical recovery path for FBX files whose
                # converter output has materials but omits the image list.
                # The probe may still have extracted the source maps, and the
                # in-memory helper can bind/embed them before this GLB is
                # published as a single-file asset.
                self._embed_external_textures_gltf(gltf, fbx_path)
                if gltf.images:
                    gltf.save(glb_path)
                    self.log_operation("Recovered and embedded missing FBX textures")
                    return
                # Still clamp bogus FBX factor alphas so the model can't go
                # invisible if anything later switches it to BLEND.
                if fix_material_transparency(gltf, self.log_operation):
                    gltf.save(glb_path)
                return

            self.log_operation(
                f"📦 GLB Analysis: Found {len(gltf.images)} images in GLB"
            )
            self.log_operation(f"📦 Image Details:")

            has_buffer_images = False
            for i, img in enumerate(gltf.images):
                if img.uri:
                    if img.uri.startswith("data:"):
                        uri_preview = (
                            img.uri[:50] + "..." if len(img.uri) > 50 else img.uri
                        )
                        self.log_operation(
                            f"  🖼️  Image {i}: Data URI (embedded, {len(img.uri)} chars)"
                        )
                        self.log_operation(f"       Preview: {uri_preview}")
                    else:
                        self.log_operation(f"  🖼️  Image {i}: External file - {img.uri}")
                        # Check if external file exists
                        external_path = os.path.join(fbx_dir, img.uri)
                        if os.path.exists(external_path):
                            size = os.path.getsize(external_path)
                            self.log_operation(f"       ✅ File exists: {size} bytes")
                        else:
                            self.log_operation(
                                f"       ❌ File NOT found at: {external_path}"
                            )
                elif img.bufferView is not None:
                    # Get buffer size
                    buffer_view = gltf.bufferViews[img.bufferView]
                    buffer_size = buffer_view.byteLength
                    self.log_operation(
                        f"  🖼️  Image {i}: Buffer-embedded (bufferView: {img.bufferView}, {buffer_size} bytes)"
                    )
                    has_buffer_images = True
                else:
                    self.log_operation(
                        f"  ⚠️  Image {i}: Unknown format (no URI, no bufferView)"
                    )

            # If images are embedded in buffer, convert to data URIs for model-viewer compatibility
            if has_buffer_images:
                self.log_operation(
                    "🔄 Converting buffer-embedded textures to data URIs for model-viewer"
                )
                try:
                    # Get binary blob
                    binary_blob = gltf.binary_blob()
                    if not binary_blob:
                        self.log_operation(
                            "⚠️  Warning: No binary blob found", "WARNING"
                        )
                        return

                    self.log_operation(f"📦 Binary blob size: {len(binary_blob)} bytes")

                    # Convert each buffer-embedded image to data URI
                    conversion_summary = []
                    for i, img in enumerate(gltf.images):
                        if img.bufferView is not None:
                            try:
                                # Get buffer view
                                buffer_view = gltf.bufferViews[img.bufferView]
                                offset = (
                                    buffer_view.byteOffset
                                    if buffer_view.byteOffset
                                    else 0
                                )
                                length = buffer_view.byteLength

                                self.log_operation(f"  🔄 Converting Image {i}:")
                                self.log_operation(
                                    f"     Buffer offset: {offset}, length: {length}"
                                )

                                # Extract image data from binary blob
                                image_data = binary_blob[offset : offset + length]

                                # Determine MIME type from image data
                                mime_type = "image/png"  # Default
                                if image_data[:4] == b"\x89PNG":
                                    mime_type = "image/png"
                                elif image_data[:2] == b"\xff\xd8":
                                    mime_type = "image/jpeg"
                                elif (
                                    image_data[:4] == b"RIFF"
                                    and image_data[8:12] == b"WEBP"
                                ):
                                    mime_type = "image/webp"

                                self.log_operation(f"     Detected format: {mime_type}")

                                # Convert to data URI
                                data_uri = f"data:{mime_type};base64,{base64.b64encode(image_data).decode('utf-8')}"

                                # Replace bufferView with data URI
                                img.uri = data_uri
                                img.bufferView = None

                                conversion_summary.append(
                                    {
                                        "index": i,
                                        "size": len(image_data),
                                        "mime": mime_type,
                                        "data_uri_size": len(data_uri),
                                    }
                                )

                                self.log_operation(
                                    f"     ✅ Converted to data URI: {len(image_data)} bytes → {len(data_uri)} chars"
                                )
                            except Exception as img_error:
                                self.log_operation(
                                    f"     ❌ Failed to convert image {i}: {img_error}",
                                    "WARNING",
                                )
                                conversion_summary.append(
                                    {"index": i, "error": str(img_error)}
                                )

                    # Summary
                    successful = len(
                        [c for c in conversion_summary if "error" not in c]
                    )
                    failed = len([c for c in conversion_summary if "error" in c])
                    self.log_operation(
                        f"🔄 Conversion Summary: {successful} successful, {failed} failed"
                    )

                    # Ensure all images have corresponding textures
                    from pygltflib import Texture, Sampler

                    if not gltf.textures:
                        gltf.textures = []
                    if not gltf.samplers:
                        gltf.samplers = []

                    # Create a default sampler if none exists
                    if len(gltf.samplers) == 0:
                        sampler = Sampler()
                        sampler.magFilter = 9729  # LINEAR
                        sampler.minFilter = 9987  # LINEAR_MIPMAP_LINEAR
                        sampler.wrapS = 10497  # REPEAT
                        sampler.wrapT = 10497  # REPEAT
                        gltf.samplers.append(sampler)

                    # Map images to textures
                    image_to_texture = {}
                    for tex_idx, tex in enumerate(gltf.textures):
                        if tex.source is not None:
                            image_to_texture[tex.source] = tex_idx

                    # Create missing textures for images without them
                    for img_idx in range(len(gltf.images)):
                        if img_idx not in image_to_texture:
                            self.log_operation(
                                f"Creating missing texture for image {img_idx}"
                            )
                            texture = Texture()
                            texture.source = img_idx
                            texture.sampler = 0  # Use first sampler
                            tex_idx = len(gltf.textures)
                            gltf.textures.append(texture)
                            image_to_texture[img_idx] = tex_idx
                            self.log_operation(
                                f"  Created Texture {tex_idx} → Image {img_idx}"
                            )

                    # Alpha-correctness pass (cutout → MASK, semi-transparent →
                    # BLEND, bogus factor alpha → clamp to opaque).
                    fix_material_transparency(gltf, self.log_operation)

                    # Log mesh-material assignments
                    if gltf.meshes:
                        self.log_operation(
                            f"Mesh-Material assignments ({len(gltf.meshes)} meshes):"
                        )
                        for mesh_idx, mesh in enumerate(gltf.meshes):
                            mesh_name = mesh.name if mesh.name else f"Mesh_{mesh_idx}"
                            for prim_idx, prim in enumerate(mesh.primitives):
                                mat_idx = (
                                    prim.material
                                    if prim.material is not None
                                    else "None"
                                )
                                mat_name = (
                                    gltf.materials[prim.material].name
                                    if prim.material is not None
                                    and prim.material < len(gltf.materials)
                                    else "Unknown"
                                )
                                self.log_operation(
                                    f"  {mesh_name}[{prim_idx}] → Material {mat_idx} ({mat_name})"
                                )

                    # Log material-texture assignments for debugging
                    if gltf.materials:
                        self.log_operation(
                            f"Material-Texture assignments ({len(gltf.materials)} materials):"
                        )
                        for i, mat in enumerate(gltf.materials):
                            mat_name = mat.name if mat.name else f"Material_{i}"
                            if (
                                mat.pbrMetallicRoughness
                                and mat.pbrMetallicRoughness.baseColorTexture
                            ):
                                tex_idx = (
                                    mat.pbrMetallicRoughness.baseColorTexture.index
                                )
                                img_idx = (
                                    gltf.textures[tex_idx].source
                                    if tex_idx < len(gltf.textures)
                                    else "?"
                                )
                                self.log_operation(
                                    f"  Material {i} ({mat_name}): Texture {tex_idx} → Image {img_idx}"
                                )
                            else:
                                self.log_operation(
                                    f"  Material {i} ({mat_name}): No baseColorTexture ❌"
                                )

                    # Log all textures
                    if gltf.textures:
                        self.log_operation(
                            f"All Textures ({len(gltf.textures)} total):"
                        )
                        for tex_idx, tex in enumerate(gltf.textures):
                            img_idx = tex.source if tex.source is not None else "None"
                            self.log_operation(f"  Texture {tex_idx} → Image {img_idx}")

                    # FINAL SUMMARY
                    self.log_operation("=" * 60)
                    self.log_operation("📊 TEXTURE EMBEDDING SUMMARY")
                    self.log_operation("=" * 60)
                    self.log_operation(
                        f"📁 Textures in FBX directory: {len(found_textures)}"
                    )
                    self.log_operation(
                        f"📦 Images in GLB (from FBX2glTF): {len(gltf.images)}"
                    )
                    self.log_operation(f"🔄 Images converted to Data URI: {successful}")
                    self.log_operation(
                        f"🎨 Textures in GLB: {len(gltf.textures) if gltf.textures else 0}"
                    )
                    self.log_operation(
                        f"🎭 Materials in GLB: {len(gltf.materials) if gltf.materials else 0}"
                    )

                    # Check which textures are actually used
                    used_textures = set()
                    if gltf.materials:
                        for mat in gltf.materials:
                            if (
                                mat.pbrMetallicRoughness
                                and mat.pbrMetallicRoughness.baseColorTexture
                            ):
                                used_textures.add(
                                    mat.pbrMetallicRoughness.baseColorTexture.index
                                )

                    unused_count = (
                        len(gltf.textures) - len(used_textures) if gltf.textures else 0
                    )
                    self.log_operation(
                        f"✅ Textures assigned to materials: {len(used_textures)}"
                    )
                    self.log_operation(f"⚠️  Unused textures: {unused_count}")
                    self.log_operation("=" * 60)

                    # Save with data URIs
                    temp_path = glb_path.replace(".glb", "_temp.glb")
                    gltf.save(temp_path)

                    if os.path.exists(temp_path):
                        temp_size = os.path.getsize(temp_path)
                        self.log_operation(f"Temp GLB created: {temp_size} bytes")

                        import shutil

                        shutil.move(temp_path, glb_path)

                        final_size = os.path.getsize(glb_path)
                        self.log_operation(
                            f"✅ GLB re-exported with data URI textures: {final_size} bytes"
                        )
                        return
                    else:
                        self.log_operation(
                            "Warning: Temp file was not created", "WARNING"
                        )
                except Exception as e:
                    self.log_operation(
                        f"Warning: Could not convert textures: {e}", "WARNING"
                    )
                    import traceback

                    self.log_operation(
                        f"Traceback: {traceback.format_exc()}", "WARNING"
                    )

            fbx_dir = os.path.dirname(fbx_path)
            glb_dir = os.path.dirname(glb_path)
            modified = False

            for i, image in enumerate(gltf.images):
                # Check if image has external URI (not embedded)
                if image.uri and not image.uri.startswith("data:"):
                    self.log_operation(f"Found external texture: {image.uri}")

                    # Try multiple locations for texture file
                    texture_path = None
                    search_paths = [
                        os.path.join(glb_dir, image.uri),  # Same dir as GLB
                        os.path.join(fbx_dir, image.uri),  # Same dir as FBX
                        os.path.join(
                            glb_dir, os.path.basename(image.uri)
                        ),  # GLB dir, filename only
                        os.path.join(
                            fbx_dir, os.path.basename(image.uri)
                        ),  # FBX dir, filename only
                    ]

                    for path in search_paths:
                        if os.path.exists(path):
                            texture_path = path
                            break

                    if not texture_path:
                        self.log_operation(
                            f"Warning: Texture file not found in any location: {image.uri}",
                            "WARNING",
                        )
                        self.log_operation(f"Searched: {search_paths}", "WARNING")
                        continue

                    self.log_operation(f"Embedding texture: {texture_path}")

                    # Read texture file
                    with open(texture_path, "rb") as f:
                        texture_data = f.read()

                    # Determine MIME type
                    ext = os.path.splitext(texture_path)[1].lower()
                    mime_type = {
                        ".png": "image/png",
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".webp": "image/webp",
                    }.get(ext, "image/png")

                    # Convert to data URI
                    data_uri = f"data:{mime_type};base64,{base64.b64encode(texture_data).decode('utf-8')}"
                    image.uri = data_uri
                    modified = True
                    self.log_operation(
                        f"Embedded texture {i}: {len(texture_data)} bytes"
                    )

            # Alpha-correctness pass for the no-buffer-images path (the buffer
            # path above runs it before saving and returns early).
            if fix_material_transparency(gltf, self.log_operation):
                modified = True

            if modified:
                self.log_operation("Saving GLB with embedded textures")
                gltf.save(glb_path)
                self.log_operation("✅ Textures embedded successfully")
            else:
                self.log_operation("No external textures to embed")

        except Exception as e:
            self.log_operation(f"Error embedding textures: {e}", "ERROR")
            import traceback

            self.log_operation(f"Traceback: {traceback.format_exc()}")
            raise
