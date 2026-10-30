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
            await workspace.start()
            if getattr(workspace,'instance_info',None):
                import json
                temp=workspace.root/'instance.json.tmp'
                temp.write_text(json.dumps(workspace.instance_info),'utf8')
                temp.replace(workspace.root/'instance.json')
            yield
        finally:
            await workspace.close()
            from app.launcher.core import read_json
            info=getattr(workspace,'instance_info',None)
            path=workspace.root/'instance.json'
            if info and read_json(path).get('instance_id')==info['instance_id']:
                path.unlink(missing_ok=True)
    app=FastAPI(title='ESA local knowledge and service workbench',lifespan=lifespan)
    app.state.workspace=workspace
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','[::1]','testserver'])
    install_workspace_errors(app)
    app.include_router(workspace_router(workspace))
    app.mount('/assets',StaticFiles(directory=Path(__file__).with_name('web')),name='workspace-assets')
    frontend=Path(__file__).with_name('web_dist')
    if frontend.is_dir():
        app.mount('/ui',StaticFiles(directory=frontend),name='product-ui')
    @app.get('/health/live')
    def live():return {'status':'alive'}
    @app.get('/health/ready')
    def ready():return {'status':'ready' if workspace.started else 'starting','storage':workspace.started,'generation':'CHECK_API_STATUS'}
    @app.get('/api/instance')
    def instance():
        return {**getattr(workspace,'instance_info',{}),'app':'esa-workbench','data_dir':str(workspace.root),'ready':workspace.started}
    return app
