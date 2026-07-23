from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import stat
from typing import Iterator


class PrivatePathError(RuntimeError):
    pass


@dataclass(frozen=True)
class HeldPrivateDirectory:
    descriptor: int | None
    windows_handle: int | None
    windows_identity: tuple[int, int] | None


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]


class _TokenUser(ctypes.Structure):
    _fields_ = [("User", _SidAndAttributes)]


class _AceHeader(ctypes.Structure):
    _fields_ = [
        ("AceType", wintypes.BYTE),
        ("AceFlags", wintypes.BYTE),
        ("AceSize", wintypes.WORD),
    ]


class _AccessAllowedAce(ctypes.Structure):
    _fields_ = [
        ("Header", _AceHeader),
        ("Mask", wintypes.DWORD),
        ("SidStart", wintypes.DWORD),
    ]


class _AclSizeInformation(ctypes.Structure):
    _fields_ = [
        ("AceCount", wintypes.DWORD),
        ("AclBytesInUse", wintypes.DWORD),
        ("AclBytesFree", wintypes.DWORD),
    ]


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = [
        ("FileAttributes", wintypes.DWORD),
        ("CreationTime", wintypes.FILETIME),
        ("LastAccessTime", wintypes.FILETIME),
        ("LastWriteTime", wintypes.FILETIME),
        ("VolumeSerialNumber", wintypes.DWORD),
        ("FileSizeHigh", wintypes.DWORD),
        ("FileSizeLow", wintypes.DWORD),
        ("NumberOfLinks", wintypes.DWORD),
        ("FileIndexHigh", wintypes.DWORD),
        ("FileIndexLow", wintypes.DWORD),
    ]


def harden_private_directory(path: Path) -> None:
    root = Path(path).absolute()
    _validate_flat_regular_directory(root)
    if os.name == "nt":
        _set_windows_private_acl(root, directory=True)
        for entry in root.iterdir():
            _set_windows_private_acl(entry, directory=False)
    else:
        os.chmod(root, 0o700)
        for entry in root.iterdir():
            os.chmod(entry, 0o600)
    validate_private_directory_permissions(root)


def harden_held_private_directory(
    path: Path,
    held: HeldPrivateDirectory,
    *,
    expected_identity: tuple[int, int],
) -> None:
    root = Path(path).absolute()
    if not private_directory_identity_is_current(
        root,
        held,
        expected_identity,
    ):
        raise PrivatePathError(
            "private identity directory changed before hardening"
        )
    if os.name == "nt":
        _harden_held_windows_directory(root, held)
    else:
        _harden_held_posix_directory(held.descriptor, expected_identity)
    if not private_directory_identity_is_current(
        root,
        held,
        expected_identity,
    ):
        raise PrivatePathError(
            "private identity directory changed while hardening"
        )


def validate_private_directory_permissions(path: Path) -> None:
    if not private_directory_permissions_are_secure(path):
        raise PrivatePathError("private identity directory permissions are unsafe")


def private_directory_permissions_are_secure(path: Path) -> bool:
    root = Path(path).absolute()
    try:
        _validate_flat_regular_directory(root)
        if os.name == "nt":
            return _windows_acl_is_private(root, require_protected=True) and all(
                _windows_acl_is_private(entry, require_protected=False)
                for entry in root.iterdir()
            )
        root_mode = stat.S_IMODE(root.lstat().st_mode)
        if root.lstat().st_uid != os.geteuid() or root_mode & 0o077:
            return False
        for entry in root.iterdir():
            metadata = entry.lstat()
            if (
                metadata.st_uid != os.geteuid()
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) & 0o077
            ):
                return False
        return True
    except (OSError, PrivatePathError):
        return False


