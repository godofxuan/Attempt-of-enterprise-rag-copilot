"""Compatibility imports; the product lives in bootstrap/API/persistence modules."""

from app.persistence.workspaces import (
    WorkspaceConfig,
    data_root,
    load_config,
    initialize,
    _initialize,
)
from app.bootstrap import Workspace
from app.api.workbench_errors import WorkspaceError, install_workspace_errors
from app.api.workbench_routes import workspace_router, require_local_request
