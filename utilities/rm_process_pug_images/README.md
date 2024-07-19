## Generate Executable binaries / EXE

The WINDOWS version was created with pyinstaller. Pyinstaller and gdal - that is [quite a thing](https://stackoverflow.com/questions/56472933/pyinstaller-executable-fails).
Solution steps

1. Install pip packages
   ```sh
   pip install pyinstaller
    ```
2. run pyinstaller 
   ```sh
   pyinstaller --noconfirm --onefile --console --noconfirm --onefile --console  "rm_process_pug_images.py"
   ```
   ( Incase you don't find pyinstaller `python.exe" "<path_to_python>\Lib\site-packages\PyInstaller\__main__.py" --noconfirm --onefile --console  "rm_process_pug_images.py"`

3. copy files and folder
  - `pgu_mask.png`
  - folder `models` including content
  - `rm_process_pug_images.exe`

Now you shoudl be able to run it  whereever you are allowed to run  software ....