@contextmanager
def hold_private_directory(path: Path) -> Iterator[HeldPrivateDirectory]:
    root = Path(path).absolute()
    if os.name == "nt":
        handles: list[int] = []
        try:
            handles.append(
                _open_windows_directory_without_delete_share(
                    root,
                    security_write=True,
                )
            )
            for ancestor in root.parents:
                try:
                    handles.append(
                        _open_windows_directory_without_delete_share(ancestor)
                    )
                except PrivatePathError:
                    if ancestor == root.parent:
                        raise
                    break
            comparison = _open_windows_directory_without_delete_share(root)
            try:
                if _windows_directory_identity(
                    handles[0]
                ) != _windows_directory_identity(comparison):
                    raise PrivatePathError(
                        "private identity directory changed while opening"
                    )
            finally:
                _windows_kernel32().CloseHandle(comparison)
            yield HeldPrivateDirectory(
                descriptor=None,
                windows_handle=handles[0],
                windows_identity=_windows_directory_identity(handles[0]),
            )
        finally:
            for handle in reversed(handles):
                _windows_kernel32().CloseHandle(handle)
        return

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(root, flags)
    try:
        descriptor_metadata = os.fstat(descriptor)
        path_metadata = root.lstat()
        if (
            not stat.S_ISDIR(descriptor_metadata.st_mode)
            or stat.S_ISLNK(path_metadata.st_mode)
            or (descriptor_metadata.st_dev, descriptor_metadata.st_ino)
            != (path_metadata.st_dev, path_metadata.st_ino)
        ):
            raise PrivatePathError("private identity directory changed while opening")
        yield HeldPrivateDirectory(
            descriptor=descriptor,
            windows_handle=None,
            windows_identity=None,
        )
    finally:
        os.close(descriptor)


def sync_directory(descriptor: int | None) -> None:
    if descriptor is not None:
        os.fsync(descriptor)


def capture_private_directory_identity(
    path: Path,
    held: HeldPrivateDirectory,
) -> tuple[int, int]:
    root = Path(path).absolute()
    try:
        path_metadata = root.lstat()
        descriptor_metadata = (
            os.fstat(held.descriptor)
            if held.descriptor is not None
            else path_metadata
        )
    except OSError:
        raise PrivatePathError(
            "private identity directory identity is unavailable"
        ) from None
    if (
        not stat.S_ISDIR(path_metadata.st_mode)
        or stat.S_ISLNK(path_metadata.st_mode)
        or _is_reparse_point(path_metadata)
        or not stat.S_ISDIR(descriptor_metadata.st_mode)
        or (
            held.windows_handle is not None
            and not _windows_held_directory_is_current(root, held)
        )
        or (
            descriptor_metadata.st_dev,
            descriptor_metadata.st_ino,
        )
        != (path_metadata.st_dev, path_metadata.st_ino)
    ):
        raise PrivatePathError("private identity directory changed while opening")
    return descriptor_metadata.st_dev, descriptor_metadata.st_ino


def private_directory_identity_is_current(
    path: Path,
    held: HeldPrivateDirectory,
    expected: tuple[int, int],
) -> bool:
    try:
        return capture_private_directory_identity(path, held) == expected
    except PrivatePathError:
        return False


def _harden_held_posix_directory(
    descriptor: int | None,
    expected_identity: tuple[int, int],
) -> None:
    if descriptor is None:
        raise PrivatePathError("private identity directory descriptor is unavailable")
    _validate_held_posix_root(descriptor, expected_identity)
    entries = _open_held_posix_entries(descriptor)
    try:
        os.fchmod(descriptor, 0o700)
        for entry_descriptor, _ in entries:
            os.fchmod(entry_descriptor, 0o600)
        root_metadata = os.fstat(descriptor)
        if (
            (root_metadata.st_dev, root_metadata.st_ino) != expected_identity
            or stat.S_IMODE(root_metadata.st_mode) & 0o077
        ):
            raise PrivatePathError(
                "private identity directory permissions are unsafe"
            )
    except OSError:
        raise PrivatePathError(
            "private identity directory permissions are unsafe"
        ) from None
    finally:
        for entry_descriptor, _ in entries:
            os.close(entry_descriptor)

    verification_entries = _open_held_posix_entries(descriptor)
    try:
        if any(
            stat.S_IMODE(metadata.st_mode) & 0o077
            for _, metadata in verification_entries
        ):
            raise PrivatePathError(
                "private identity directory permissions are unsafe"
            )
    finally:
        for entry_descriptor, _ in verification_entries:
            os.close(entry_descriptor)


def _validate_held_posix_root(
    descriptor: int,
    expected_identity: tuple[int, int],
) -> os.stat_result:
    try:
        metadata = os.fstat(descriptor)
    except OSError:
        raise PrivatePathError(
            "private identity directory identity is unavailable"
        ) from None
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or (metadata.st_dev, metadata.st_ino) != expected_identity
    ):
        raise PrivatePathError("private identity directory changed while opening")
    return metadata


