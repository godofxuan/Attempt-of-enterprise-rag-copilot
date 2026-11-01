class WorkspaceError(Exception):
    def __init__(self, status, code, data=None):
        self.status = status
        self.code = code
        self.data = data or {}


def install_workspace_errors(application):
    from fastapi.responses import JSONResponse
    import sqlite3

    async def handle(request, exc):
        return JSONResponse(
            status_code=exc.status,
            content={"error": {"code": exc.code, "message": exc.code, "data": exc.data}},
        )

    application.add_exception_handler(WorkspaceError, handle)

    async def storage_error(request, exc):
        busy = "locked" in str(exc).lower() or "busy" in str(exc).lower()
        return JSONResponse(status_code=409 if busy else 500, content={"error": {
            "code": "STORAGE_BUSY" if busy else "STORAGE_ERROR",
            "message": "本地数据正在保存，请稍后重试当前操作；已保存内容保持不变。" if busy else "本地数据读取失败，请查看诊断。",
            "data": {"retryable": busy},
        }})
    application.add_exception_handler(sqlite3.OperationalError, storage_error)
