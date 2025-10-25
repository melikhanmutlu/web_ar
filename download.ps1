$url = "https://github.com/facebookincubator/FBX2glTF/releases/download/v0.13.1/FBX2glTF-linux-x64"
$output = "tools/FBX2glTF"

Write-Host "Downloading FBX2glTF Linux binary..." -ForegroundColor Cyan
Invoke-WebRequest -Uri $url -OutFile $output
Write-Host "Download complete!" -ForegroundColor Green
