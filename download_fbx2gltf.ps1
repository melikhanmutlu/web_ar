# Download FBX2glTF Linux binary for Railway deployment
Write-Host "Downloading FBX2glTF Linux binary..." -ForegroundColor Cyan

# Create tools directory if it doesn't exist
$toolsDir = "tools"
if (-not (Test-Path $toolsDir)) {
    New-Item -ItemType Directory -Path $toolsDir | Out-Null
}

# GitHub release URL
$releaseUrl = "https://api.github.com/repos/facebookincubator/FBX2glTF/releases/latest"

try {
    # Get latest release info
    Write-Host "Fetching latest release info..." -ForegroundColor Yellow
    $release = Invoke-RestMethod -Uri $releaseUrl
    
    # Find Linux x64 asset
    $asset = $release.assets | Where-Object { $_.name -like "*linux-x64*" }
    
    if ($asset) {
        $downloadUrl = $asset.browser_download_url
        $outputPath = Join-Path $toolsDir "FBX2glTF"
        
        Write-Host "Downloading from: $downloadUrl" -ForegroundColor Yellow
        Invoke-WebRequest -Uri $downloadUrl -OutFile $outputPath
        
        Write-Host "✅ Downloaded successfully to: $outputPath" -ForegroundColor Green
        Write-Host ""
        Write-Host "Next steps:" -ForegroundColor Cyan
        Write-Host "1. git add tools/FBX2glTF" -ForegroundColor White
        Write-Host "2. git commit -m 'Add Linux FBX2glTF binary'" -ForegroundColor White
        Write-Host "3. git push origin main" -ForegroundColor White
    } else {
        Write-Host "❌ Linux x64 binary not found in latest release" -ForegroundColor Red
        Write-Host "Please download manually from: https://github.com/facebookincubator/FBX2glTF/releases" -ForegroundColor Yellow
    }
} catch {
    Write-Host "❌ Error: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "Manual download:" -ForegroundColor Yellow
    Write-Host "1. Go to: https://github.com/facebookincubator/FBX2glTF/releases/latest" -ForegroundColor White
    Write-Host "2. Download: FBX2glTF-linux-x64" -ForegroundColor White
    Write-Host "3. Save to: tools/FBX2glTF (no extension)" -ForegroundColor White
}
