"""
Script to process PUG images, extract EXIF data, apply masks, and create a KML file with image previews and location data.

Dependencies:
- cv2 (OpenCV)
- easyocr
- numpy
- PIL (Pillow)
- datetime
- exif
- glob
- re
- pykml
- lxml
- base64

Usage:
1. Run the script.
2. Enter the input directory path containing PNG images.
3. Enter the output directory path where processed images and KML file will be saved.
4. If 'pgu_mask.png' is not found in the current directory, provide the path to it.
5. The script will process each image, apply masks, extract EXIF data, and create a KML file with image previews and coordinates. 
6. An error file will be generated for files which could not be georeferenced

"""
import os
import cv2
import easyocr
from PIL import Image
from datetime import datetime
from exif import Image as ExifImage
from exif import DATETIME_STR_FORMAT
import glob
import re
from pykml.factory import KML_ElementMaker as KML
from lxml import etree
import base64
from colorama import init, Fore, Style



def print_lowest_confidence_score(lat_dd_text, lat_mm_text, lat_ss_text, lat_dir_text, 
                                  lon_dd_text, lon_mm_text, lon_ss_text, lon_dir_text):
    """
    Print the lowest confidence score among the extracted texts and indicate which text it corresponds to.

    Args:
    - lat_dd_text (list): Extracted text and score for latitude degrees.
    - lat_mm_text (list): Extracted text and score for latitude minutes.
    - lat_ss_text (list): Extracted text and score for latitude seconds.
    - lat_dir_text (list): Extracted text and score for latitude direction.
    - lon_dd_text (list): Extracted text and score for longitude degrees.
    - lon_mm_text (list): Extracted text and score for longitude minutes.
    - lon_ss_text (list): Extracted text and score for longitude seconds.
    - lon_dir_text (list): Extracted text and score for longitude direction.
    """
    # Collect all the extracted texts and their corresponding labels
    extracted_texts = {
        'lat_dd_text': lat_dd_text,
        'lat_mm_text': lat_mm_text,
        'lat_ss_text': lat_ss_text,
        'lat_dir_text': lat_dir_text,
        'lon_dd_text': lon_dd_text,
        'lon_mm_text': lon_mm_text,
        'lon_ss_text': lon_ss_text,
        'lon_dir_text': lon_dir_text
    }
    
    # Find the lowest confidence score among the extracted texts
    lowest_score = float('inf')
    lowest_label = None
    for label, text_data in extracted_texts.items():
        if text_data:
            score = text_data[0][2]
            if score < lowest_score:
                lowest_score = score
                lowest_label = label
    
    # Format the score to two decimal places
    score_str = f"{lowest_score:.2f}"
    
    # Determine the color based on the score
    if lowest_score >= 0.90:
        color_code = Fore.GREEN  # Green
    elif 0.39 < lowest_score < 0.90:
        color_code = Fore.YELLOW  # Yellow
    else:
        color_code = Fore.RED  # Red
    
    # Print the lowest score and the corresponding label in the determined color
    print(f"Lowest Confidence Score: {color_code}{score_str}{Style.RESET_ALL} from {lowest_label}")
    

def check_not_processed_file():
    """
    Check if the 'not_processed.txt' file exists, count the number of lines,
    and print a warning message if there are any lines.
    """
    file_path = error_file_path
    if os.path.exists(file_path):
        with open(file_path, 'r') as file:
            lines = file.readlines()
            if lines:
                print(f"- {Fore.RED}{len(lines)} of images could not be georeferenced, details in not_processed.txt{Style.RESET_ALL}")


