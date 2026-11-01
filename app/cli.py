"""One application entry: explicit init, persistent serve, non-generating doctor."""
import argparse
import asyncio
import json
import os

from app.workspace import data_root, initialize, load_config


def main():
    parser = argparse.ArgumentParser(prog="esa")
    commands = parser.add_subparsers(dest="command",required=True)
    for name in ("init","serve","doctor","open"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir")
        if name == "init": command.add_argument("--sample",action="store_true")
        if name in ("serve","open"):
            command.add_argument("--port",type=int,default=8740)
            command.add_argument("--host",choices=["127.0.0.1","::1"],default="127.0.0.1")
        if name == 'open':
            command.add_argument('--no-browser',action='store_true')
            command.add_argument('--registry')
            command.add_argument('--existing', choices=['open','restart'])
            command.add_argument('--create',action='store_true',help='Explicitly initialize a new empty workspace')
    args = parser.parse_args()
    if args.command=='open':
        from app.launcher.core import open_workspace,selected_workspace,registry_path
        root=selected_workspace(args.data_dir,registry_path(args.registry))
        print(json.dumps(open_workspace(root,registry=args.registry,port=args.port,browser=not args.no_browser,create=args.create,existing_choice=args.existing),ensure_ascii=False))
        return
    root = data_root(args.data_dir)
    if args.command == "init":
        initialize(root,sample=args.sample)
        print("Initialized:",root);return
    from app.config import Settings
    settings = Settings(workbench_enabled=True,data_dir=root,sqlite_path=root/"app.sqlite3")
    if args.command == "doctor":
        from app.workspace import Workspace
        async def inspect():
            import httpx
            workspace = Workspace(settings)
            workspace.client=httpx.AsyncClient(trust_env=False,timeout=2,follow_redirects=False)
            workspace.started=workspace.db_path.is_file()
            try:
                status=await workspace.status();status.update(web=None,inspection='READ_ONLY_NO_STARTUP_OR_RECOVERY')
                print(json.dumps(status,ensure_ascii=False,indent=2))
            finally: await workspace.client.aclose()
        asyncio.run(inspect());return
    from app.launcher.core import serve_workspace
    serve_workspace(root,args.port,host=args.host,auto_port=False)


if __name__ == "__main__": main()
