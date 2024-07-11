#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rm_publish_einzelbilder.py
Version: 
1.0 initial Version
1.1  fixed missing KML Header info
1.2  added check for missing gps tags
"""
version= 1.2
"""
Author: David Oesch
Description:
    This script processes images for the RM-PublishEinzelbilder project.
    It includes functions for resizing images, extracting EXIF data,
    and generating KML and TXT files. The intention was to run this script 
    as an intermediate solution on a laptop with QGIS and therefore OSGeo4W Shell,
    without requiring additional Python packages, so it can be run on a PC with a standard 
    QGIS installation.
    
"""

import os
import subprocess
import json
import re
print("Version: "+str(version))

#Fix RM-PublishEinzelbilder.py

max_width = 640
max_height = 480 
COLLECTION="https://data.geo.admin.ch/ch.swisstopo.rapidmapping/data/"

def prompt_choice():
    """Check for Valid Product input"""
    choice = input("Please enter your choice\n1) for Einzelbilder SENKRECHT\n2) for Einzelbilder SCHRAEG \n-> ")
    if choice == '1':
        return "Einzelbilder SENKRECHT", "https://map.geo.admin.ch/api/icons/sets/default/icons/008-circle-stroked@1x-255,0,0.png", 0.25, "SENKRECHT"
    elif choice == '2':
        return "Einzelbilder SCHRAEG", "https://map.geo.admin.ch/api/icons/sets/default/icons/100-camera@1x-127,0,255.png", 0.75, "SCHRAEGAUFNAHMEN"
    else:
        print("Invalid choice. Please enter 1 or 2.")
        return prompt_choice()

def check_directory_exists(directory):
    """Check if the given directory exists."""
    return os.path.isdir(directory)


def check_item_name(item_name):
    """Check if the item name matches the pattern YYYY-###-CAPITALLETTERS."""
    # Define the pattern to match
    pattern = r'^\d{4}-\d{3}-[A-Z]+$'
    
    # Check if the item name matches the pattern
    if re.fullmatch(pattern, item_name):
        return True
    else:
        return False

def dms_to_decimal(degrees, minutes, seconds, direction):
    """Convert DMS (Degrees, Minutes, Seconds) to decimal format."""
    decimal = degrees + minutes / 60 + seconds / 3600
    if direction in ['S', 'W']:
        decimal *= -1

    # Reduce the precision to 6 digits tos reduce kml Sapce
    decimal = round(decimal, 6)
    return decimal

def resize_images(input_dir, output_dir, max_width, max_height,image_count):
    """Resize images maintaining aspect ratio."""
    os.makedirs(output_dir, exist_ok=True)
    count=1
    for filename in os.listdir(input_dir):
        file_path = os.path.join(input_dir, filename)
        if os.path.isfile(file_path) and filename.lower().endswith(('.jpg', '.jpeg')):
            print("Step 1: generating thumbnail for image "+str(count)+" of "+str(image_count)+" "+filename  )
            thumbnail_path = os.path.join(output_dir, filename)
            
            
            # Bilddimensionen auslesen
            with open(os.devnull, 'w') as devnull:
                gdalinfo_output = subprocess.run(
                    ['gdalinfo', '-json', file_path],
                    capture_output=True, text=True
                )
            
            image_info = json.loads(gdalinfo_output.stdout)
            width = int(image_info['size'][0])
            height = int(image_info['size'][1])
            
            # Berechnung der neuen Dimensionen unter Beibehaltung des Seitenverhältnisses
            aspect_ratio = width / height
            if aspect_ratio > 1:
                new_width = min(max_width, width)
                new_height = int(new_width / aspect_ratio)
            else:
                new_height = min(max_height, height)
                new_width = int(new_height * aspect_ratio)

            new_width = min(new_width, max_width)
            new_height = min(new_height, max_height)

            # Unterdrücken der Ausgaben und Setzen der Umgebungsvariable GDAL_PAM_ENABLED=NO
            with open(os.devnull, 'w') as devnull:
                subprocess.run(
                    ['gdal_translate', '-of', 'JPEG', '-outsize', str(new_width), str(new_height), file_path, thumbnail_path],
                    stdout=devnull,
                    stderr=devnull,
                    env={**os.environ, 'GDAL_PAM_ENABLED': 'NO'}
                )
            count=count+1