def image_to_base64(image_path):
    """
    Convert an image to base64 format.

    Args:
    - image_path (str): Path to the image file.

    Returns:
    - str: Base64 encoded image as a string.
    """
    with open(image_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')

def extract_exif_and_create_kml(output_dir, kml_file_path):
    """
    Extract EXIF data from images in the specified directory and create a KML file with image previews and coordinates.

    Args:
    - output_dir (str): Path to the directory containing processed images.
    - kml_file_path (str): Path to save the generated KML file.
    """
    kml_doc = KML.kml(
        KML.Document(
            KML.name("PUG-PREVIEW"),  # Set the document title here
            KML.Style(
                KML.IconStyle(
                    KML.scale(0.75),
                    KML.Icon(
                        KML.href("https://map.geo.admin.ch/api/icons/sets/default/icons/100-camera@1x-0,0,225.png"),
                        KML.gx_w("48"),
                        KML.gx_h("48")
                    )
                ),
                KML.LabelStyle(
                    KML.color("ff0000ff"),
                    KML.scale("1.5")
                ),
                id="image_style"
            )
        )
    )

    for filename in os.listdir(output_dir):
        if filename.lower().endswith((".jpg", ".jpeg", ".png")):
            image_path = os.path.join(output_dir, filename)

            try:
                with open(image_path, 'rb') as image_file:
                    img = ExifImage(image_file)

                    if img.has_exif and 'gps_latitude' in dir(img) and 'gps_longitude' in dir(img):
                        lat = getattr(img, 'gps_latitude')
                        lon = getattr(img, 'gps_longitude')
                        lat_ref = getattr(img, 'gps_latitude_ref')
                        lon_ref = getattr(img, 'gps_longitude_ref')

                        lat_deg = lat[0] + lat[1] / 60 + lat[2] / 3600
                        lon_deg = lon[0] + lon[1] / 60 + lon[2] / 3600

                        if lat_ref == 'S':
                            lat_deg = -lat_deg
                        if lon_ref == 'W':
                            lon_deg = -lon_deg

                        # Convert image to Base64 data URL
                        image_base64 = image_to_base64(image_path)

                        # Get image creation time (adjust according to your EXIF library)
                        exif_time = img.datetime_original
            
                        description = f"""
                        File: {filename} Time: {exif_time}<br />
                        <img src="data:image/jpeg;base64,{image_base64}" width="400px" />
                        """

                        placemark = KML.Placemark(
                            KML.name(""),  # Empty name for icon style
                            KML.description(description),
                            KML.styleUrl("#image_style"),
                            KML.Point(
                                KML.coordinates(f"{lon_deg},{lat_deg}")
                            )
                        )
                        kml_doc.Document.append(placemark)

            except Exception as e:
                print(f"Error processing {image_path}: {str(e)}")

    kml_tree = etree.ElementTree(kml_doc)
    kml_tree.write(kml_file_path, pretty_print=True, xml_declaration=True, encoding="UTF-8")
    print(f"- KML file created at {kml_file_path}")



def apply_and_save_mask(image_path):
    """
    Apply a mask to an image and save the masked image.

    Args:
    - image_path (str): Path to the image file.
    """
    # Read the input image
    img = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"Error loading the image {image_path}. Please check the file path.")
    
    # Read the mask image with alpha channel 
    mask = cv2.imread(mask_path, cv2.IMREAD_UNCHANGED)
    if mask is None:
        raise ValueError(f"Error loading the mask image {mask_path}. Please check the file path.")
    
    # Ensure the mask size matches the image size
    if mask.shape[:2] != img.shape[:2]:
        raise ValueError(f"The mask size {mask.shape[:2]} does not match the image size {img.shape[:2]}.")
    
    # Split the mask into its color and alpha channels
    b, g, r, alpha = cv2.split(mask)

    # Convert the original image to BGRA if it's not already
    if img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)

    # Create an inverse alpha mask
    alpha_inv = cv2.bitwise_not(alpha)

    # Extract the original image's alpha channel if it exists, or create one if it doesn't
    if img.shape[2] == 4:
        b_img, g_img, r_img, alpha_img = cv2.split(img)
    else:
        b_img, g_img, r_img = cv2.split(img)
        # Create an alpha channel filled with 255 using OpenCV functions
        alpha_img = cv2.merge((b_img, g_img, r_img, b_img.copy()))
        alpha_img[:, :, 3] = 255

    # Blend the mask and the original image using the alpha channel
    for c in range(0, 3):
        img[:, :, c] = (alpha_inv / 255.0 * img[:, :, c] + (alpha / 255.0 * mask[:, :, c]))

    # Save the masked image
    masked_image_path = image_path
    cv2.imwrite(masked_image_path, img)
    
    #print(f"Masked image saved to {masked_image_path}")

