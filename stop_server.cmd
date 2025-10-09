@echo off
echo.
echo Web AR Sunucusu Durduruluyor...
echo ==============================
echo.

REM Python süreçlerini bul ve sonlandır
echo Flask sunucusu araniyor...
tasklist /FI "IMAGENAME eq python.exe" 2>NUL | find /I /N "python.exe">NUL
if %errorlevel% equ 0 (
    echo Flask sunucusu bulundu, durduruluyor...
    taskkill /F /IM python.exe >NUL 2>&1
    if %errorlevel% equ 0 (
        echo [OK] Flask sunucusu durduruldu.
    ) else (
        echo [HATA] Flask sunucusu durdurulamadi!
        echo Lutfen Task Manager'dan manuel olarak durdurun.
    )
) else (
    echo [BILGI] Calisan Flask sunucusu bulunamadi.
)

echo.
pause
