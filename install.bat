@echo off
set "TARGET=%APPDATA%\inkscape\extensions\Bom_Publish"

if not exist "%TARGET%" mkdir "%TARGET%"

echo Copying extension files to %TARGET%...
xcopy /Y /S /I "%~dp0*" "%TARGET%"

echo Done. Restart Inkscape to see the changes.
pause