def add_exif_information(image_path, date_text, time_text,  lat, lon):
    """
    Add or modify EXIF information (date, time, GPS coordinates) in an image file.

    Args:
    - image_path (str): Path to the image file.
    - date_text (str): Date in text format (YYYY MM DD).
    - time_text (str): Time in text format (HH:MM:SS).
    - lat (tuple): Latitude tuple (degrees, minutes, seconds, direction).
    - lon (tuple): Longitude tuple (degrees, minutes, seconds, direction).

    Returns:
    - bool: True if EXIF information is successfully added, False otherwise.
    """
    try:
        with open(image_path, 'rb') as image_file:
            img = ExifImage(image_file)
        
        exif_date_time = datetime.strptime(f"{date_text} {time_text}", "%Y %m %d %H:%M:%S")
        #print(exif_date_time)
        img.datetime_original = exif_date_time.strftime(DATETIME_STR_FORMAT)
        img.datetime_digitized = exif_date_time.strftime(DATETIME_STR_FORMAT)

        if lat and lon:
            img.gps_latitude = (float(lat[0]), float(lat[1]), float(lat[2]))
            img.gps_latitude_ref = "N" if lat[3] == 'N' else 'S'
            img.gps_longitude = (float(lon[0]), float(lon[1]), float(lon[2]))
            img.gps_longitude_ref = "E" if lon[3] == 'E' else 'W'
        
        with open(image_path, 'wb') as new_image_file:
            new_image_file.write(img.get_file())
        
        return True
    
    except Exception as e:
        return f"Error: {str(e)}"

def crop_image(image, bbox):
    """
    Crop an image based on given bounding box coordinates.

    Args:
    - image (numpy.ndarray): Input image as a NumPy array.
    - bbox (tuple): Bounding box coordinates (x1, y1, x2, y2).

    Returns:
    - numpy.ndarray: Cropped image as a NumPy array.
    """
    x1, y1, x2, y2 = bbox
    return image[y1:y2, x1:x2]

def print_extracted_text(label, extracted_text):
    """
    Print extracted text and confidence score.

    Args:
    - label (str): Label for the extracted text.
    - extracted_text (list): List of tuples containing extracted text and confidence score.
    """
    if extracted_text:
        text, score = extracted_text[0][1], extracted_text[0][2]
        score_str = str(score)
        decimal_index = score_str.find('.')
        if decimal_index != -1:
            formatted_score = score_str[:decimal_index + 3]
        else:
            formatted_score = score_str
        print(f"{label}: {text} with score: {formatted_score}")

