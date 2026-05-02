import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_json_atomic(
    path: Path,
    data: Any,
    *,
    indent: int | None = 2,
    ensure_ascii: bool = False,
) -> None:
    """Write JSON atomically so interrupted writes do not corrupt state files."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
        text=True,
    )
    tmp_path = Path(tmp_name)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_path, target)

    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        finally:
            raise
