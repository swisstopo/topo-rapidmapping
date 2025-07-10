@echo off
REM Set codepage to UTF-8 to handle special characters (umlauts, etc.)
chcp 65001 >nul

REM ###############################################################################
REM ADS100 Flightline Mosaic and COG Creator (Windows Version)
REM
REM This script processes exports of ADS100 flightlines (GeoTIFF files) and
REM generates a seamless mosaic, then converts it into a Cloud Optimized GeoTIFF
REM (COG) containing the RGB bands. Based on https://github.com/geostandards-ch/cog-best-practices
REM
REM Features:
REM - Interactive prompts for input/output directories, filename, and GSD (Ground Sample Distance)
REM - Automatic creation of output directory if it doesn't exist
REM - Uses GDAL tools (gdalbuildvrt, gdalwarp, gdal_translate) for efficient processing
REM - Handles large datasets with multi-threading and optimized settings
REM
REM Requirements:
REM - Windows Command Prompt
REM - GDAL installed and available in PATH (with support for COG and JPEG compression)
REM
REM Usage:
REM   1. Save this script as rm_publish_quickorthophoto.bat
REM   2. Double-click the script or run from command prompt:
REM        rm_publish_quickorthophoto.bat
REM   3. Follow the prompts to specify:
REM        - Input directory containing .tif files (ADS100 flightline exports)
REM        - Output directory for results
REM        - Output filename (without extension)
REM        - Desired GSD (in meters)
REM
REM Output:
REM - A COG GeoTIFF mosaic of the RGB bands at the specified GSD.
REM ###############################################################################

REM Prompt for input directory
set /p input_directory="Enter the input directory containing the .tif files: "

REM Prompt for output directory
set /p output_directory="Enter the output directory: "

REM Prompt for output filename
set /p output_filename="Enter the output filename (without extension): "

REM Prompt for GSD
set /p gsd="Enter the GSD (Ground Sample Distance) in [m]: "

REM Check if output directory exists, create if not
if not exist "%output_directory%" (
    mkdir "%output_directory%"
    echo Created output directory: %output_directory%
) else (
    echo Output directory already exists: %output_directory%
)

REM Find all .tif files in input directory and save to input_files.txt
REM Handle UNC paths by using dir command with proper encoding
dir /s /b "%input_directory%\*.tif" > input_files_temp.txt

REM Process the file list to ensure proper encoding
REM Use a simple for loop to read and rewrite the file list
del input_files.txt 2>nul
for /f "usebackq delims=" %%i in ("input_files_temp.txt") do (
    echo %%i >> input_files.txt
)
del input_files_temp.txt

REM Create VRT file
echo [1/3] Building VRT mosaic...
set "vrt_file=%output_directory%\%output_filename%.vrt"
gdalbuildvrt --config NUM_THREADS ALL_CPUS -srcnodata "0 0 0" -vrtnodata "0 0 0" -input_file_list input_files.txt "%vrt_file%"

REM Create mosaic with gdalwarp
echo [2/3] Creating mosaic (warp)...
gdalwarp -tr %gsd% %gsd% -s_srs EPSG:2056 -t_srs EPSG:2056 -of GTiff -co COMPRESS=LZW -co TILED=YES -co BIGTIFF=YES -multi -wo NUM_THREADS=ALL_CPUS -r cubic -wm 512 -srcnodata 0,0,0 -dstalpha -nosrcalpha -srcband 1 -srcband 2 -srcband 3 "%vrt_file%" "%output_directory%\intermediate.tif"

REM Convert to COG with gdal_translate
echo [3/3] Creating Cloud Optimized GeoTIFF (COG)...
gdal_translate --config NUM_THREADS ALL_CPUS --config GDAL_DISABLE_READDIR_ON_OPEN EMPTY_DIR -of COG -co COMPRESS=JPEG -co QUALITY=75 -co BLOCKSIZE=256 -co BIGTIFF=YES "%output_directory%\intermediate.tif" "%output_directory%\%output_filename%.tif"

REM Cleanup (optional)
REM del input_files.txt
REM del "%output_directory%\intermediate.tif"

echo Processing complete! Output file located at: %output_directory%\%output_filename%.tif

REM Additional notes for special characters:
REM - Save this .bat file with UTF-8 encoding (not ANSI)
REM - When entering paths with umlauts, they should display correctly
REM - Network UNC paths with special characters are supported
REM - If you still see encoding issues, try mapping the network drive first

REM Pause to keep window open if double-clicked
pause
