from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import unicodedata
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ...domain.money import MoneyError, normalize_currency, to_minor

ProgressCallback = Callable[[int, int, str], None]
CancelCallback = Callable[[], bool]

_CZECH_MONTHS = {
    "leden": 1,
    "ledna": 1,
    "únor": 2,
    "února": 2,
    "brezen": 3,
    "březen": 3,
    "března": 3,
    "duben": 4,
    "dubna": 4,
    "květen": 5,
    "kveten": 5,
    "května": 5,
    "kvetna": 5,
    "červen": 6,
    "cerven": 6,
    "června": 6,
    "cervna": 6,
    "červenec": 7,
    "cervenec": 7,
    "července": 7,
    "cervence": 7,
    "srpen": 8,
    "srpna": 8,
    "září": 9,
    "zari": 9,
    "říjen": 10,
    "rijen": 10,
    "října": 10,
    "rijna": 10,
    "listopad": 11,
    "listopadu": 11,
    "prosinec": 12,
    "prosince": 12,
}


class ImportValidationError(ValueError):
    pass


class ImportCancelled(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ImmutableInput:
    original_path: Path
    snapshot_path: Path
    file_hash: str
    size: int

    def cleanup(self) -> None:
        self.snapshot_path.unlink(missing_ok=True)
        parent = self.snapshot_path.parent
        try:
            parent.rmdir()
        except OSError:
            return


def utc_now() -> str:
    from datetime import UTC

    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def normalize_header(value: object) -> str:
    text = unicodedata.normalize("NFC", "" if value is None else str(value)).strip()
    return re.sub(r"\s+", " ", text).casefold()


def normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", "" if value is None else str(value)).strip())


def parse_czech_date(value: object, *, allow_empty: bool = False) -> date | None:
    if value is None or str(value).strip() == "":
        if allow_empty:
            return None
        raise ImportValidationError("Datum chybí.")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = normalize_text(value).rstrip(".")
    for fmt in ("%d.%m.%Y", "%d. %m. %Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    match = re.fullmatch(r"(\d{1,2})\.?\s+([^\s]+)\s+(\d{4})", text, re.IGNORECASE)
    if not match:
        raise ImportValidationError(f"Neplatné datum: {value!r}")
    day = int(match.group(1))
    month_name = match.group(2).casefold().rstrip(".")
    month = _CZECH_MONTHS.get(month_name)
    if month is None:
        raise ImportValidationError(f"Neznámý český měsíc: {match.group(2)!r}")
    try:
        return date(int(match.group(3)), month, day)
    except ValueError as exc:
        raise ImportValidationError(f"Neplatné datum: {value!r}") from exc


def parse_datetime(value: object, *, allow_empty: bool = False) -> datetime | None:
    if value is None or str(value).strip() == "":
        if allow_empty:
            return None
        raise ImportValidationError("Datum a čas chybí.")
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    text = normalize_text(value)
    for fmt in (
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ImportValidationError(f"Neplatné datum a čas: {value!r}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_text(*parts: object) -> str:
    payload = "|".join(normalize_text(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha256_bytes(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def immutable_snapshot(path: Path) -> ImmutableInput:
    source = path.resolve(strict=True)
    if not source.is_file():
        raise ImportValidationError(f"Vstup není soubor: {source}")
    file_hash = sha256_bytes(source)
    temp_dir = Path(tempfile.mkdtemp(prefix="kajovokarty-import-"))
    target = temp_dir / source.name
    shutil.copyfile(source, target)
    copied_hash = sha256_bytes(target)
    if copied_hash != file_hash:
        target.unlink(missing_ok=True)
        temp_dir.rmdir()
        raise ImportValidationError("Vstupní soubor se při vytváření snapshotu změnil.")
    return ImmutableInput(source, target, file_hash, source.stat().st_size)


def map_headers(headers: Sequence[object], required: Sequence[str]) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for index, header in enumerate(headers):
        key = normalize_header(header)
        if key and key not in normalized:
            normalized[key] = index
    missing = [name for name in required if normalize_header(name) not in normalized]
    if missing:
        raise ImportValidationError("Soubor nemá očekávané sloupce. Chybí: " + ", ".join(missing))
    return {name: normalized[normalize_header(name)] for name in required}


def row_dict(row: Sequence[object], mapping: Mapping[str, int]) -> dict[str, object]:
    return {name: row[index] if index < len(row) else None for name, index in mapping.items()}


def money_minor(value: object, currency: object) -> tuple[int, str]:
    try:
        code = normalize_currency(str(currency))
        return to_minor(value, code), code
    except MoneyError as exc:
        raise ImportValidationError(str(exc)) from exc


def cancellation_point(cancel: CancelCallback | None) -> None:
    if cancel is not None and cancel():
        raise ImportCancelled("Operace byla bezpečně zrušena.")


def progress(callback: ProgressCallback | None, current: int, total: int, message: str) -> None:
    if callback is not None:
        callback(current, total, message)


def chunked(values: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    if size < 1:
        raise ValueError("Velikost dávky musí být kladná.")
    for start in range(0, len(values), size):
        yield values[start : start + size]
