"""Package source and public acceptance records from the repository allowlist."""
import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from validate_repository import DIRECTORIES, NAMED_FILES, ROOT_FILES, SECRET, allowed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('zip', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    relatives = set(NAMED_FILES | ROOT_FILES)
    for directory in DIRECTORIES:
        relatives.update(str(path.relative_to(root)) for path in (root / directory).glob('*.py'))
    args.zip.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(args.zip, 'w', compression=ZIP_DEFLATED) as bundle:
        for name in sorted(relatives):
            path = root / name
            if not path.is_file():
                raise ValueError(f'Release input missing: {name}')
            if not allowed(name) or path.is_symlink() or SECRET.search(path.read_bytes()):
                raise ValueError(f'Release input rejected: {name}')
            bundle.write(path, arcname='job-agent/' + name)
    with ZipFile(args.zip) as bundle:
        if bundle.testzip():
            raise ValueError('ZIP integrity check failed')
    print(f'Verified package saved to {args.zip}')


if __name__ == '__main__':
    main()
