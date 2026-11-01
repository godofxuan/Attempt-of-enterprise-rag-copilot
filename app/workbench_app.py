"""Current single-workspace app factory; legacy protected APIs remain explicit in app.main."""
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.bootstrap import Workspace
from app.api.workbench_routes import workspace_router
from app.api.workbench_errors import install_workspace_errors

def create_workbench_app(settings, *, model_transport=None):
    workspace=Workspace(settings)
    workspace.model_transport=model_transport
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
        from app.build_info import build_info
        return {**getattr(workspace,'instance_info',{}), **build_info(),
                'app':'esa-workbench','data_dir':str(workspace.root),'ready':workspace.started,
                'active_runs':len(workspace.runs.tasks) if workspace.started else 0,
                'index_jobs':len(workspace.library.running) if workspace.started else 0,
                'active_operations':getattr(workspace,'active_operations',0)}
    @app.middleware('http')
    async def active_operations(request, call_next):
        tracked = request.method not in {'GET','HEAD','OPTIONS'}
        if tracked: workspace.active_operations = getattr(workspace,'active_operations',0) + 1
        try: return await call_next(request)
        finally:
            if tracked: workspace.active_operations -= 1
    return app
