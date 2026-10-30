"""Current single-workspace app factory; legacy protected APIs remain explicit in app.main."""
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.workspace import Workspace,workspace_router,install_workspace_errors

def create_workbench_app(settings):
    workspace=Workspace(settings)
    @asynccontextmanager
    async def lifespan(app):
        try:
            await workspace.start();yield
        finally:await workspace.close()
    app=FastAPI(title='ESA local knowledge and service workbench',lifespan=lifespan)
    app.state.workspace=workspace
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','[::1]','testserver'])
    install_workspace_errors(app)
    app.include_router(workspace_router(workspace))
    app.mount('/assets',StaticFiles(directory=Path(__file__).with_name('web')),name='workspace-assets')
    @app.get('/health/live')
    def live():return {'status':'alive'}
    @app.get('/health/ready')
    def ready():return {'status':'ready' if workspace.started else 'starting','storage':workspace.started,'generation':'CHECK_API_STATUS'}
    return app