def _open_held_posix_entries(
    descriptor: int,
) -> list[tuple[int, os.stat_result]]:
    try:
        with os.scandir(descriptor) as scanned:
            candidates = [
                (entry.name, entry.stat(follow_symlinks=False))
                for entry in scanned
            ]
    except OSError:
        raise PrivatePathError(
            "private identity directory contents are unavailable"
        ) from None
    if any(
        not stat.S_ISREG(metadata.st_mode)
        or _is_reparse_point(metadata)
        or metadata.st_nlink != 1
        or metadata.st_uid != os.geteuid()
        for _, metadata in candidates
    ):
        raise PrivatePathError(
            "private identity directory contains an unsafe entry"
        )

    opened: list[tuple[int, os.stat_result]] = []
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        for name, _ in candidates:
            entry_descriptor = os.open(
                name,
                flags,
                dir_fd=descriptor,
            )
            try:
                metadata = os.fstat(entry_descriptor)
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or _is_reparse_point(metadata)
                    or metadata.st_nlink != 1
                    or metadata.st_uid != os.geteuid()
                ):
                    raise PrivatePathError(
                        "private identity directory contains an unsafe entry"
                    )
            except Exception:
                os.close(entry_descriptor)
                raise
            opened.append((entry_descriptor, metadata))
    except OSError:
        for entry_descriptor, _ in opened:
            os.close(entry_descriptor)
        raise PrivatePathError(
            "private identity directory contains an unsafe entry"
        ) from None
    except Exception:
        for entry_descriptor, _ in opened:
            os.close(entry_descriptor)
        raise
    return opened


def _harden_held_windows_directory(
    root: Path,
    held: HeldPrivateDirectory,
) -> None:
    root_handle = held.windows_handle
    if root_handle is None or held.windows_identity is None:
        raise PrivatePathError("private identity directory handle is unavailable")
    try:
        entries = list(root.iterdir())
    except OSError:
        raise PrivatePathError(
            "private identity directory contents are unavailable"
        ) from None

    opened: dict[str, int] = {}
    try:
        for entry in entries:
            if entry.name in opened:
                raise PrivatePathError(
                    "private identity directory contains an unsafe entry"
                )
            try:
                metadata = entry.lstat()
            except OSError:
                raise PrivatePathError(
                    "private identity directory contains an unsafe entry"
                ) from None
            if (
                not stat.S_ISREG(metadata.st_mode)
                or _is_reparse_point(metadata)
                or metadata.st_nlink != 1
            ):
                raise PrivatePathError(
                    "private identity directory contains an unsafe entry"
                )
            opened[entry.name] = _open_windows_regular_file_without_delete_share(
                entry,
                security_write=True,
            )
        if not _windows_held_directory_is_current(root, held) or not (
            _windows_entry_handles_are_current(root, opened)
        ):
            raise PrivatePathError(
                "private identity directory changed before hardening"
            )

        _set_windows_private_acl_handle(root_handle, directory=True)
        for entry_handle in opened.values():
            _set_windows_private_acl_handle(entry_handle, directory=False)

        if not _windows_handle_acl_is_private(
            root_handle,
            require_protected=True,
        ) or any(
            not _windows_handle_acl_is_private(
                entry_handle,
                require_protected=False,
            )
            for entry_handle in opened.values()
        ):
            raise PrivatePathError(
                "private identity directory permissions are unsafe"
            )
        if not _windows_held_directory_is_current(root, held) or not (
            _windows_entry_handles_are_current(root, opened)
        ):
            raise PrivatePathError(
                "private identity directory changed while hardening"
            )
    finally:
        for entry_handle in opened.values():
            _windows_kernel32().CloseHandle(entry_handle)


def _windows_held_directory_is_current(
    root: Path,
    held: HeldPrivateDirectory,
) -> bool:
    if held.windows_handle is None or held.windows_identity is None:
        return False
    try:
        metadata = root.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or _is_reparse_point(metadata)
        ):
            return False
        comparison = _open_windows_directory_without_delete_share(root)
    except (OSError, PrivatePathError):
        return False
    try:
        return (
            _windows_directory_identity(comparison)
            == held.windows_identity
        )
    except PrivatePathError:
        return False
    finally:
        _windows_kernel32().CloseHandle(comparison)


