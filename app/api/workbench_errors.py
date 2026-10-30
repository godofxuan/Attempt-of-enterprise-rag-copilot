class WorkspaceError(Exception):
    def __init__(self, status, code, data=None):
        self.status = status
        self.code = code
        self.data = data or {}


def install_workspace_errors(application):
    from fastapi.responses import JSONResponse

    async def handle(request, exc):
        return JSONResponse(
            status_code=exc.status,
            content={"error": {"code": exc.code, "message": exc.code, "data": exc.data}},
        )

    application.add_exception_handler(WorkspaceError, handle)
