#!/usr/bin/env python3
"""Debug GLB material and texture assignments"""

from pygltflib import GLTF2
import sys

if len(sys.argv) < 2:
    print("Usage: python debug_glb.py <glb_file>")
    sys.exit(1)

glb_path = sys.argv[1]
print(f"Loading: {glb_path}\n")

gltf = GLTF2().load(glb_path)

print(f"📊 GLB Structure:")
print(f"  Materials: {len(gltf.materials) if gltf.materials else 0}")
print(f"  Textures: {len(gltf.textures) if gltf.textures else 0}")
print(f"  Images: {len(gltf.images) if gltf.images else 0}")
print(f"  Meshes: {len(gltf.meshes) if gltf.meshes else 0}")
print()

# Material details
if gltf.materials:
    print("🎨 Materials:")
    for i, mat in enumerate(gltf.materials):
        print(f"\n  Material {i}:")
        if mat.name:
            print(f"    Name: {mat.name}")
        
        if mat.pbrMetallicRoughness:
            pbr = mat.pbrMetallicRoughness
            print(f"    PBR:")
            
            # Base color
            if pbr.baseColorFactor:
                print(f"      baseColorFactor: {pbr.baseColorFactor}")
            
            # Base color texture
            if pbr.baseColorTexture:
                tex_idx = pbr.baseColorTexture.index
                print(f"      baseColorTexture: index={tex_idx}")
                
                # Get texture details
                if gltf.textures and tex_idx < len(gltf.textures):
                    texture = gltf.textures[tex_idx]
                    if texture.source is not None:
                        img = gltf.images[texture.source]
                        if img.uri:
                            if img.uri.startswith('data:'):
                                print(f"        → Image {texture.source}: Data URI ({len(img.uri)} chars)")
                            else:
                                print(f"        → Image {texture.source}: {img.uri}")
                        elif img.bufferView is not None:
                            print(f"        → Image {texture.source}: Buffer (bufferView: {img.bufferView})")
            else:
                print(f"      baseColorTexture: None ❌")
            
            print(f"      metallicFactor: {pbr.metallicFactor}")
            print(f"      roughnessFactor: {pbr.roughnessFactor}")
        else:
            print(f"    No PBR properties ❌")

# Mesh-Material assignments
if gltf.meshes:
    print("\n\n🔗 Mesh-Material Assignments:")
    for i, mesh in enumerate(gltf.meshes):
        print(f"\n  Mesh {i}:")
        if mesh.name:
            print(f"    Name: {mesh.name}")
        
        for j, prim in enumerate(mesh.primitives):
            mat_idx = prim.material if prim.material is not None else "None"
            print(f"    Primitive {j}: Material {mat_idx}")
