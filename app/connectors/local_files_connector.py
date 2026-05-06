from __future__ import annotations

from pathlib import Path
import shutil


class LocalFilesConnector:
    def exists(self, path: str | Path) -> bool:
        return Path(path).exists()

    def read_text(self, path: str | Path, *, max_chars: int = 4000) -> str:
        return Path(path).read_text(encoding="utf-8", errors="replace")[:max_chars]

    def list_entries(self, folder: str | Path) -> list[Path]:
        return sorted(Path(folder).iterdir(), key=lambda path: (not path.is_dir(), path.name.lower()))

    def search_files(self, folder: str | Path, pattern: str = "*", *, limit: int = 20) -> list[Path]:
        results: list[Path] = []
        for item in Path(folder).rglob(pattern or "*"):
            if item.is_file():
                results.append(item)
                if len(results) >= limit:
                    break
        return results

    def write_text(self, path: str | Path, content: str, *, overwrite: bool = False) -> Path:
        target = Path(path)
        if target.exists() and not overwrite:
            raise FileExistsError(str(target))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def rename(self, source: str | Path, destination: str | Path) -> Path:
        target = Path(destination)
        if target.exists():
            raise FileExistsError(str(target))
        return Path(source).rename(target)

    def move(self, source: str | Path, destination: str | Path) -> Path:
        target = Path(destination)
        if target.exists():
            raise FileExistsError(str(target))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        return target
