"""Product tests on CI, with newly created Windows objects owned by this user.

Elevated hosted runners otherwise create cache directories owned by the local
Administrators group. Production deliberately accepts only the current user or
SYSTEM. Do not weaken that policy or rewrite existing directory ownership.
TOKEN_OWNER affects only new objects created by this test process; no privilege,
ACL, machine policy or other process is changed. Restore it on exit.
https://learn.microsoft.com/windows/win32/api/winnt/ns-winnt-token_owner
"""

from contextlib import contextmanager
import os
import sys


@contextmanager
def user_owned_test_objects():
    if os.name != "nt":
        yield
        return
    import ctypes
    from ctypes import wintypes
    from app.security.private_fs import (
        _windows_advapi32, _windows_kernel32, _windows_current_user_sid,
    )

    class TokenOwner(ctypes.Structure):
        _fields_ = [("owner", wintypes.LPVOID)]

    api, kernel = _windows_advapi32(), _windows_kernel32()
    api.SetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    api.SetTokenInformation.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    # QUERY | ADJUST_DEFAULT, for our own process only. No privilege enablement.
    if not api.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008 | 0x0080, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    sid_token = None
    try:
        required = wintypes.DWORD()
        api.GetTokenInformation(token, 4, None, 0, ctypes.byref(required))
        old = ctypes.create_string_buffer(required.value)
        if not api.GetTokenInformation(token, 4, old, required, ctypes.byref(required)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid, sid_token, sid_buffer = _windows_current_user_sid(api)
        new = TokenOwner(sid)
        if not api.SetTokenInformation(token, 4, ctypes.byref(new), ctypes.sizeof(new)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            # Keep both SID backing buffers alive through restoration.
            _ = sid_buffer
            if not api.SetTokenInformation(token, 4, old, required):
                raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if sid_token is not None:
            kernel.CloseHandle(sid_token)
        kernel.CloseHandle(token)


if __name__ == "__main__":
    import pytest
    with user_owned_test_objects():
        result = pytest.main(sys.argv[1:])
    raise SystemExit(result)
