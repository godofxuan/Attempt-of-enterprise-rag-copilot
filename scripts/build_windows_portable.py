"""Build the actual Windows x64 product from a commit, not an author's venv.

Prepare the official CPython 3.12.10 embeddable runtime and install requirements
exported from uv.lock once at BUILD time. This script does no runtime downloads.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from windows_runtime import prepare_runtime

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--ref", default="HEAD")
parser.add_argument(
    "--runtime",
    type=Path,
    help="Optional explicitly prepared runtime; default builds it from uv.lock",
)
parser.add_argument("--embed-zip", type=Path, help="Optional official embedded CPython ZIP cache")
parser.add_argument(
    "--uv", default=shutil.which("uv") or str(Path(sys.executable).with_name("uv.exe"))
)
parser.add_argument("--npm", default=shutil.which("npm.cmd") or shutil.which("npm") or "npm")
parser.add_argument("--offline", action="store_true")
parser.add_argument("--output-dir", default=".private/esa-vnext/build/releases")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
commit = subprocess.check_output(
    ["git", "rev-parse", args.ref + "^{commit}"], cwd=root, text=True
).strip()
version = tomllib.loads(
    subprocess.check_output(["git", "show", commit + ":pyproject.toml"], cwd=root, text=True)
)["project"]["version"]
output = (root / args.output_dir).resolve()
output.mkdir(parents=True, exist_ok=True)
package = output / ("ESA-" + version + "-windows-x64-" + commit[:8])
assert not package.exists(), package
source = output / ("_source-" + commit[:8])
assert not source.exists(), source
paths = [
    "app",
    "frontend",
    "pyproject.toml",
    "uv.lock",
    "README.md",
    "packaging/windows/Launcher.cs",
]
if subprocess.check_output(["git", "ls-tree", commit, "--", "LICENSE"], cwd=root).strip():
    paths.append("LICENSE")
archive = subprocess.check_output(["git", "archive", "--format=tar", commit, *paths], cwd=root)
source.mkdir()
with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
    for entry in tar.getmembers():
        assert (source / entry.name).resolve().is_relative_to(source)
        assert not entry.issym() and not entry.islnk()
    tar.extractall(source, filter="data")
package.mkdir()
logs = output / ("BUILD_" + commit[:8] + ".log")
uv = args.uv


def command(*parts, cwd=root):
    with logs.open("a", encoding="utf8") as log:
        result = subprocess.run(
            [str(p) for p in parts], cwd=cwd, stdout=log, stderr=subprocess.STDOUT
        )
    if result.returncode:
        raise RuntimeError("Build step failed: " + str(parts[0]) + "; " + str(logs))


try:
    (source / "app/resources/build.json").write_text(json.dumps({
        "version":version,"source_commit":commit,"build_id":commit,"source_dirty":False,
    }),"utf8")
    command(
        args.npm,
        "ci",
        "--ignore-scripts",
        *(["--offline"] if args.offline else []),
        cwd=source / "frontend",
    )
    command(args.npm, "run", "build", cwd=source / "frontend")
    runtime = (
        args.runtime.resolve()
        if args.runtime
        else prepare_runtime(
            source, output, uv, command, embed_zip=args.embed_zip, offline=args.offline
        )
    )
    assert (runtime / "python.exe").exists() and (runtime / "Lib/site-packages/faiss").is_dir()
    # This is the official embedded runtime + lock-built wheel dependencies.
    # No author environment, user data, model or index is included.
    shutil.copytree(runtime, package / "runtime")
    command(
        uv,
        "build",
        *(["--offline"] if args.offline else []),
        "--default-index",
        "https://pypi.org/simple",
        "--wheel",
        "--python",
        sys.executable,
        "--out-dir",
        output / ("wheel-" + commit[:8]),
        source,
    )
    wheel = next((output / ("wheel-" + commit[:8])).glob("*.whl"))
    command(
        uv,
        "pip",
        "install",
        "--offline",
        "--no-deps",
        "--python",
        package / "runtime/python.exe",
        "--target",
        package / "runtime/Lib/site-packages",
        wheel,
    )
    compiler = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
    command(
        compiler,
        "/nologo",
        "/target:winexe",
        "/reference:System.Windows.Forms.dll",
        "/reference:System.Drawing.dll",
        "/reference:System.Web.Extensions.dll",
        "/out:" + str(package / "ESA.exe"),
        source / "packaging/windows/Launcher.cs",
    )
    if (source / "LICENSE").exists():
        shutil.copy2(source / "LICENSE", package / "LICENSE")
    (package / "使用说明.txt").write_text(
        "完整解压此目录，然后双击ESA.exe。\n首次明确选择已有工作区或新建；内置Python及依赖，不需要安装Node/Python/uv。\n模型权重不包含；使用已有本机Ollama与模型。模型未连接也可以打开设置和历史。\n数据保存在你明确选择的工作区，升级程序不重建数据库。\n日常启动不安装依赖、不下载模型。服务台仅为本地合成TEST。\n设置中可停止本地服务；关闭浏览器不清空数据。\n",
        "utf8",
    )
    (package / "release.json").write_text(
        json.dumps(
            {
                "version": version,
                "commit": commit,
                "platform": "Windows x64",
                "python": "3.12.10 official embeddable",
                "launcher": "ESA.exe",
                "entry": "app.launcher -> create_workbench_app",
                "dependency_lock": "uv.lock",
                "runtime_package_installation": False,
                "includes_models_or_data": False,
            },
            indent=2,
        ),
        "utf8",
    )
    # The product must work without repo/import/PATH dependencies.
    command(
        package / "runtime/python.exe",
        "-I",
        "-c",
        "import faiss,sqlite3,app.cli;from importlib.metadata import version;assert version('enterprise-service-agent')=='"
        + version
        + "';print(app.cli.__file__)",
    )
    target = Path(str(package) + ".zip")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for p in sorted(package.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                zipped.write(p, p.relative_to(output).as_posix())
    with zipfile.ZipFile(target) as zipped:
        assert zipped.testzip() is None
    result = {
        "folder": str(package),
        "archive": str(target),
        "version": version,
        "commit": commit,
        "bytes": target.stat().st_size,
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }
    (output / ("BUILD_" + commit[:8] + ".json")).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), "utf8"
    )
    print(json.dumps(result, ensure_ascii=False))
finally:
    # Remove only our checked cold extraction, never a workspace/runtime.
    assert source.resolve().parent == output
    shutil.rmtree(source)
