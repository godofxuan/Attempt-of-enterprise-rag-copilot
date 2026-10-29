"""One application owner per data directory; OS releases ownership on crash."""
import os


class WorkspaceLease:
    def __init__(self,root):self.path=root/'workspace.lock';self.file=None

    def acquire(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        stream=self.path.open('a+b')
        if self.path.stat().st_size==0:stream.write(b'\0');stream.flush()
        stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            stream.close();raise RuntimeError('WORKSPACE_ALREADY_RUNNING: '+str(self.path.parent)) from exc
        self.file=stream;return self

    def close(self):
        if not self.file:return
        try:
            self.file.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file,fcntl.LOCK_UN)
        finally:self.file.close();self.file=None

    def __enter__(self):return self.acquire()
    def __exit__(self,*exc):self.close()