def extract_exif(file_path):
    """Extract EXIF data from images."""
    with open(os.devnull, 'w') as devnull:
        gdalinfo_output = subprocess.run(['gdalinfo', '-json', file_path], capture_output=True, text=True)
    exif_data = json.loads(gdalinfo_output.stdout)
    
    lat, lon = None, None
    timestamp = None
    if 'metadata' in exif_data and '' in exif_data['metadata']:
        exif = exif_data['metadata']['']

        if 'EXIF_GPSLatitude' in exif and 'EXIF_GPSLongitude' in exif:
            lat_parts = exif['EXIF_GPSLatitude']
            lon_parts = exif['EXIF_GPSLongitude']
            lat_ref = exif.get('EXIF_GPSLatitudeRef', 'N')
            lon_ref = exif.get('EXIF_GPSLongitudeRef', 'E')
            
            # Klammern und Leerzeichen entfernen und in Float umwandeln
            lat_degrees, lat_minutes, lat_seconds = [float(x.replace(')', '')) for x in lat_parts.strip('()').split(') (')]
            lon_degrees, lon_minutes, lon_seconds = [float(x.replace(')', '')) for x in lon_parts.strip('()').split(') (')]
            
            lat = dms_to_decimal(lat_degrees, lat_minutes, lat_seconds, lat_ref)
            lon = dms_to_decimal(lon_degrees, lon_minutes, lon_seconds, lon_ref)
        
        if 'EXIF_DateTimeOriginal' in exif:
            timestamp = exif['EXIF_DateTimeOriginal']

    return lat, lon, timestamp

def generate_kml(input_dir, kml_file,image_count):

    with open(kml_file, 'w') as kml:
        
        
        kml.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        kml.write('<kml\n')
        kml.write('xmlns="http://www.opengis.net/kml/2.2"\n')
        kml.write('xmlns:gx="http://www.google.com/kml/ext/2.2"\n')
        kml.write('xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n')
        kml.write('xsi:schemaLocation="http://www.opengis.net/kml/2.2 https://developers.google.com/kml/schema/kml22gx.xsd">\n')
        kml.write(f'<Document><name>{ITEM_NAME}-{PRODUCT_TYPE}</name>\n')
        kml.write('<Style id="image_style">\n')
        kml.write('<IconStyle>\n')
        kml.write(f'<scale>{ICON_SCALE}</scale>\n')
        kml.write(f'<Icon><href>{ICON_URL}</href><gx:w>48</gx:w><gx:h>48</gx:h></Icon>\n')  # Halbe Größe
        kml.write('</IconStyle>\n')
        kml.write('<LabelStyle>\n')
        kml.write('<color>ff0000ff</color><scale>1.5</scale>\n')  # Halbe Skalierung
        kml.write('</LabelStyle>\n')
        kml.write('</Style>\n')
        
        count=1
        for filename in os.listdir(input_dir):
            file_path = os.path.join(input_dir, filename)
            
            if os.path.isfile(file_path) and filename.lower().endswith(('.jpg', '.jpeg')):
                print("Step 2: generating kmlinfo for image "+str(count)+" of "+str(image_count)+" "+filename  )
                lat, lon, timestamp = extract_exif(file_path)
                
                if lat is not None and lon is not None:
                    kml.write('<Placemark>\n')
                    kml.write('<name></name>\n')
                    kml.write(f'<description><![CDATA[<a href="{BASE_URL}{filename}">Download-View Fullresolution</a> {timestamp}<br>')
                    kml.write(f'<img style="max-width:400px;" src="{BASE_URL}thumbs/{filename}">]]></description>\n')
                    kml.write(f'<styleUrl>#image_style</styleUrl>\n')
                    kml.write('<Point>\n')
                    kml.write(f'<coordinates>{lon},{lat},0</coordinates>\n')
                    kml.write('</Point>\n')
                    kml.write('</Placemark>\n')
                else: # In case no gps tags are available
                    print(f'!!! Error: No GPS tag for image {count} of {image_count} {filename} !!!')
                count=count+1  

        kml.write('</Document>\n')
        kml.write('</kml>\n')

