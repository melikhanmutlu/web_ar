@echo off
cls
echo.
echo Web AR Kurulum Scripti
echo =====================
echo.
echo SISTEM GEREKLILIKLERI:
echo ---------------------
echo 1. Python 3.8 veya daha yeni surumu
echo    - https://www.python.org/downloads/
echo    - Kurulum sirasinda "Add Python to PATH" secenegini isaretleyin!
echo.
echo 2. Node.js 14.x veya daha yeni surumu
echo    - https://nodejs.org/
echo    - LTS (Long Term Support) surumunu indirin
echo.
echo KURULUM ADIMLARI:
echo ---------------
echo 1. Gerekli yazilimlari yukleyin (Python ve Node.js)
echo 2. Bu scripti calistirin
echo 3. Kurulum tamamlandiginda 'start_server.cmd' ile sunucuyu baslatin
echo 4. Web tarayicinizda http://localhost:5000 adresine gidin
echo.
echo DEVAM ETMEK ICIN BIR TUSA BASIN...
pause > nul

cls
echo Sistem kontrolu yapiliyor...
echo ===========================
echo.

REM Python kontrolü
python --version >nul 2>&1
if %errorlevel% neq 0 (
    REM 'python' çalışmadıysa 'py' komutu ile dene
    py --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo [HATA] Python bulunamadi! Lutfen asagidaki adimlari takip edin:
        echo 1. https://www.python.org/downloads/ adresinden Python 3.8 veya daha yeni surumu indirin
        echo 2. Kurulum sirasinda "Add Python to PATH" secenegini isaretleyin
        echo 3. Kurulum tamamlandiktan sonra bilgisayarinizi yeniden baslatin
        echo 4. Bu scripti tekrar calistirin
        pause
        exit /b 1
    ) else (
        set PYTHON_CMD=py
        echo [OK] Python bulundu (py komutu)
    )
) else (
    set PYTHON_CMD=python
    echo [OK] Python bulundu (python komutu)
)

REM Node.js kontrolü
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [HATA] Node.js bulunamadi! Lutfen asagidaki adimlari takip edin:
    echo 1. https://nodejs.org/ adresinden Node.js'i indirin
    echo 2. Kurulum tamamlandiktan sonra bilgisayarinizi yeniden baslatin
    echo 3. Bu scripti tekrar calistirin
    pause
    exit /b 1
) else (
    echo [OK] Node.js bulundu
)

echo.
echo Gerekli klasorler olusturuluyor...
echo ==================================
mkdir uploads 2>nul && echo [OK] uploads klasoru olusturuldu
mkdir converted 2>nul && echo [OK] converted klasoru olusturuldu
mkdir temp 2>nul && echo [OK] temp klasoru olusturuldu
mkdir qr_codes 2>nul && echo [OK] qr_codes klasoru olusturuldu
mkdir instance 2>nul && echo [OK] instance klasoru olusturuldu

echo.
echo Virtual environment olusturuluyor...
echo ==================================
%PYTHON_CMD% -m venv venv
if %errorlevel% neq 0 (
    echo [HATA] Virtual environment olusturulamadi!
    echo Python kurulumunuzu kontrol edin ve tekrar deneyin.
    pause
    exit /b 1
) else (
    echo [OK] Virtual environment olusturuldu
)

echo.
echo Virtual environment aktif ediliyor...
echo ===================================
call venv\Scripts\activate
if %errorlevel% neq 0 (
    echo [HATA] Virtual environment aktif edilemedi!
    pause
    exit /b 1
) else (
    echo [OK] Virtual environment aktif edildi
)

echo.
echo Python paketleri yukleniyor...
echo =============================
%PYTHON_CMD% -m pip install --upgrade pip
if %errorlevel% neq 0 (
    echo [HATA] Pip guncellenemedi!
    pause
    exit /b 1
) else (
    echo [OK] Pip guncellendi
)

pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [HATA] Python paketleri yuklenemedi!
    pause
    exit /b 1
) else (
    echo [OK] Python paketleri yuklendi
)

echo.
echo Node.js paketleri yukleniyor...
echo ==============================
call npm install
if %errorlevel% neq 0 (
    echo [HATA] Node.js paketleri yuklenemedi!
    pause
    exit /b 1
) else (
    echo [OK] Node.js paketleri yuklendi
)

echo.
echo obj2gltf yukleniyor...
echo =====================
call npm install -g obj2gltf
if %errorlevel% neq 0 (
    echo [HATA] obj2gltf yuklenemedi!
    pause
    exit /b 1
) else (
    echo [OK] obj2gltf yuklendi
)

echo.
echo Veritabani olusturuluyor...
echo ==========================
%PYTHON_CMD% create_db.py
if %errorlevel% neq 0 (
    echo [HATA] Veritabani olusturulamadi!
    pause
    exit /b 1
) else (
    echo [OK] Veritabani olusturuldu
)

echo.
echo Migration sistemi kontrol ediliyor...
echo ==================================
if exist "migrations" (
    echo [OK] Migration klasoru zaten mevcut
) else (
    echo Migration klasoru olusturuluyor...
    %PYTHON_CMD% -m flask db init
    if %errorlevel% neq 0 (
        echo [HATA] Migration klasoru olusturulamadi!
        pause
        exit /b 1
    ) else (
        echo [OK] Migration klasoru olusturuldu
    )
)

echo.
echo Ilk migration olusturuluyor...
echo ============================
%PYTHON_CMD% -m flask db migrate -m "Initial migration"
if %errorlevel% neq 0 (
    echo [HATA] Migration olusturulamadi!
    pause
    exit /b 1
) else (
    echo [OK] Migration olusturuldu
)

echo.
echo Migration uygulaniyor...
echo ======================
%PYTHON_CMD% -m flask db upgrade
if %errorlevel% neq 0 (
    echo [HATA] Migration uygulanamadi!
    pause
    exit /b 1
) else (
    echo [OK] Migration uygulandi
)

echo.
echo =============================
echo Kurulum basariyla tamamlandi!
echo =============================
echo.
echo Sunucuyu baslatmak icin:
echo 1. 'start_server.cmd' dosyasini calistirin
echo 2. Web tarayicinizda http://localhost:5000 adresine gidin
echo.
echo Sunucuyu durdurmak icin:
echo - 'stop_server.cmd' dosyasini kullanin
echo   veya
echo - Komut penceresini kapatabilirsiniz
echo.
pause