def _windows_entry_handles_are_current(
    root: Path,
    expected: dict[str, int],
) -> bool:
    try:
        current = list(root.iterdir())
    except OSError:
        return False
    if {entry.name for entry in current} != set(expected):
        return False
    for entry in current:
        try:
            comparison = _open_windows_regular_file_without_delete_share(
                entry,
                security_write=False,
            )
        except PrivatePathError:
            return False
        try:
            if _windows_directory_identity(comparison) != (
                _windows_directory_identity(expected[entry.name])
            ):
                return False
        except PrivatePathError:
            return False
        finally:
            _windows_kernel32().CloseHandle(comparison)
    return True


def replace_private_file(source: Path, target: Path) -> None:
    if os.name != "nt":
        os.replace(source, target)
        return
    kernel32 = _windows_kernel32()
    move_file = kernel32.MoveFileExW
    move_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
    ]
    move_file.restype = wintypes.BOOL
    if not move_file(str(source), str(target), 0x00000001 | 0x00000008):
        raise OSError(
            ctypes.get_last_error(),
            "private identity atomic replace failed",
        )


def _validate_flat_regular_directory(root: Path) -> None:
    metadata = root.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or _is_reparse_point(metadata)
    ):
        raise PrivatePathError("private identity directory is unsafe")
    if os.name != "nt" and metadata.st_uid != os.geteuid():
        raise PrivatePathError("private identity directory owner is unsafe")
    for entry in root.iterdir():
        entry_metadata = entry.lstat()
        if (
            not stat.S_ISREG(entry_metadata.st_mode)
            or _is_reparse_point(entry_metadata)
            or entry_metadata.st_nlink != 1
            or (
                os.name != "nt"
                and entry_metadata.st_uid != os.geteuid()
            )
        ):
            raise PrivatePathError("private identity directory contains an unsafe entry")


def _set_windows_private_acl(path: Path, *, directory: bool) -> None:
    advapi32 = _windows_advapi32()
    current_sid, token_handle, current_buffer = _windows_current_user_sid(advapi32)
    system_buffer = None
    try:
        system_buffer, system_sid = _windows_system_sid(advapi32)
        sid_lengths = [
            int(advapi32.GetLengthSid(current_sid)),
            int(advapi32.GetLengthSid(system_sid)),
        ]
        if any(length <= 0 for length in sid_lengths):
            raise PrivatePathError("private identity ACL operation failed")
        acl_size = 8 + sum(8 + length for length in sid_lengths)
        acl_buffer = ctypes.create_string_buffer(acl_size)
        if not advapi32.InitializeAcl(acl_buffer, acl_size, 2):
            raise PrivatePathError("private identity ACL operation failed")
        ace_flags = 0x03 if directory else 0x00
        for sid in (current_sid, system_sid):
            if not advapi32.AddAccessAllowedAceEx(
                acl_buffer,
                2,
                ace_flags,
                0x001F01FF,
                sid,
            ):
                raise PrivatePathError("private identity ACL operation failed")
        owner_is_trusted = _windows_path_owner_is_trusted(
            path,
            advapi32=advapi32,
            current_sid=current_sid,
            system_sid=system_sid,
        )
        if not owner_is_trusted:
            raise PrivatePathError("private identity directory owner is unsafe")
        security_information = 0x00000004 | 0x80000000
        result = advapi32.SetNamedSecurityInfoW(
            str(path),
            1,
            security_information,
            None,
            None,
            acl_buffer,
            None,
        )
        if result != 0:
            raise PrivatePathError("private identity ACL operation failed")
    finally:
        _ = current_buffer
        _ = system_buffer
        _windows_kernel32().CloseHandle(token_handle)


