import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "utils"))

import requests
from config import KYB_DATASET_URL

OUTPUT_PATH = "/data/kyb_entities.ftm.json"


def download_dataset(url: str, output_file: str) -> None:
    print(f"Downloading {url} → {output_file}")
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(output_file, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)
    print(f"Downloaded {output_file}")


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    if os.path.exists(OUTPUT_PATH):
        print(f"Dataset already present at {OUTPUT_PATH}, skipping download.")
    else:
        download_dataset(KYB_DATASET_URL, OUTPUT_PATH)
