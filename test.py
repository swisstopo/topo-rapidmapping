import requests


def download_asset(asset_url, filename):
    # Imposta il proxy
    session = requests.Session()
    session.proxies = {"https": "http://proxy-bvcol.admin.ch:8080"}

    # Fai la richiesta per scaricare il file
    response = session.get(asset_url, stream=True)

    if response.status_code == 200:
        # Salva il file con il nome specificato
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)
        print(f"File scaricato con successo: {filename}")
    else:
        print(f"Errore durante il download: {response.status_code}")


if __name__ == "__main__":
    asset_url = "https://data.geo.admin.ch/ch.swisstopo.swissimage-dop10/swissimage-dop10_2017_2517-1139/swissimage-dop10_2017_2517-1139_2_2056.tif"
    filename = "swissimage-dop10_2017_2517-1139_2_2056.tif"
    download_asset(asset_url,filename)
    breakpoint()
    print("done")
