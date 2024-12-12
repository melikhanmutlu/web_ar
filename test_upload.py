import requests
import os

def test_upload():
    url = 'http://localhost:5000/upload'
    base_dir = r'C:\Users\syste\CascadeProjects\web_ar\3D Modeller\Australian_Cattle_Dog_v1_L3.123c9c6a5764-399b-4e86-9897-6bcb08b5e8ed\Australian_Cattle_Dog_v1_L3.123c9c6a5764-399b-4e86-9897-6bcb08b5e8ed'
    obj_file = os.path.join(base_dir, '13463_Australian_Cattle_Dog_v3.obj')
    
    print(f"Attempting to upload file: {obj_file}")
    
    # Ensure file exists
    if not os.path.exists(obj_file):
        print(f"Error: File not found at {obj_file}")
        # List directory contents to debug
        print("\nDirectory contents:")
        for item in os.listdir(base_dir):
            print(f"- {item}")
        return
        
    files = {
        'file': open(obj_file, 'rb')
    }
    
    data = {
        'apply_color': 'false'
    }
    
    try:
        response = requests.post(url, files=files, data=data)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        files['file'].close()

if __name__ == '__main__':
    test_upload()