def _set_windows_private_acl_handle(
    handle: int,
    *,
    directory: bool,
) -> None:
    advapi32 = _windows_advapi32()
    current_sid, token_handle, current_buffer = _windows_current_user_sid(advapi32)
    system_buffer = None
    try:
        system_buffer, system_sid = _windows_system_sid(advapi32)
        sid_lengths = [
            int(advapi32.GetLengthSid(current_sid)),
            int(advapi32.GetLengthSid(system_sid)),
        ]
        if any(length <= 0 for length in sid_lengths):
            raise PrivatePathError("private identity ACL operation failed")
        acl_size = 8 + sum(8 + length for length in sid_lengths)
        acl_buffer = ctypes.create_string_buffer(acl_size)
        if not advapi32.InitializeAcl(acl_buffer, acl_size, 2):
            raise PrivatePathError("private identity ACL operation failed")
        ace_flags = 0x03 if directory else 0x00
        for sid in (current_sid, system_sid):
            if not advapi32.AddAccessAllowedAceEx(
                acl_buffer,
                2,
                ace_flags,
                0x001F01FF,
                sid,
            ):
                raise PrivatePathError("private identity ACL operation failed")
        owner_is_trusted = _windows_handle_owner_is_trusted(
            handle,
            advapi32=advapi32,
            current_sid=current_sid,
            system_sid=system_sid,
        )
        if not owner_is_trusted:
            raise PrivatePathError("private identity directory owner is unsafe")
        security_information = 0x00000004 | 0x80000000
        result = advapi32.SetSecurityInfo(
            handle,
            1,
            security_information,
            None,
            None,
            acl_buffer,
            None,
        )
        if result != 0:
            raise PrivatePathError("private identity ACL operation failed")
    finally:
        _ = current_buffer
        _ = system_buffer
        _windows_kernel32().CloseHandle(token_handle)


def _windows_handle_owner_is_trusted(
    handle: int,
    *,
    advapi32,
    current_sid,
    system_sid,
) -> bool:
    descriptor = wintypes.LPVOID()
    owner = wintypes.LPVOID()
    try:
        result = advapi32.GetSecurityInfo(
            handle,
            1,
            0x00000001,
            ctypes.byref(owner),
            None,
            None,
            None,
            ctypes.byref(descriptor),
        )
        return bool(
            result == 0
            and owner
            and (
                advapi32.EqualSid(owner, current_sid)
                or advapi32.EqualSid(owner, system_sid)
            )
        )
    finally:
        if descriptor:
            _windows_kernel32().LocalFree(descriptor)


def _windows_path_owner_is_trusted(
    path: Path,
    *,
    advapi32,
    current_sid,
    system_sid,
) -> bool:
    descriptor = wintypes.LPVOID()
    owner = wintypes.LPVOID()
    try:
        result = advapi32.GetNamedSecurityInfoW(
            str(path),
            1,
            0x00000001,
            ctypes.byref(owner),
            None,
            None,
            None,
            ctypes.byref(descriptor),
        )
        return bool(
            result == 0
            and owner
            and (
                advapi32.EqualSid(owner, current_sid)
                or advapi32.EqualSid(owner, system_sid)
            )
        )
    finally:
        if descriptor:
            _windows_kernel32().LocalFree(descriptor)


def _windows_acl_is_private(path: Path, *, require_protected: bool) -> bool:
    advapi32 = _windows_advapi32()
    current_sid, token_handle, current_buffer = _windows_current_user_sid(advapi32)
    system_buffer = None
    descriptor = wintypes.LPVOID()
    dacl = wintypes.LPVOID()
    owner = wintypes.LPVOID()
    try:
        system_buffer, system_sid = _windows_system_sid(advapi32)
        result = advapi32.GetNamedSecurityInfoW(
            str(path),
            1,
            0x00000001 | 0x00000004,
            ctypes.byref(owner),
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(descriptor),
        )
        if result != 0 or not dacl:
            return False
        if not owner or not (
            advapi32.EqualSid(owner, current_sid)
            or advapi32.EqualSid(owner, system_sid)
        ):
            return False
        if require_protected:
            control = wintypes.WORD()
            revision = wintypes.DWORD()
            if not advapi32.GetSecurityDescriptorControl(
                descriptor,
                ctypes.byref(control),
                ctypes.byref(revision),
            ) or not (control.value & 0x1000):
                return False
        info = _AclSizeInformation()
        if not advapi32.GetAclInformation(
            dacl,
            ctypes.byref(info),
            ctypes.sizeof(info),
            2,
        ) or info.AceCount != 2:
            return False
        matched = {"current": 0, "system": 0}
        for index in range(info.AceCount):
            ace = wintypes.LPVOID()
            if not advapi32.GetAce(dacl, index, ctypes.byref(ace)):
                return False
            allowed = ctypes.cast(ace, ctypes.POINTER(_AccessAllowedAce)).contents
            if allowed.Header.AceType != 0 or (
                int(allowed.Mask) & 0x001F01FF
            ) != 0x001F01FF:
                return False
            sid_address = int(ace.value) + _AccessAllowedAce.SidStart.offset
            sid = ctypes.c_void_p(sid_address)
            if advapi32.EqualSid(sid, current_sid):
                matched["current"] += 1
            elif advapi32.EqualSid(sid, system_sid):
                matched["system"] += 1
            else:
                return False
        return matched == {"current": 1, "system": 1}
    finally:
        _ = current_buffer
        _ = system_buffer
        if descriptor:
            _windows_kernel32().LocalFree(descriptor)
        _windows_kernel32().CloseHandle(token_handle)


