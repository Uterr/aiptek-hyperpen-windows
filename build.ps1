# Builds dist\AiptekTablet.exe (single file, no Python needed on the target PC).
# Requirements on the build machine only:  python -m pip install pyinstaller pystray pillow
Set-Location $PSScriptRoot
python -c "import app; app.icon_image(256).save('icon.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"
if ($LASTEXITCODE) { throw "icon generation failed" }
# PyInstaller logs to stderr; run it through cmd so PowerShell doesn't treat that as an error
cmd /c "python -m PyInstaller --noconfirm --clean --log-level WARN --onefile --windowed --name AiptekTablet --icon icon.ico --hidden-import pystray._win32 --exclude-module numpy --exclude-module PIL.ImageQt --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide6 --exclude-module gi app.py 2>&1"
if ($LASTEXITCODE) { throw "PyInstaller failed" }
Write-Host "Built: $PSScriptRoot\dist\AiptekTablet.exe"
