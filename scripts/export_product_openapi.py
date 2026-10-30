"""Export the current product contract without starting services or models."""
import json
from pathlib import Path
import tempfile

from app.config import Settings
from app.workbench_app import create_workbench_app

with tempfile.TemporaryDirectory(prefix="esa-openapi-") as directory:
    root = Path(directory)
    app = create_workbench_app(Settings(workbench_enabled=True, data_dir=root, sqlite_path=root / "app.sqlite3"))
    target = Path(__file__).resolve().parents[1] / "frontend" / "openapi.json"
    target.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2), "utf8")
    print(target)
