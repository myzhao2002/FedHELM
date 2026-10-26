"""Download the official processed ALFA archive, verify its checksum, extract CSV only."""
import argparse
import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('data/alfa'))
    args = parser.parse_args()
    root = args.directory.resolve()
    root.mkdir(parents=True, exist_ok=True)
    url = 'https://api.figshare.com/v2/articles/12707963'
    with urllib.request.urlopen(url, timeout=60) as response:
        metadata = json.load(response)
    entry = next(f for f in metadata['files'] if f['name'] == 'processed.zip')
    archive = root / 'processed.zip'
    if not archive.exists() or archive.stat().st_size != entry['size']:
        temporary = root / 'processed.zip.part'
        print('Downloading official ALFA processed.zip', flush=True)
        with urllib.request.urlopen(entry['download_url'], timeout=120) as response, temporary.open('wb') as out:
            while chunk := response.read(1024 * 1024):
                out.write(chunk)
        temporary.replace(archive)
    checksum = hashlib.md5(archive.read_bytes()).hexdigest()
    expected = entry.get('computed_md5') or entry.get('supplied_md5')
    if expected and checksum != expected:
        raise ValueError('Archive checksum mismatch; refusing extraction')
    count = 0
    with zipfile.ZipFile(archive) as zipped:
        for member in zipped.infolist():
            if not member.filename.lower().endswith(('.csv', '.txt')):
                continue
            destination = (root / member.filename).resolve()
            if not destination.is_relative_to(root):
                raise ValueError('Unsafe archive member')
            destination.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(member) as source, destination.open('wb') as target:
                import shutil
                shutil.copyfileobj(source, target)
            count += 1
    (root / 'source.json').write_text(json.dumps({'source': url, 'doi': metadata.get('doi'),
        'file': entry, 'verified_md5': checksum, 'extracted_files': count}, indent=2), encoding='utf-8')
    print(f'Verified and extracted {count} CSV/text files to {root}')


if __name__ == '__main__':
    main()
