"""Download a pinned, checksummed public Kraken base model (no archive data uploaded)."""
import hashlib
import os
from pathlib import Path
import urllib.request

REVISION = '316cf2a4b4b0cab5f3f8c4f28f3310ca3e03c726'
SHA256 = '972700b1c72de14bdde028f9b06d77f13c88ec60da5e942bb9e57aca421fa361'
URL = f'https://huggingface.co/small-models-for-glam/kraken-ppocrv6-tiny/resolve/{REVISION}/tiny.safetensors'


def main():
    root = Path(__file__).resolve().parents[1] / 'models' / 'kraken-ppocrv6-tiny'
    root.mkdir(parents=True, exist_ok=True)
    destination = root/'tiny.safetensors'
    temporary = root/'tiny.safetensors.partial'
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(URL, timeout=60) as response, temporary.open('wb') as output:
            for chunk in iter(lambda: response.read(1024*1024), b''):
                digest.update(chunk); output.write(chunk)
        if digest.hexdigest() != SHA256:
            raise ValueError('Model checksum mismatch; refusing to install.')
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    print(destination)


if __name__ == '__main__': main()
