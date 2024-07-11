# topo-rapidmapping

## Overview

Welcome to the official code repository for the swisstopo / FOEN  [www.rapidmapping.admin.ch](www.rapidmapping.admin.ch) initiative. This repository contains software and code developed by swisstopo, a Swiss government agency, dedicated to the timely acquisition and provision of geospatial data in the event of natural disasters. Our Rapidmapping service is a crucial tool in delivering aerial or satellite imagery to support disaster response and management.

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
