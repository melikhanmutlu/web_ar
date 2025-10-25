"""
ARVision - Build Script for Standalone EXE
This script helps create a standalone executable for the ARVision application.
"""

import os
import sys

# PyInstaller build command
build_command = """
pyinstaller --name=ARVision ^
    --onefile ^
    --windowed ^
    --icon=static/favicon.ico ^
    --add-data "templates;templates" ^
    --add-data "static;static" ^
    --add-data "converters;converters" ^
    --hidden-import=flask ^
    --hidden-import=flask_sqlalchemy ^
    --hidden-import=flask_login ^
    --hidden-import=flask_migrate ^
    --hidden-import=trimesh ^
    --hidden-import=pygltflib ^
    --hidden-import=PIL ^
    --hidden-import=qrcode ^
    --collect-all trimesh ^
    --collect-all pygltflib ^
    app.py
"""

print("=" * 60)
print("ARVision - Standalone EXE Builder")
print("=" * 60)
print("\nThis will create a standalone executable for ARVision.")
print("\nNOTE: The EXE will be quite large (100-200MB) because it includes:")
print("  - Python interpreter")
print("  - All dependencies (Flask, Trimesh, etc.)")
print("  - Templates and static files")
print("\n" + "=" * 60)
print("\nTo build, run this command in terminal:")
print("\n" + build_command)
print("\n" + "=" * 60)
