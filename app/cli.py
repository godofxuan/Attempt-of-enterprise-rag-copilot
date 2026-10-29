"""One application entry: explicit init, persistent serve, non-generating doctor."""
import argparse
import asyncio
import json
import os

from app.workspace import data_root, initialize, load_config


def main():
    parser = argparse.ArgumentParser(prog="esa")
    commands = parser.add_subparsers(dest="command",required=True)
    for name in ("init","serve","doctor"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir")
        if name == "init": command.add_argument("--sample",action="store_true")
        if name == "serve":
            command.add_argument("--port",type=int,default=8740)
            command.add_argument("--host",choices=["127.0.0.1","::1"],default="127.0.0.1")
    args = parser.parse_args();root = data_root(args.data_dir)
    if args.command == "init":
        initialize(root,sample=args.sample)
        print("Initialized:",root);return
    from app.config import Settings
    from app.runtime.resources import build_service_container
    config = load_config(root)
    settings = Settings(workbench_enabled=True,data_dir=root,sqlite_path=root/"app.sqlite3",
                        chat_model=config.chat_model,embedding_model=config.embedding_model)
    if args.command == "doctor":
        from app.workspace import Workspace
        async def inspect():
            workspace = Workspace(settings)
            await workspace.start()
            try: print(json.dumps(await workspace.status(),ensure_ascii=False,indent=2))
            finally: await workspace.close()
        asyncio.run(inspect());return
    import uvicorn
    from app.main import create_app
    print("Workspace:",root,flush=True)
    print("URL: http://"+args.host+":"+str(args.port),flush=True)
    uvicorn.run(create_app(build_service_container(settings)),host=args.host,port=args.port,access_log=False)


if __name__ == "__main__": main()
