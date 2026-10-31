"""Build-time-only official embedded Python and hashed lock dependencies."""

import hashlib
import json
from pathlib import Path
from urllib.request import urlopen
import zipfile


def prepare_runtime(source, output, uv, command, *, embed_zip=None, offline=False):
    lock = hashlib.sha256((source / "uv.lock").read_bytes()).hexdigest()
    runtime = output / "build-cache" / ("python-312-" + lock[:12])
    marker = runtime / "prepared.json"
    if marker.is_file() and json.loads(marker.read_text("utf8")).get("lock_sha256") == lock:
        return runtime
    cache = (
        Path(embed_zip).resolve()
        if embed_zip
        else output / "build-cache/python-3.12.10-embed-amd64.zip"
    )
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not cache.is_file():
        if offline:
            raise FileNotFoundError(
                "Offline build needs --embed-zip: official CPython 3.12.10 embeddable ZIP"
            )
        with urlopen(
            "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip", timeout=60
        ) as response:
            cache.write_bytes(response.read())
    runtime.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(cache) as archive:
        if any(not (runtime / n).resolve().is_relative_to(runtime) for n in archive.namelist()):
            raise ValueError("Unsafe runtime archive")
        archive.extractall(runtime)
    (runtime / "python312._pth").write_text(
        "python312.zip\n.\nLib/site-packages\nimport site\n", "utf8"
    )
    requirements = runtime.parent / ("requirements-" + lock[:12] + ".txt")
    flags = ["--offline"] if offline else []
    command(
        uv,
        "export",
        "--locked",
        "--no-dev",
        "--no-emit-project",
        "--no-editable",
        *flags,
        "--output-file",
        requirements,
        cwd=source,
    )
    command(
        uv,
        "pip",
        "install",
        "--python",
        runtime / "python.exe",
        "--target",
        runtime / "Lib/site-packages",
        "--require-hashes",
        *flags,
        "-r",
        requirements,
        cwd=source,
    )
    marker.write_text(
        json.dumps(
            {
                "python": "3.12.10",
                "lock_sha256": lock,
                "official_zip_sha256": hashlib.sha256(cache.read_bytes()).hexdigest(),
            }
        ),
        "utf8",
    )
    return runtime
