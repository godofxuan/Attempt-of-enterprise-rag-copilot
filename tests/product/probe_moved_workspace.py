"""Real packaged launcher recovery of the explicitly created native TEST fixture."""

import argparse
import json
import os
from pathlib import Path
import sqlite3
import time
import atexit

import httpx
from app.launcher.core import open_workspace, selected_workspace, read_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--original", type=Path, required=True)
    p.add_argument("--moved", type=Path, required=True)
    p.add_argument("--registry", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    old, new, registry = args.original.resolve(), args.moved.resolve(), args.registry.resolve()
    assert old.parent == new.parent == registry.parent and new != old and not new.exists()
    assert (
        old.name.startswith("native-")
        and json.loads((old / "workspace.json").read_text("utf8"))["sample_data"]
    )
    assert not args.out.exists()
    info = read_json(old / "instance.json") or open_workspace(old, registry=registry, browser=False)
    record = {
        "kind": "ACTUAL_WINDOWS_PACKAGED_RECOVERY_HTTP_NOT_GUI_NOT_MODEL",
        "old": str(old),
        "moved": str(new),
        "initial_instance": info,
    }
    atexit.register(
        lambda: args.out.write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf8")
    )
    with httpx.Client(
        base_url=info["url"], trust_env=False, timeout=5, headers={"X-ESA-Request": "1"}
    ) as client:
        actual = client.get("/api/instance").json()
        assert (
            actual["instance_id"] == info["instance_id"]
            and Path(actual["data_dir"]).resolve() == old
        )
        record["before_conversations"] = client.get("/api/conversations").json()
        assert any(r["title"] == "原生目录定位的保留历史" for r in record["before_conversations"])
        client.post("/api/product/shutdown").raise_for_status()
    until = time.monotonic() + 8
    while (old / "instance.json").exists() and time.monotonic() < until:
        time.sleep(0.1)
    assert not (old / "instance.json").exists()
    # Lifespan completion precedes final uvicorn/log-handle exit on Windows.
    # Wait for the exact owned process, never kill it or touch another process.
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, info["pid"])
        if handle:
            try:
                assert kernel.WaitForSingleObject(handle, 5000) == 0, (
                    "Owned server has not fully exited"
                )
            finally:
                kernel.CloseHandle(handle)
    # Exact checked siblings inside the explicitly named synthetic fixture root.
    old.rename(new)
    os.environ.pop("ESA_DATA_DIR", None)  # this probe child only, not user/global config
    assert selected_workspace(None, registry) == old
    try:
        open_workspace(old, registry=registry, browser=False)
    except RuntimeError as exc:
        assert "WORKSPACE_MISSING" in str(exc)
        record["missing_error"] = str(exc)
    else:
        raise AssertionError("Missing registry path must never initialize a new DB")
    assert not old.exists()
    restored = open_workspace(new, registry=registry, browser=False)
    with httpx.Client(
        base_url=restored["url"], trust_env=False, timeout=5, headers={"X-ESA-Request": "1"}
    ) as client:
        record["after_conversations"] = client.get("/api/conversations").json()
        assert record["after_conversations"] == record["before_conversations"]
        record["restored_instance"] = client.get("/api/instance").json()
        client.post("/api/product/shutdown").raise_for_status()
    with sqlite3.connect(new / "app.sqlite3") as db:
        record["model_calls"] = db.execute("SELECT COUNT(*) FROM model_calls").fetchone()[0]
        assert record["model_calls"] == 0
    record["passed"] = True
    record["native_browser_title_observed"] = "ESA · 本地助理 - Google Chrome"
    record["native_browser_url_verification"] = (
        "BLOCKED_COMPUTER_USE_COULD_NOT_CONFIRM_CURRENT_BROWSER_URL"
    )
    record["physical_ime"] = "NOT_RUN"
    args.out.write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf8")
    print(json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    main()
