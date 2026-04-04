from __future__ import annotations

from pathlib import Path
from threading import RLock

import yaml
from pydantic import ValidationError

from config.settings import settings
from models import SemanticModel


class SemanticConfigError(RuntimeError):
    pass


class SemanticConfigLoader:
    def __init__(self, config_path: str | Path | None = None) -> None:
        self._path = self._resolve_path(config_path or settings.semantic_model_path)
        self._lock = RLock()
        self._cached_model: SemanticModel | None = None
        self._cached_mtime: float | None = None
        self._version = 0

    def _resolve_path(self, config_path: str | Path) -> Path:
        path = Path(config_path)
        if path.is_absolute():
            return path
        project_root = Path(__file__).resolve().parents[2]
        return project_root / path

    @property
    def path(self) -> Path:
        return self._path

    def load_semantic_model(self, force_reload: bool = False) -> SemanticModel:
        with self._lock:
            if not self._path.exists():
                raise SemanticConfigError(f"Semantic model file not found: {self._path}")

            mtime = self._path.stat().st_mtime
            if (
                not force_reload
                and self._cached_model is not None
                and self._cached_mtime == mtime
            ):
                return self._cached_model

            try:
                payload = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
                model = SemanticModel.model_validate(payload)
            except ValidationError as exc:
                raise SemanticConfigError(
                    f"Semantic model validation failed: {exc}"
                ) from exc
            except yaml.YAMLError as exc:
                raise SemanticConfigError(f"Semantic YAML parse failed: {exc}") from exc

            self._cached_model = model
            self._cached_mtime = mtime
            self._version += 1
            return model

    def get_version(self) -> int:
        with self._lock:
            return self._version


_loader = SemanticConfigLoader()


def get_semantic_model(force_reload: bool = False) -> SemanticModel:
    return _loader.load_semantic_model(force_reload=force_reload)


def get_semantic_model_version() -> int:
    return _loader.get_version()