def process_image(image_path, reader):
    """
    Processes an image to extract latitude and longitude coordinates.

    Parameters:
    -----------
    image_path : str
        The file path to the image to be processed.
    reader : easyocr.Reader
        An EasyOCR reader instance used for text recognition.

    Raises:
    -------
    ValueError
        If the image cannot be loaded or if its dimensions are not 1920x1080 pixels.

    Description:
    ------------
    This function reads an image from the specified path, checks its dimensions,
    and extracts text from predefined bounding boxes corresponding to latitude
    and longitude coordinates. The extracted text is then printed and the image
    is saved with EXIF metadata.

    Steps:
    ------
    1. Load the image.
    2. Verify the image dimensions.
    3. Define bounding boxes for latitude and longitude regions.
    4. Crop the image to these regions.
    5. Use EasyOCR to extract text from the cropped regions.
    6. Print the extracted text in the desired format.
    7. Save with mask the processed image with EXIF metadata.
    """
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Error loading the image {image_path}. Please check the file path.")
    
    height, width, _ = img.shape
    if width != 1920 or height != 1080:
        print(f"The image {image_path} has dimensions {width}x{height}.")
        print("Extraction works only for 1920x1080 imagery.")
    else:
        lat_dd_bbox = (1670, 988, 1725, 1017)
        lat_mm_bbox = (1744, 988, 1799, 1017)
        lat_ss_bbox = (1820, 988, 1867, 1017)
        lat_dir_bbox = (1866, 988, 1891, 1017)
        lon_dd_bbox = (1670, 1018, 1730, 1060)
        lon_mm_bbox = (1744, 1018, 1799, 1049)
        lon_ss_bbox = (1820, 1018, 1867, 1049)
        lon_dir_bbox = (1866, 1018, 1891, 1049)

        lat_dd_img = crop_image(img, lat_dd_bbox)
        lat_mm_img = crop_image(img, lat_mm_bbox)
        lat_ss_img = crop_image(img, lat_ss_bbox)
        lat_dir_img = crop_image(img, lat_dir_bbox)
        lon_dd_img = crop_image(img, lon_dd_bbox)
        lon_mm_img = crop_image(img, lon_mm_bbox)
        lon_ss_img = crop_image(img, lon_ss_bbox)
        lon_dir_img = crop_image(img, lon_dir_bbox)

        #Fine Tune Here with the parameters based on https://www.jaided.ai/easyocr/documentation/     
        lat_dd_text = reader.readtext(lat_dd_img, allowlist='0123456789', mag_ratio=3,text_threshold=0.6)
        lat_mm_text = reader.readtext(lat_mm_img, allowlist='0123456789', mag_ratio=3,text_threshold=0.6)
        lat_ss_text = reader.readtext(lat_ss_img, allowlist='0123456789', mag_ratio=3,text_threshold=0.6)
        lat_dir_text = reader.readtext(lat_dir_img, allowlist='NS', mag_ratio=3,text_threshold=0.6)
        lon_dd_text = reader.readtext(lon_dd_img, allowlist='0123456789', mag_ratio=2)
        lon_mm_text = reader.readtext(lon_mm_img, allowlist='0123456789', mag_ratio=3,text_threshold=0.6)
        lon_ss_text = reader.readtext(lon_ss_img, allowlist='0123456789', mag_ratio=3,text_threshold=0.6)
        lon_dir_text = reader.readtext(lon_dir_img, allowlist='EW', mag_ratio=3,text_threshold=0.6)

        # print_extracted_text("Latitude DD", lat_dd_text)
        # print_extracted_text("Latitude MM", lat_mm_text)
        # print_extracted_text("Latitude SS", lat_ss_text)
        # print_extracted_text("Latitude Direction", lat_dir_text)
        # print_extracted_text("Longitude DD", lon_dd_text)
        # print_extracted_text("Longitude MM", lon_mm_text)
        # print_extracted_text("Longitude SS", lon_ss_text)
        # print_extracted_text("Longitude Direction", lon_dir_text)

        # Print the extracted text in the desired format
        
        #print(image_path)
        if all([lat_dd_text, lat_mm_text, lat_ss_text, lat_dir_text]):
            print(f"{lat_dd_text[0][1]} : {lat_mm_text[0][1]} : {lat_ss_text[0][1]}{lat_dir_text[0][1]}")
        if all([lon_dd_text, lon_mm_text, lon_ss_text, lon_dir_text]):
            print(f"{lon_dd_text[0][1]} : {lon_mm_text[0][1]} : {lon_ss_text[0][1]}{lon_dir_text[0][1]}")
        print_lowest_confidence_score(lat_dd_text, lat_mm_text, lat_ss_text, lat_dir_text, 
                                  lon_dd_text, lon_mm_text, lon_ss_text, lon_dir_text)
        print("")
        print("*****************************************")

        # Check if any text extraction results are empty
        if not all([lat_dd_text, lat_mm_text, lat_ss_text, lat_dir_text, lon_dd_text, lon_mm_text, lon_ss_text, lon_dir_text]):
            missing_parts = []
            if not lat_dd_text:
                missing_parts.append("lat_dd_text")
            if not lat_mm_text:
                missing_parts.append("lat_mm_text")
            if not lat_ss_text:
                missing_parts.append("lat_ss_text")
            if not lat_dir_text:
                missing_parts.append("lat_dir_text")
            if not lon_dd_text:
                missing_parts.append("lon_dd_text")
            if not lon_mm_text:
                missing_parts.append("lon_mm_text")
            if not lon_ss_text:
                missing_parts.append("lon_ss_text")
            if not lon_dir_text:
                missing_parts.append("lon_dir_text")

            result = f"Missing parts: {', '.join(missing_parts)}"
            print(f"{Fore.RED} FAILED ON: {image_path} - {result}{Style.RESET_ALL}\n")
            with open(error_file_path, "a") as file:
                file.write(f"{image_path} - {result}\n")


        filename = os.path.basename(image_path)
        match = re.match(r'i(\d{6})_(\d{6})-\d+\.png', filename)
        if match:
            date_part, time_part = match.groups()
            date_text = f"20{date_part[:2]} {date_part[2:4]} {date_part[4:6]}"
            time_text_value = f"{time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}"


            # print(f"YEAR: 20{date_part[:2]}")
            # print(f"MONTH: {date_part[2:4]}")
            # print(f"DAY: {date_part[4:6]}")
            # print(f"Time: {time_text_value}")


            # Open ans export to jpeg
            jpeg_path = os.path.join(output_dir, filename.replace(".png", ".jpg"))
            im = Image.open(image_path)
            im.save(jpeg_path) 
            
            #Apply mask
            apply_and_save_mask(jpeg_path)
            
            lat = (lat_dd_text[0][1], lat_mm_text[0][1], lat_ss_text[0][1], lat_dir_text[0][1]) if all([lat_dd_text, lat_mm_text, lat_ss_text, lat_dir_text]) else None
            lon = (lon_dd_text[0][1], lon_mm_text[0][1], lon_ss_text[0][1], lon_dir_text[0][1]) if all([lon_dd_text, lon_mm_text, lon_ss_text, lon_dir_text]) else None
            result = add_exif_information(jpeg_path, date_text, time_text_value,  lat, lon)

            if result is not True:
                print(f"{Fore.RED} FAILED ON: {image_path} - {result}{Style.RESET_ALL}\n")
                with open(error_file_path, "a") as file:
                    file.write(f"{image_path} - Missing parts: {result}\n")
        else:
            print(f"Filename {filename} does not match expected format.")

