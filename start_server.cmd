@echo off
cls
echo.
echo Web AR Sunucusu Baslatiliyor...
echo ==============================
echo.

REM Virtual environment kontrolü
if not exist "venv" (
    echo [HATA] Virtual environment bulunamadi!
    echo Lutfen once 'install.cmd' dosyasini calistirin.
    pause
    exit /b 1
)

REM Virtual environment'ı aktifleştir
echo Virtual environment aktif ediliyor...
call venv\Scripts\activate
if %errorlevel% neq 0 (
    echo [HATA] Virtual environment aktif edilemedi!
    pause
    exit /b 1
)

REM Flask uygulamasını başlat
echo.
echo Flask sunucusu baslatiliyor...
echo Durdurmak icin bu pencereyi kapatabilir
echo veya 'stop_server.cmd' dosyasini calistirabilirsiniz.
echo.
echo Tarayicinizda http://localhost:5000 adresine gidin...
echo.

python app.py

REM Eğer Flask çökerse, kullanıcıya bilgi ver
if %errorlevel% neq 0 (
    echo.
    echo [HATA] Flask sunucusu beklenmedik sekilde durdu!
    echo Hata kodu: %errorlevel%
    echo.
    echo Olasi cozumler:
    echo 1. 'install.cmd' ile kurulumu tekrar yapin
    echo 2. Port 5000'in baska bir uygulama tarafindan kullanilmadiginden emin olun
    echo 3. Sistem yoneticisi olarak calistirmayi deneyin
    echo.
    pause
    exit /b 1
)
pause