def _windows_handle_acl_is_private(
    handle: int,
    *,
    require_protected: bool,
) -> bool:
    advapi32 = _windows_advapi32()
    current_sid, token_handle, current_buffer = _windows_current_user_sid(advapi32)
    system_buffer = None
    descriptor = wintypes.LPVOID()
    dacl = wintypes.LPVOID()
    owner = wintypes.LPVOID()
    try:
        system_buffer, system_sid = _windows_system_sid(advapi32)
        result = advapi32.GetSecurityInfo(
            handle,
            1,
            0x00000001 | 0x00000004,
            ctypes.byref(owner),
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(descriptor),
        )
        if result != 0 or not dacl:
            return False
        if not owner or not (
            advapi32.EqualSid(owner, current_sid)
            or advapi32.EqualSid(owner, system_sid)
        ):
            return False
        if require_protected:
            control = wintypes.WORD()
            revision = wintypes.DWORD()
            if not advapi32.GetSecurityDescriptorControl(
                descriptor,
                ctypes.byref(control),
                ctypes.byref(revision),
            ) or not (control.value & 0x1000):
                return False
        info = _AclSizeInformation()
        if not advapi32.GetAclInformation(
            dacl,
            ctypes.byref(info),
            ctypes.sizeof(info),
            2,
        ) or info.AceCount != 2:
            return False
        matched = {"current": 0, "system": 0}
        for index in range(info.AceCount):
            ace = wintypes.LPVOID()
            if not advapi32.GetAce(dacl, index, ctypes.byref(ace)):
                return False
            allowed = ctypes.cast(ace, ctypes.POINTER(_AccessAllowedAce)).contents
            if allowed.Header.AceType != 0 or (
                int(allowed.Mask) & 0x001F01FF
            ) != 0x001F01FF:
                return False
            sid_address = int(ace.value) + _AccessAllowedAce.SidStart.offset
            sid = ctypes.c_void_p(sid_address)
            if advapi32.EqualSid(sid, current_sid):
                matched["current"] += 1
            elif advapi32.EqualSid(sid, system_sid):
                matched["system"] += 1
            else:
                return False
        return matched == {"current": 1, "system": 1}
    finally:
        _ = current_buffer
        _ = system_buffer
        if descriptor:
            _windows_kernel32().LocalFree(descriptor)
        _windows_kernel32().CloseHandle(token_handle)


def _windows_current_user_sid(advapi32):
    kernel32 = _windows_kernel32()
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(),
        0x0008,
        ctypes.byref(token),
    ):
        raise PrivatePathError("private identity ACL operation failed")
    required = wintypes.DWORD()
    advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
    if required.value <= 0:
        kernel32.CloseHandle(token)
        raise PrivatePathError("private identity ACL operation failed")
    buffer = ctypes.create_string_buffer(required.value)
    if not advapi32.GetTokenInformation(
        token,
        1,
        buffer,
        required,
        ctypes.byref(required),
    ):
        kernel32.CloseHandle(token)
        raise PrivatePathError("private identity ACL operation failed")
    token_user = ctypes.cast(buffer, ctypes.POINTER(_TokenUser)).contents
    return token_user.User.Sid, token, buffer


def _windows_system_sid(advapi32):
    required = wintypes.DWORD(68)
    buffer = ctypes.create_string_buffer(required.value)
    if not advapi32.CreateWellKnownSid(
        22,
        None,
        buffer,
        ctypes.byref(required),
    ):
        raise PrivatePathError("private identity ACL operation failed")
    return buffer, ctypes.cast(buffer, wintypes.LPVOID)


