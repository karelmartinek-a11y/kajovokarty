from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import json
import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from cryptography.fernet import Fernet, InvalidToken

from ...app.paths import AppPaths

_SERVICE: Final = "cz.kajovo.kajovokarty"


class SecretStoreError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ApiTokens:
    access_token: str = ""
    client_token: str = ""

    @property
    def complete(self) -> bool:
        return bool(self.access_token and self.client_token)


class SecretStore:
    """Encrypts Better Hotel tokens outside SQLite.

    Windows uses user-scoped DPAPI. The portable fallback is used only for development on
    non-Windows hosts and protects a local Fernet key with restrictive file permissions.
    """

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.path = paths.data_dir / "credentials.dat"
        self.key_path = paths.data_dir / ".credentials.key"

    def save_tokens(self, tokens: ApiTokens) -> None:
        self.paths.data_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"access_token": tokens.access_token, "client_token": tokens.client_token},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        encrypted = self._protect(payload)
        temp = self.path.with_suffix(".tmp")
        temp.write_bytes(encrypted)
        os.chmod(temp, 0o600)
        os.replace(temp, self.path)

    def load_tokens(self) -> ApiTokens:
        if not self.path.exists():
            return ApiTokens()
        try:
            payload = json.loads(self._unprotect(self.path.read_bytes()).decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError, InvalidToken) as exc:
            raise SecretStoreError("Uložené tokeny nelze bezpečně načíst.") from exc
        return ApiTokens(str(payload.get("access_token", "")), str(payload.get("client_token", "")))

    def clear_tokens(self) -> None:
        self.path.unlink(missing_ok=True)

    def _protect(self, payload: bytes) -> bytes:
        if platform.system() == "Windows":
            return _dpapi_protect(payload)
        return b"FERNET1\0" + self._fernet().encrypt(payload)

    def _unprotect(self, payload: bytes) -> bytes:
        if platform.system() == "Windows":
            return _dpapi_unprotect(payload)
        prefix = b"FERNET1\0"
        if not payload.startswith(prefix):
            raise SecretStoreError("Formát úložiště tajných údajů není podporován.")
        return self._fernet().decrypt(payload[len(prefix) :])

    def _fernet(self) -> Fernet:
        if not self.key_path.exists():
            key = Fernet.generate_key()
            self.key_path.write_bytes(key)
            os.chmod(self.key_path, 0o600)
        return Fernet(self.key_path.read_bytes())


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(data)
    pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    return _DataBlob(len(data), pointer), buffer


def _dpapi_protect(payload: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    source, source_buffer = _blob(payload)
    entropy_bytes = _SERVICE.encode("utf-8")
    entropy, entropy_buffer = _blob(entropy_bytes)
    output = _DataBlob()
    description = ctypes.c_wchar_p("KájovoKarty Better Hotel tokeny")
    flags = 0x01  # CRYPTPROTECT_UI_FORBIDDEN
    if not crypt32.CryptProtectData(
        ctypes.byref(source), description, ctypes.byref(entropy), None, None, flags, ctypes.byref(output)
    ):
        raise SecretStoreError(f"DPAPI šifrování selhalo: {ctypes.get_last_error()}")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)
        _ = source_buffer, entropy_buffer


def _dpapi_unprotect(payload: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    source, source_buffer = _blob(payload)
    entropy_bytes = _SERVICE.encode("utf-8")
    entropy, entropy_buffer = _blob(entropy_bytes)
    output = _DataBlob()
    description = ctypes.c_wchar_p()
    flags = 0x01
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), ctypes.byref(description), ctypes.byref(entropy), None, None, flags, ctypes.byref(output)
    ):
        raise SecretStoreError(f"DPAPI dešifrování selhalo: {ctypes.get_last_error()}")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)
        if description:
            kernel32.LocalFree(description)
        _ = source_buffer, entropy_buffer
