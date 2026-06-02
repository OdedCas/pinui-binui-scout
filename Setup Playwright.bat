@echo off
echo ============================================
echo  Bat Yam GIS - API Discovery via Playwright
echo ============================================
echo.

cd /d "C:\Users\cassu\OneDrive - oren\Desktop\ramat yosef"

echo [1/3] Installing playwright...
pip install playwright -q
if errorlevel 1 (
    echo ERROR: pip install failed. Make sure Python is in PATH.
    pause
    exit /b 1
)

echo [2/3] Installing Chromium browser...
python -m playwright install chromium
if errorlevel 1 (
    echo ERROR: browser install failed.
    pause
    exit /b 1
)

echo [3/3] Running discovery...
echo.
echo A browser window will open. Watch it navigate Bat Yam GIS.
echo Results will be saved to outputs\batyam_gis_apis.json
echo.
python playwright_discover.py

echo.
echo Done. Check outputs\batyam_gis_apis.json for discovered APIs.
pause