def main():
    # Initialize colorama for cross-platform compatibility for color
    init()
    reader = easyocr.Reader(['en'], gpu=False)
    global output_dir  # Declare the global variable
    global mask_path  # Declare the global variable
    global error_file_path  # Declare the global variable
    
    error_file_path="not_processed.txt"

    if os.path.exists(error_file_path):
        os.remove(error_file_path)

    print("")
    print("Enter the input directory path:")
    print("Example: /path/to/your/images (Linux/Mac) or C:\\Path\\To\\Your\\Images (Windows)")
    image_dir = input("> ")

    print("")
    print("Enter the output directory path:")
    print("Example: /path/to/your/output (Linux/Mac) or C:\\Path\\To\\Your\\Output (Windows)")
    output_dir = input("> ")

    # Check if the mask file exists in the current directory
    mask_path = "pgu_mask.png"
    if not os.path.exists(mask_path):
        print("")
        print(f"{Fore.RED}pgu_mask.png not found in the current directory.{Style.RESET_ALL}")
        print("Enter the path to the mask file:")
        mask_path = input("> ")

        # Verify the entered mask file path
        if not os.path.exists(mask_path):
            raise ValueError(f"Mask file not found at the specified path: {mask_path}")


    image_dir = os.path.normpath(image_dir)
    output_dir = os.path.normpath(output_dir)

    pattern = os.path.join(image_dir, "*.png")

    image_files = glob.glob(pattern)
    total_images = len(image_files)

    image_count = 1

    for filename in os.listdir(image_dir):
        if filename.endswith(".png"):
            image_path = os.path.join(image_dir, filename)
            # image_path ="/media/menas/data/projects/pngtojpg/PGU_TI_sani/i240630_122337-0.png"
            print(f"Processing {image_path} : {image_count} of {total_images}")
            process_image(image_path, reader)
    
            image_count += 1
    print("")
    print("Results:")
    # Create KML
    extract_exif_and_create_kml(output_dir, os.path.join(output_dir,"pug_preview.kml"))
    print(f"- JPEG files with GEOTAG and TIME path: {output_dir}")
    # Check number of non processed files
    check_not_processed_file()
    
    

if __name__ == "__main__":
    main()
