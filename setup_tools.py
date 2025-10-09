import os
import requests
from config import TOOLS_DIR

def download_file(url, local_path):
    """Download a file from URL to local path."""
    response = requests.get(url, stream=True)
    response.raise_for_status()
    
    with open(local_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

def setup_fbx2gltf():
    """Setup FBX2GLTF converter."""
    os.makedirs(TOOLS_DIR, exist_ok=True)
    
    # URL for FBX2GLTF
    fbx2gltf_url = "https://github.com/facebookincubator/FBX2glTF/releases/download/v0.9.7/FBX2glTF-windows-x64.exe"
    exe_path = os.path.join(TOOLS_DIR, "FBX2glTF.exe")
    
    try:
        # Download FBX2GLTF
        download_file(fbx2gltf_url, exe_path)
        print("FBX2GLTF installed successfully!")
        return True
    except Exception as e:
        print(f"Error installing FBX2GLTF: {str(e)}")
        return False

def setup_obj2gltf():
    try:
        # Install obj2gltf using npm
        print("Installing obj2gltf...")
        os.system("npm install -g obj2gltf")
        print("obj2gltf installed successfully!")
        return True
    except Exception as e:
        print(f"Error installing obj2gltf: {str(e)}")
        return False

if __name__ == "__main__":
    print("Setting up conversion tools...")
    
    # Install required Python package
    os.system(f"{sys.executable} -m pip install requests")
    
    # Setup FBX2GLTF
    if setup_fbx2gltf():
        print("FBX2GLTF setup completed successfully!")
    else:
        print("Failed to setup FBX2GLTF")
    
    # Setup obj2gltf
    if setup_obj2gltf():
        print("obj2gltf setup completed successfully!")
    else:
        print("Failed to setup obj2gltf")
    
    print("Setup complete!")
