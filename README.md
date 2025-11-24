# topo-rapidmapping

## Overview

Welcome to the official code repository for the swisstopo / FOEN  [www.rapidmapping.admin.ch](https://www.rapidmapping.admin.ch) initiative. This repository contains software and code developed by swisstopo, a Swiss government agency, dedicated to the timely acquisition and provision of geospatial data in the event of natural disasters. Our Rapidmapping service is a crucial tool in delivering aerial or satellite imagery to support disaster response and management.

## Table of Contents

- [Introduction](#introduction)
- [Features](#features)
- [Usage](#usage)
- [Utilities](#utilities)
- [Contributing](#contributing)
- [License](#license)
- [Contact](#contact)

## Introduction

Rapidmapping is a federal service aimed at swiftly gathering and distributing geospatial data, such as aerial or satellite images, during natural events. This repository encompasses various scripts, utilities, and resources that facilitate the creation and dissemination of these rapid mapping products.

## Features

- **Data Processing Pipelines**: Scripts to handle image preprocessing, analysis, and conversion.
- **Data Publication Pipelines**: Tools to ensure quick publication of mapping products.

## Usage

Detailed usage instructions for each tool and script can be found in their respective directories. 

## Utilities

We provide several utility scripts to assist with various tasks in the [utilities](utilities/):

###  rm_publish_einzelbilder.py
#### Description

This script processes images for the RM-PublishEinzelbilder project. It includes functions for resizing images, extracting EXIF data, and generating KML and TXT files. The intention was to run this script as an intermediate solution on a laptop with QGIS and therefore OSGeo4W Shell, without requiring additional Python packages, so it can be run on a PC with a standard QGIS installation.

#####  Features

- **Image Resizing**: Efficiently generates thumbnails images .
- **EXIF Data Extraction**: Check and extract metadata from images for further processing.
- **KML File Generation**: Create KML files for easy visualization of geospatial data.
- **TXT File Generation**: Produce TXT files for downloadlinks.

##### Usage

To use this script, run the following command in your OSGeo4W Shell with a standard QGIS installation:

```sh
python rm-publish_einzelbilder.py
```
### rm_publish_quickorthophoto.sh/bat
#### Description

A Bash/DOS script to automate the publication of quick orthophoto products. Exports of ADS100 flightlines (GeoTIFF files) and generates a seamless mosaic, then converts it into a Cloud Optimized GeoTIFF(COG) containing the RGB bands. Based on https://github.com/geostandards-ch/cog-best-practices 

#### Features

- **Interactive prompts**  for input/output directories, filename, and GSD (Ground Sample Distance)
- **Uses GDAL tools**  (gdalbuildvrt, gdalwarp, gdal_translate) for efficient processing
- **Handles large datasets**  with multi-threading and optimized settings


#### Usage

Run the script in your shell (Linux or OSGeo4W Shell) or Windows/DOS Prompt:

Linux
```sh
bash rm_publish_quickorthophoto.sh /path/to/input_folder /path/to/output_folder
```
Windows/DOS
```sh
rm_publish_quickorthophoto.bat /path/to/input_folder /path/to/output_folder
```

- Replace `/path/to/input_folder` with your orthophoto source directory.
- Replace `/path/to/output_folder` with your desired destination.

###  rm_remove_leeren_TIFS.py
#### Description

This script removes the empty TIFs (TIFs with only "no data") from a folder and the tfw which are related.The intention was to run this script as an intermediate solution on a laptop with QGIS and therefore OSGeo4W Shell, without requiring additional Python packages, so it can be run on a PC with a standard QGIS installation.

#####  Features

- **Size check**: Check siz from image
- **Search data name**: Search for a tfw with the same name as a TIF.
- **Delete files**: Delet TIFs and TWs.
- **TXT File Generation**: Write log file with deletes Filenames.

##### Usage

To use this script, run the following command in your OSGeo4W Shell with a standard QGIS installation:

```sh
python rm_remove_leeren_TIFS.py
```
### rm_process_pug_images.py

#### Description
This script processes PUG images [example](https://data.geo.admin.ch/ch.swisstopo.rapidmapping/data/2024-008-TICINO/i240630_121859-0.jpg) by extracting EXIF data, applying mask, and creating a KML file with image previews and location data.

##### Features
- Extracts text from predefined bounding boxes using EasyOCR.
- Applies mask to images and saves the masked images.
- Extracts and modifies EXIF data (date, time, GPS coordinates).
- Generates a KML file with image previews and coordinates.
- Logs errors for images that cannot be georeferenced.

##### Usage
###### Python
This scripts needs some additional Python modules. Tested with Python 3.10.12 and 3.11.9.
   ```sh
   pip install -r requirements.txt
   python rm_process_pug_images.py
   ```
1. Run the script.
2. Enter the input directory path containing PNG images.
3. Enter the output directory path where processed images and KML file will be saved.
4. If `pgu_mask.png` is not found in the current directory, provide the path to it.
5. The script will process each image, apply masks, extract EXIF data, and create a KML file with image previews and coordinates.
6. An error file (`not_processed.txt`) will be generated for files that could not be georeferenced.

###### Executable binaries / EXE
Download from [v0.0.1-alpha](https://github.com/swisstopo/topo-rapidmapping/releases/tag/v0.0.1-alpha)
- `pgu_mask.png`
- folder `models` including content
- `rm_process_pug_images.exe`

1. Run `rm_process_pug_images.exe`

### util_publish_stac_fsdi.py

**Purpose:** Simplified STAC publisher for publishing geodata to FSDI (Federal Spatial Data Infrastructure) without a configuration file. All settings are passed as parameters.

**Description:**
This [script](https://github.com/swisstopo/topo-rapidmapping/blob/main/utilities/util_publish_stac_fsdi.py) publishes geospatial assets (GeoTIFFs, GeoJSON, CSV, Parquet, JPEG) to the FSDI STAC catalog. It automatically creates STAC Items and Assets, generates metadata from the files, and uploads the data via multipart upload.

**Features:**

- Automatic creation of STAC Items from GeoTIFF metadata (bounding box, timestamp)
- Supports various file types: GeoTIFF, GeoJSON, CSV, Parquet, JPEG
- Coordinate transformation from LV95 to WGS84
- Automatic thumbnail linking and map visualization
- Integrated multipart upload for large files
- CLI interface with environment variable support
- Support for "current" use cases (current data)

**Usage:**

```sh
# Basic usage
python util_publish_stac_fsdi.py -u myuser -p mypass -a file.tif -i 2024-01-15T120000 \
  -c ch.swisstopo.product -g geocat-id -H data.geo.admin.ch

# With custom asset title
python util_publish_stac_fsdi.py -u myuser -p mypass -a file.tif -i 2024-01-15T120000 \
  -c ch.swisstopo.product -g geocat-id -H data.int.bgdi.ch -t "My Custom Title"

# With environment variables for credentials
export STAC_USERNAME=myuser
export STAC_PASSWORD=mypass
python util_publish_stac_fsdi.py -a file.tif -i 2024-01-15T120000 \
  -c ch.swisstopo.product -g geocat-id -H data.geo.admin.ch
```


***

### main_multipart_upload_via_api.py

**Purpose:** Multipart upload of large asset files to the STAC API with MD5 checksums and retry logic.

**Description:**
This [script](https://github.com/swisstopo/topo-rapidmapping/blob/main/utilities/main_multipart_upload_via_api.py) enables uploading large files to the STAC API via multipart upload. It splits large files into smaller parts, generates MD5 checksums for each part, and uploads them in parallel. The script is an adaptation of the original [bgdi-script](https://github.com/geoadmin/bgdi-scripts/blob/master/system-utilities/sys-data/py-scripts/multipart_upload_via_api.py) from geoadmin.

**Features:**

- Multipart upload for large files (default: 250 MB per part)
- Automatic MD5 checksum generation (Base64-encoded)
- SHA-256 multihash calculation for file integrity
- Retry logic with exponential backoff
- Support for different environments (localhost, dev, int, prod)
- Graceful abort on errors or keyboard interrupt
- Force option to abort running uploads
- Verbose logging for debugging


**Usage:**

```sh
# Basic usage (CLI)
python main_multipart_upload_via_api.py int ch.swisstopo.collection item_name \
  asset_name /path/to/file.tif --username myuser --password mypass

# With custom part size (500 MB)
python main_multipart_upload_via_api.py prod ch.swisstopo.collection item_name \
  asset_name /path/to/large_file.tif --part-size 500 --username myuser --password mypass

# With verbose output and force
python main_multipart_upload_via_api.py int ch.swisstopo.collection item_name \
  asset_name /path/to/file.tif --username myuser --password mypass -v --force

# Programmatic usage (within Python)
from main_multipart_upload_via_api import multipart_upload

success = multipart_upload(
    env='int',
    collection='ch.swisstopo.myproduct',
    item='2024-01-15T120000',
    asset='data.tif',
    filepath='/path/to/data.tif',
    username='myuser',
    password='mypass',
    force=True,
    verbose=False
)
```

**Dependencies:**

- requests
- multihash
- urllib3

## Contributing

Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

If you have a suggestion that would make this better, please fork the repo and create a pull request. You can also simply open an issue with the tag "enhancement".
Don't forget to give the project a star! Thanks again!

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

Distributed under the BSD-3-Clause License. See `LICENSE.txt` for more information.

## Contact

info[ a t]rapidmapping.admin.ch

[https://www.rapidmapping.admin.ch](https://www.rapidmapping.admin.ch)
