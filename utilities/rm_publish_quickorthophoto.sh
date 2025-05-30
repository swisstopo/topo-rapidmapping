bash
#!/bin/bash

###############################################################################
# ADS100 Flightline Mosaic and COG Creator
#
# This script processes exports of ADS100 flightlines (GeoTIFF files) and
# generates a seamless mosaic, then converts it into a Cloud Optimized GeoTIFF
# (COG) containing the RGB bands. Based on https://github.com/geostandards-ch/cog-best-practices 
#
# Features:
# - Interactive prompts for input/output directories, filename, and GSD (Ground Sample Distance)
# - Automatic creation of output directory if it doesn't exist
# - Uses GDAL tools (gdalbuildvrt, gdalwarp, gdal_translate) for efficient processing
# - Handles large datasets with multi-threading and optimized settings
#
# Requirements:
# - Bash shell
# - GDAL installed and available in PATH (with support for COG and JPEG compression)
#
# Usage:
#   1. Place this script in a directory and make it executable:
#        chmod +x rm_publish_quickorthophoto.sh
#   2. Run the script:
#        ./rm_publish_quickorthophoto.sh
#   3. Follow the prompts to specify:
#        - Input directory containing .tif files (ADS100 flightline exports)
#        - Output directory for results
#        - Output filename (without extension)
#        - Desired GSD (in meters)
#
# Output:
# - A COG GeoTIFF mosaic of the RGB bands at the specified GSD.
#
###############################################################################

# Prompt for input directory
read -p "Enter the input directory containing the .tif files: " input_directory

# Prompt for output directory
read -p "Enter the output directory: " output_directory

# Prompt for output filename
read -p "Enter the output filename (without extension): " output_filename

# Prompt for GSD
read -p "Enter the GSD (Ground Sample Distance) in [m]: " gsd

# Check if output directory exists, create if not
if [ ! -d "$output_directory" ]; then
  mkdir -p "$output_directory"
  echo "Created output directory: $output_directory"
else
  echo "Output directory already exists: $output_directory"
fi

# GDAL options
gdalbuildvrt_options=(
  --config NUM_THREADS ALL_CPUS
  --config GDAL_DISABLE_READDIR_ON_OPEN EMPTY_DIR
)

gdal_translate_options=(
  --config NUM_THREADS ALL_CPUS
  --config GDAL_DISABLE_READDIR_ON_OPEN EMPTY_DIR
)

# Find all .tif files in input directory and save to input_files.txt
find "$input_directory" -type f -name "*.tif" > input_files.txt

# Create VRT file
echo "[1/3] Building VRT mosaic..."
vrt_file="$output_directory/$output_filename.vrt"
gdalbuildvrt "${gdalbuildvrt_options[@]}" -srcnodata "0 0 0" -vrtnodata "0 0 0" -input_file_list input_files.txt "$vrt_file"

# Create mosaic with gdalwarp
echo "[2/3] Creating mosaic (warp)..."
gdalwarp -tr "$gsd" "$gsd" -s_srs EPSG:2056 -t_srs EPSG:2056 -of GTiff -co COMPRESS=LZW -co TILED=YES -co BIGTIFF=YES -multi -wo NUM_THREADS=ALL_CPUS -r cubic -wm 512 -srcnodata 0,0,0 -dstalpha -nosrcalpha -srcband 1 -srcband 2 -srcband 3 "$vrt_file" "$output_directory/intermediate.tif"

# Convert to COG with gdal_translate
echo "[3/3] Creating Cloud Optimized GeoTIFF (COG)..."
gdal_translate -co NUM_THREADS=ALL_CPUS -of COG -co COMPRESS=JPEG -co QUALITY=75 -co BLOCKSIZE=256 -co BIGTIFF=YES "$output_directory/intermediate.tif" "$output_directory/$output_filename.tif"

# Cleanup (optional)
#rm input_files.txt
#rm "$output_directory/intermediate.tif"

echo "Processing complete! Output file located at: $output_directory/$output_filename.tif"
