import os

#Ask/Set user parameter
folder=input("\nGive folder Path:")


# Set the size threshold in bytes (e.g., 1 MB = 1,000,000 bytes)
size_threshold = 557480  # Change this value to your desired threshold
Sumup = "Leeren TIFs:\n"
counter=0

def execute_code(Sumup,counter):
    # List to store names of files to be deleted
    files_to_delete = []
    
    # Example processing code: Search for .tif files, check their sizes, and delete if below threshold
    print("Ich suche .tif files in Ordner: ...")
    tif_files = [f for f in os.listdir(folder) if f.lower().endswith('.tif')]
    if tif_files:
        print ("Es gibt "+str(len(tif_files))+" Tifs in Ordner")
        print ("Ich\33[93m lösche\33[0m folgenden TIFs (und TFWs) für dich:")
        for tif_file in tif_files:
            # Get the full path of the file
            file_path = os.path.join(folder, tif_file)
            # Get the size of the file in bytes
            file_size = os.path.getsize(file_path)
            # Get the file name without extension
            file_name_without_ext = os.path.splitext(tif_file)[0]
            if file_size < size_threshold:
                files_to_delete.append(file_name_without_ext)
                # Delete the file
                os.remove(file_path)
                print(f" - {tif_file}: {file_size} bytes (deleted)")
                Sumup=Sumup+tif_file+"\n"
        if files_to_delete:
            delete_tfw(files_to_delete)
            counter= counter +1
            
    else:
        print("No .tif files found in the selected folder.")
    return (Sumup,counter)



def delete_tfw(file_names):
    tfw_files = [f for f in os.listdir(folder) if f.lower().endswith('.tfw')]
    if tfw_files:
        for tfw_file in tfw_files:
            # Get the full path of the file
            file_path = os.path.join(folder, tfw_file)
            file_name_without_ext = os.path.splitext(tfw_file)[0]
            if file_name_without_ext in file_names:
                os.remove(file_path)


#Main
print ("\nIch werde alle leere Tifs aus "+folder+" \33[91mentfernen\33[0m, du wirst es nicht spüren\n") 
Sumup,counter=execute_code(Sumup,counter)
if counter==0:
    print ("\33[92mKein Tif gelöscht (die enthalten alle mindestens 1 Pixel Daten)\33[0m")
else:
    logopt=input("\nWollen eine Liste der gelöschten Files in Ordner ablegen? (geben Sie 1 für Ja):")
    if logopt=="1":
        logfile= open(folder+"/log.txt","w")
        logfile.write(Sumup)
        logfile.close
        
