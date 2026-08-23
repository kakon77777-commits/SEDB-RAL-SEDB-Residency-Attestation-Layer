from __future__ import annotations

import argparse
import gzip
import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path


def normalize_sdist(
    source: Path,
    target: Path,
    *,
    source_date_epoch: int,
) -> None:
    entries: list[tuple[tarfile.TarInfo, bytes | None]] = []
    with tarfile.open(source, mode="r:gz") as archive:
        for member in archive.getmembers():
            extracted = archive.extractfile(member) if member.isfile() else None
            entries.append(
                (member, None if extracted is None else extracted.read())
            )

    tar_buffer = io.BytesIO()
    with tarfile.open(
        fileobj=tar_buffer,
        mode="w",
        format=tarfile.PAX_FORMAT,
    ) as normalized_archive:
        for member, data in sorted(entries, key=lambda item: item[0].name):
            normalized = tarfile.TarInfo(member.name)
            normalized.type = member.type
            normalized.linkname = member.linkname
            normalized.mode = member.mode
            normalized.uid = 0
            normalized.gid = 0
            normalized.uname = ""
            normalized.gname = ""
            normalized.mtime = source_date_epoch
            normalized.devmajor = member.devmajor
            normalized.devminor = member.devminor
            normalized.pax_headers = {}
            normalized.size = 0 if data is None else len(data)
            normalized_archive.addfile(
                normalized,
                None if data is None else io.BytesIO(data),
            )

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as raw:
        with gzip.GzipFile(
            fileobj=raw,
            mode="wb",
            filename="",
            mtime=source_date_epoch,
        ) as compressed:
            compressed.write(tar_buffer.getvalue())


def build_artifacts(
    root: Path,
    output: Path,
    *,
    source_date_epoch: int,
) -> tuple[Path, Path]:
    output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["SOURCE_DATE_EPOCH"] = str(source_date_epoch)
    subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(output)],
        cwd=root,
        env=environment,
        check=True,
    )
    wheel = next(output.glob("*.whl"))
    sdist = next(output.glob("*.tar.gz"))
    normalized = sdist.with_suffix(sdist.suffix + ".normalized")
    normalize_sdist(
        sdist,
        normalized,
        source_date_epoch=source_date_epoch,
    )
    normalized.replace(sdist)
    return wheel, sdist


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--source-date-epoch", type=int, required=True)
    arguments = parser.parse_args()
    wheel, sdist = build_artifacts(
        arguments.root.resolve(),
        arguments.outdir.resolve(),
        source_date_epoch=arguments.source_date_epoch,
    )
    print(wheel)
    print(sdist)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
