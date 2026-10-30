"""Actual ZIP/executable probe with isolated Chinese paths and no developer PATH."""

import argparse
import json
import os
from pathlib import Path
import socket
import sqlite3
import statistics
import subprocess
import time
import zipfile

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument('--starts',type=int,choices=range(1,6),default=5)
    args = parser.parse_args()
    root = args.output.resolve()
    assert not root.exists()
    root.mkdir(parents=True)
    with zipfile.ZipFile(args.artifact) as archive:
        assert all((root / n).resolve().is_relative_to(root) for n in archive.namelist())
        archive.extractall(root)
    package = next(p.parent for p in root.glob("*/ESA.exe"))
    exe = package / "ESA.exe"
    data = root / "独立 TEST 工作区"
    environment = {
        k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME", "ESA_DATA_DIR"}
    }
    environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    environment["PYTHONUTF8"] = "1"

    def execute(*parts):
        started = time.monotonic()
        result = subprocess.run(
            [str(p) for p in parts],
            env=environment,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf8",
            timeout=45,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert result.returncode == 0, result.stderr
        return round(time.monotonic() - started, 3), result.stdout

    execute(
        package / "runtime/python.exe",
        "-I",
        "-X",
        "utf8",
        "-m",
        "app.cli",
        "init",
        "--sample",
        "--data-dir",
        data,
    )
    config = json.loads((data / "workspace.json").read_text("utf8"))
    config["model_endpoint"] = "http://127.0.0.1:1"
    (data / "workspace.json").write_text(json.dumps(config), "utf8")
    record = {
        "kind": "REAL_WINDOWS_ZIP_EXE_ISOLATED_PATH_NO_PYTHON_UV_NODE",
        "artifact": str(args.artifact.resolve()),
        "release": json.loads((package / "release.json").read_text("utf8")),
        "starts": [],
        "native_first_dialog": "NOT_RUN_APPLICATION_CONTROL_APPROVAL_TIMEOUT",
        "automatic_browser_open": "NOT_RUN_NATIVE_GUI",
        "program_path": str(package),
    }
    occupied = socket.socket()
    occupied.bind(("127.0.0.1", 0))
    occupied.listen()
    port = occupied.getsockname()[1]
    record["occupied_port"] = port
    cid = None
    try:
        with httpx.Client(trust_env=False, timeout=5, headers={"X-ESA-Request": "1"}) as client:
            for start in range(args.starts):
                elapsed, _ = execute(
                    exe,
                    "--data-dir",
                    data,
                    "--registry",
                    root / "workspaces.json",
                    "--port",
                    port,
                    "--no-browser",
                )
                info = json.loads((data / "instance.json").read_text("utf8"))
                url = info["url"]
                assert not url.endswith(":" + str(port))
                actual = client.get(url + "/api/instance").json()
                assert actual["instance_id"] == info["instance_id"]
                assert (
                    client.get(url + "/").status_code == 200
                    and not client.get(url + "/api/status").json()["chat"]["ready"]
                )
                if cid is None:
                    response = client.post(
                        url + "/api/conversations", json={"title": "安装与重启保留验证"}
                    )
                    response.raise_for_status()
                    cid = response.json()["id"]
                    reused, _ = execute(
                        exe,
                        "--data-dir",
                        data,
                        "--registry",
                        root / "workspaces.json",
                        "--port",
                        port,
                        "--no-browser",
                    )
                    again = json.loads((data / "instance.json").read_text("utf8"))
                    assert (
                        again["instance_id"] == info["instance_id"] and again["pid"] == info["pid"]
                    )
                    record["repeat_reuse_seconds"] = reused
                else:
                    assert client.get(url + "/api/conversations/" + cid).status_code == 200
                record["starts"].append(
                    {"elapsed_seconds": elapsed, "instance": info, "conversation_id": cid}
                )
                client.post(url + "/api/product/shutdown").raise_for_status()
                deadline = time.monotonic() + 12
                while (data / "instance.json").exists() and time.monotonic() < deadline:
                    time.sleep(0.1)
                assert not (data / "instance.json").exists()
        _, raw = execute(
            package / "runtime/python.exe",
            "-I",
            "-X",
            "utf8",
            "-c",
            "import app.cli,faiss,sqlite3,sys,json;print(json.dumps({'python':sys.version,'app':app.cli.__file__,'faiss':faiss.__file__}))",
        )
        runtime = json.loads(raw)
        assert Path(runtime["app"]).is_relative_to(package) and Path(
            runtime["faiss"]
        ).is_relative_to(package)
        with sqlite3.connect(data / "app.sqlite3") as db:
            assert db.execute("SELECT COUNT(*) FROM model_calls").fetchone()[0] == 0
        record["runtime"] = runtime
        record["startup_median_seconds"] = statistics.median(
            r["elapsed_seconds"] for r in record["starts"]
        )
        record["startup_max_seconds"] = max(r["elapsed_seconds"] for r in record["starts"])
        record["passed"] = True
    except Exception as exc:
        record["failure"] = str(exc)
        raise
    finally:
        occupied.close()
        (root.parent / ('WINDOWS_PORTABLE_'+record['release']['commit'][:8]+'.json')).write_text(
            json.dumps(record, ensure_ascii=False, indent=2), "utf8"
        )
        print(json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    main()
