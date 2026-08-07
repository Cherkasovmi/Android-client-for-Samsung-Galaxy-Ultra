@echo off
echo ============================================
echo   People Recognition - Android Client
echo   Build Script for Windows
echo ============================================
echo.

echo Checking Python...
python --version
if errorlevel 1 (
    echo.
    echo ERROR: Python not found.
    echo Download and install Python 3.10+ from:
    echo   https://www.python.org/downloads/
    echo Be sure to check "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

echo.
echo Installing Kivy and dependencies...
pip install --index-url http://pypi.org/simple/ --trusted-host pypi.org --trusted-host files.pythonhosted.org kivy requests pillow
if errorlevel 1 (
    echo.
    echo ERROR: Failed to install dependencies.
    echo Check your internet connection.
    pause
    exit /b 1
)

echo.
echo Installing Buildozer...
pip install --index-url http://pypi.org/simple/ --trusted-host pypi.org --trusted-host files.pythonhosted.org buildozer cython
if errorlevel 1 (
    echo.
    echo WARNING: Buildozer install failed.
    echo For APK building you also need Java JDK 17 and Android SDK.
    echo   Java: https://adoptium.net/
    echo   Git: https://git-scm.com/
    echo.
    echo After installing, run manually:
    echo   cd client_android
    echo   buildozer -v android debug
    echo.
    goto :end
)

echo.
echo Setting up build folder...
set INSTALL_DIR=%LOCALAPPDATA%\PeopleRecognitionAndroid
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

copy /Y "client_android.py" "%INSTALL_DIR%\"
copy /Y "requirements.txt" "%INSTALL_DIR%\"
copy /Y "buildozer.spec" "%INSTALL_DIR%\"

echo.
echo Building APK...
cd /d "%INSTALL_DIR%"
buildozer -v android debug
cd /d "%~dp0"

echo.
echo ============================================
echo   Done!
echo ============================================
echo.
echo APK location: %INSTALL_DIR%\bin\
echo.
echo To run on Android:
echo   1. Transfer the .apk to your device
echo   2. Open the APK
echo   3. Enter server address
echo.
echo To run on PC:
echo   python client_android.py http://SERVER_IP:8000
echo.
pause

:end