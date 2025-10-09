const https = require('https');
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const FBX2GLTF_VERSION = '0.9.7';
const TOOLS_DIR = path.join(__dirname, 'tools');

// Platform kontrolü
const platform = process.platform;
const fbx2gltfFileName = platform === 'win32' ? 'FBX2glTF-windows-x64.exe' :
                        platform === 'darwin' ? 'FBX2glTF-macos-x64' :
                        'FBX2glTF-linux-x64';

const downloadUrl = `https://github.com/facebookincubator/FBX2glTF/releases/download/v${FBX2GLTF_VERSION}/${fbx2gltfFileName}`;

// Tools klasörünü oluştur
if (!fs.existsSync(TOOLS_DIR)) {
    fs.mkdirSync(TOOLS_DIR);
}

console.log('FBX2glTF indiriliyor...');

// FBX2glTF indir
const file = fs.createWriteStream(path.join(TOOLS_DIR, fbx2gltfFileName));
https.get(downloadUrl, (response) => {
    response.pipe(file);
    file.on('finish', () => {
        file.close();
        console.log('FBX2glTF indirildi');
        
        // Linux/macOS için çalıştırma izni ver
        if (platform !== 'win32') {
            try {
                execSync(`chmod +x ${path.join(TOOLS_DIR, fbx2gltfFileName)}`);
                console.log('Çalıştırma izni verildi');
            } catch (error) {
                console.error('Çalıştırma izni verirken hata:', error);
            }
        }
    });
}).on('error', (err) => {
    fs.unlink(path.join(TOOLS_DIR, fbx2gltfFileName));
    console.error('İndirme hatası:', err);
});