def _windows_advapi32():
    library = ctypes.WinDLL("advapi32", use_last_error=True)
    library.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    library.OpenProcessToken.restype = wintypes.BOOL
    library.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    library.GetTokenInformation.restype = wintypes.BOOL
    library.GetLengthSid.argtypes = [wintypes.LPVOID]
    library.GetLengthSid.restype = wintypes.DWORD
    library.InitializeAcl.argtypes = [wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD]
    library.InitializeAcl.restype = wintypes.BOOL
    library.AddAccessAllowedAceEx.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
    ]
    library.AddAccessAllowedAceEx.restype = wintypes.BOOL
    library.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    library.SetNamedSecurityInfoW.restype = wintypes.DWORD
    library.SetSecurityInfo.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    library.SetSecurityInfo.restype = wintypes.DWORD
    library.CreateWellKnownSid.argtypes = [
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.DWORD),
    ]
    library.CreateWellKnownSid.restype = wintypes.BOOL
    library.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
    ]
    library.GetNamedSecurityInfoW.restype = wintypes.DWORD
    library.GetSecurityInfo.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
    ]
    library.GetSecurityInfo.restype = wintypes.DWORD
    library.GetSecurityDescriptorControl.argtypes = [
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.WORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    library.GetSecurityDescriptorControl.restype = wintypes.BOOL
    library.GetAclInformation.argtypes = [
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.c_int,
    ]
    library.GetAclInformation.restype = wintypes.BOOL
    library.GetAce.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
    ]
    library.GetAce.restype = wintypes.BOOL
    library.EqualSid.argtypes = [wintypes.LPVOID, wintypes.LPVOID]
    library.EqualSid.restype = wintypes.BOOL
    return library


def _open_windows_directory_without_delete_share(
    path: Path,
    *,
    security_write: bool = False,
) -> int:
    kernel32 = _windows_kernel32()
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    desired_access = 0x0080
    if security_write:
        desired_access |= 0x00020000 | 0x00040000
    handle = create_file(
        str(path),
        desired_access,
        0x00000001 | 0x00000002,
        None,
        3,
        0x02000000 | 0x00200000,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle in {None, invalid}:
        raise PrivatePathError("private identity directory could not be locked")
    return int(handle)


def _open_windows_regular_file_without_delete_share(
    path: Path,
    *,
    security_write: bool,
) -> int:
    kernel32 = _windows_kernel32()
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    desired_access = 0x0080
    if security_write:
        desired_access |= 0x00020000 | 0x00040000
    handle = create_file(
        str(path),
        desired_access,
        0x00000001 | 0x00000002,
        None,
        3,
        0x00200000,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle in {None, invalid}:
        raise PrivatePathError(
            "private identity directory contains an unsafe entry"
        )
    result = int(handle)
    try:
        information = _windows_handle_information(result)
        if (
            information.FileAttributes & 0x00000010
            or information.FileAttributes & 0x00000400
            or int(information.NumberOfLinks) != 1
        ):
            raise PrivatePathError(
                "private identity directory contains an unsafe entry"
            )
    except Exception:
        kernel32.CloseHandle(result)
        raise
    return result


def _windows_handle_information(handle: int) -> _ByHandleFileInformation:
    kernel32 = _windows_kernel32()
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ByHandleFileInformation),
    ]
    get_information.restype = wintypes.BOOL
    information = _ByHandleFileInformation()
    if not get_information(handle, ctypes.byref(information)):
        raise PrivatePathError(
            "private identity directory identity is unavailable"
        )
    return information


def _windows_directory_identity(handle: int) -> tuple[int, int]:
    information = _windows_handle_information(handle)
    file_index = (
        int(information.FileIndexHigh) << 32
    ) | int(information.FileIndexLow)
    return int(information.VolumeSerialNumber), file_index


def _windows_kernel32():
    library = ctypes.WinDLL("kernel32", use_last_error=True)
    library.GetCurrentProcess.argtypes = []
    library.GetCurrentProcess.restype = wintypes.HANDLE
    library.CloseHandle.argtypes = [wintypes.HANDLE]
    library.CloseHandle.restype = wintypes.BOOL
    library.LocalFree.argtypes = [wintypes.LPVOID]
    library.LocalFree.restype = wintypes.LPVOID
    return library


def _is_reparse_point(metadata: os.stat_result) -> bool:
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return bool(attributes & reparse)


__all__ = [
    "HeldPrivateDirectory",
    "PrivatePathError",
    "capture_private_directory_identity",
    "harden_private_directory",
    "harden_held_private_directory",
    "hold_private_directory",
    "private_directory_identity_is_current",
    "private_directory_permissions_are_secure",
    "replace_private_file",
    "sync_directory",
    "validate_private_directory_permissions",
]
