@echo off
REM Set OSGeo4W environment and launch VS Code

set OSGEO4W_ROOT=C:\Program Files\QGIS 3.40.7
set PATH=%OSGEO4W_ROOT%\bin;%PATH%
set GDAL_DATA=%OSGEO4W_ROOT%\share\gdal
set PROJ_LIB=%OSGEO4W_ROOT%\share\proj


call "%OSGEO4W_ROOT%\bin\o4w_env.bat"
call "%OSGEO4W_ROOT%\bin\py3_env.bat"

"C:\Program Files\Microsoft VS Code\Code.exe"