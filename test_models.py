import os
import requests
import time
import glob
from pathlib import Path

BASE_URL = "http://127.0.0.1:5000"

def find_model_file(directory, extensions=['.obj', '.mtl', '.stl', '.fbx']):
    """Find model files in the given directory"""
    if os.path.isfile(directory):
        return directory
    
    for ext in extensions:
        files = glob.glob(os.path.join(directory, f"*{ext}"))
        if files:
            return files[0]
    return None

def test_model_upload(path):
    print(f"\nTesting upload for: {path}")
    
    # Find the actual model file if path is a directory
    model_file = find_model_file(path)
    if not model_file:
        print(f"No model file found in: {path}")
        return
        
    print(f"Using model file: {model_file}")
    
    # Prepare the file for upload
    try:
        with open(model_file, 'rb') as f:
            files = {
                'file': (os.path.basename(model_file), f, 'application/octet-stream')
            }
            
            # Upload the file
            response = requests.post(f"{BASE_URL}/upload", files=files)
            response.raise_for_status()
            result = response.json()
            print(f"Upload response: {result}")
            
            if 'model_id' in result:
                model_id = result['model_id']
                
                # If it's an STL file, test color update
                if model_file.lower().endswith('.stl'):
                    print("Testing color update for STL model...")
                    color_response = requests.post(
                        f"{BASE_URL}/api/update-model-color",
                        json={'model_id': model_id, 'color': '#FF0000'}
                    )
                    print(f"Color update response: {color_response.json()}")
                
                # Wait for conversion to complete
                time.sleep(2)
                
                # Check if the converted file exists
                converted_path = os.path.join('converted', f"{model_id}.glb")
                if os.path.exists(converted_path):
                    print(f"✓ Conversion successful: {converted_path}")
                else:
                    print(f"✗ Conversion failed: {converted_path} not found")
                    
    except Exception as e:
        print(f"Error testing {os.path.basename(path)}: {str(e)}")

def main():
    # Test models
    models = [
        r"C:\Users\syste\CascadeProjects\web_ar\3D Modeller\Australian_Cattle_Dog_v1_L3.123c9c6a5764-399b-4e86-9897-6bcb08b5e8ed",
        r"C:\Users\syste\CascadeProjects\web_ar\3D Modeller\AirFunnel_XL.stl",
        r"C:\Users\syste\CascadeProjects\web_ar\3D Modeller\ağaç modeli - fbx obj mtl\Tree.fbx"
    ]
    
    for model_path in models:
        if os.path.exists(model_path):
            test_model_upload(model_path)
        else:
            print(f"Model not found: {model_path}")

if __name__ == "__main__":
    main()
