"""
Script to update dimensions for existing models
"""
import os
import sys
import trimesh
import numpy as np
from app import app, db, UserModel

def update_model_dimensions():
    """Update dimensions for all models in database"""
    with app.app_context():
        models = UserModel.query.all()
        total = len(models)
        updated = 0
        failed = 0
        
        print(f"\n{'='*60}")
        print(f"Found {total} models to process")
        print(f"{'='*60}\n")
        
        for i, model in enumerate(models, 1):
            print(f"[{i}/{total}] Processing model: {model.id}")
            
            if not model.filename or not os.path.exists(model.filename):
                print(f"  ❌ File not found: {model.filename}")
                failed += 1
                continue
            
            try:
                # Load the GLB file
                mesh = trimesh.load(model.filename)
                
                # Get extents
                if isinstance(mesh, trimesh.Scene):
                    # For Scene, combine all vertices
                    all_vertices = []
                    for geom in mesh.geometry.values():
                        if isinstance(geom, trimesh.Trimesh):
                            all_vertices.append(geom.vertices)
                    
                    if all_vertices:
                        combined_vertices = np.vstack(all_vertices)
                        min_bounds = combined_vertices.min(axis=0)
                        max_bounds = combined_vertices.max(axis=0)
                        extents = max_bounds - min_bounds
                    else:
                        bounds = mesh.bounds
                        extents = bounds[1] - bounds[0]
                else:
                    extents = mesh.extents
                
                # Check if valid
                if max(extents) > 0.001:  # At least 0.1 cm
                    # Convert to cm
                    x_cm = round(float(extents[0]) * 100, 2)
                    y_cm = round(float(extents[1]) * 100, 2)
                    z_cm = round(float(extents[2]) * 100, 2)
                    max_cm = round(float(max(extents)) * 100, 2)
                    
                    # Store as JSON string in bounds field
                    import json
                    bounds_data = {
                        'extents': [x_cm, y_cm, z_cm],
                        'max': max_cm
                    }
                    model.bounds = json.dumps(bounds_data)
                    
                    print(f"  ✅ Dimensions: {x_cm} x {y_cm} x {z_cm} cm (max: {max_cm} cm)")
                    updated += 1
                else:
                    print(f"  ⚠️  Invalid dimensions (all zero)")
                    failed += 1
                    
            except Exception as e:
                print(f"  ❌ Error: {str(e)}")
                failed += 1
        
        # Commit all changes
        try:
            db.session.commit()
            print(f"\n{'='*60}")
            print(f"✅ Database updated successfully!")
            print(f"{'='*60}")
        except Exception as e:
            db.session.rollback()
            print(f"\n❌ Database commit failed: {str(e)}")
        
        # Summary
        print(f"\n📊 SUMMARY:")
        print(f"   Total models: {total}")
        print(f"   Updated: {updated}")
        print(f"   Failed: {failed}")
        print(f"   Success rate: {(updated/total*100):.1f}%\n")

if __name__ == '__main__':
    update_model_dimensions()