def generate_txt(input_dir, txt_file):

    with open(txt_file, 'w') as txt:
               
        count=1
        for filename in os.listdir(input_dir):
            file_path = os.path.join(input_dir, filename)
            
            if os.path.isfile(file_path) and filename.lower().endswith(('.jpg', '.jpeg')):
              
                txt.write(f'{BASE_URL}{filename}\n')
                
                count=count+1    




if __name__ == "__main__":
    
    # Initialize input_directory
    input_directory = ""

   # Keep prompting the user for the input directory until a valid directory is entered
    while not check_directory_exists(input_directory):
        print("\nPlease enter the INPUT directory.")
        print("Example: 'C:\\oed\\temp\\_rm\\inscript'")
        input_directory = input("-> ")
    
        # Check if the directory exists
        if check_directory_exists(input_directory):
            print(f"The directory '{input_directory}' exists.")
        else:
            print(f"The directory '{input_directory}' does not exist. Please enter a valid directory.")

    # Initialize export_directory
    export_directory = ""

    # Keep prompting the user for the KML directory until a valid directory is entered
    while not check_directory_exists(export_directory):
        print("\nPlease enter EXPORT directory")
        print("Example: 'C:\\oed\\temp\\_rm\\inscript'")
        export_directory = input("-> ")
    
    
        # Check if the directory exists
        if check_directory_exists(export_directory):
            print(f"The directory '{export_directory}' exists.")
        else:
            print(f"The directory '{export_directory}' does not exist. Please enter a valid directory.")


     # Prompt the user The Product type
    option, ICON_URL, ICON_SCALE, PRODUCT_TYPE = prompt_choice()

    # Prompt the user for the item NAME
    # Initialize item_name
    ITEM_NAME = ""

    # Keep prompting the user for the item NAME until a valid format is entered
    while not check_item_name(ITEM_NAME):
        print("\nPlease enter the item NAME (format YYYY-###-CAPITALLETTERS)")
        print("Example: 2024-001-WALLIS")
        ITEM_NAME= input("-> ")
        
        
        # Check the structure of the input
        if check_item_name(ITEM_NAME):
            print(f"The item NAME '{ITEM_NAME}' is valid.")
        else:
            print(f"The item NAME '{ITEM_NAME}' is invalid. Please enter a valid item NAME in the format YYYY-###-CAPITALLETTERS. e.g. 2024-001-WALLIS")

        BASE_URL = COLLECTION+ITEM_NAME+"/"

    # Print the collected information
    print("\n")
    print("************************************\n")
    print(f"INPUT Directory: {input_directory}")
    print(f"EXPORT Directory: {export_directory}")
    print(f"Selected OPTION: {option}")
    print(f"ITEM Name: {ITEM_NAME}\n")
    print("************************************\n")
    print("\n")

    #Defeine variables based on input
    output_directory = os.path.join(input_directory, 'thumbs')
    kml_filepath = os.path.join(export_directory, ITEM_NAME+"-"+PRODUCT_TYPE+'.kml')
    txt_filepath = os.path.join(export_directory, ITEM_NAME+"-"+PRODUCT_TYPE+'.txt')

    #count the fiels to estimate a job run time
    image_count = sum(1 for f in os.listdir(input_directory) if f.lower().endswith(('.jpg', '.jpeg')))

    #RUN the different steps

    resize_images(input_directory, output_directory, max_width, max_height,image_count)
   
    generate_kml(input_directory,  kml_filepath,image_count)

    generate_txt(input_directory, txt_filepath)

    
    print(f"KML-Datei erstellt: {kml_filepath}")
    print(f"TXT-Datei erstellt: {txt_filepath}")
    print("Nächste Schritte:")
    print("    - meta.txt erstellen und nach bgdiscratch ")
    print("    - KML in hostpoint ablegen")
    print(f"    - thumbs und originaldaten aus dem {input_directory} und {txt_filepath} nach bgdiscratch kopieren")
    print("    - beten")

    # Add a prompt to ask the user if they want to quit
    user_input = input("Drücke 'q' um das Programm zu beenden: ").lower()
    if user_input == 'q':
        print("Exiting the program.")
        exit()
    else:
        print("Exiting the program..anyway.")
