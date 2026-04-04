from __future__ import annotations

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent


def find_env_file() -> Path:
    for candidate in (REPO_ROOT / ".env", BACKEND_ROOT / ".env"):
        if candidate.exists():
            return candidate
    return REPO_ROOT / ".env"


def resolve_app_path(path_value: str | Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path

    candidates: list[Path] = [
        Path.cwd() / path,
        BACKEND_ROOT / path,
        REPO_ROOT / path,
    ]

    if path.parts and path.parts[0] == "backend" and len(path.parts) > 1:
        trimmed = Path(*path.parts[1:])
        candidates.extend(
            [
                BACKEND_ROOT / trimmed,
                REPO_ROOT / path,
            ]
        )

    seen: set[Path] = set()
    ordered_candidates: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        ordered_candidates.append(resolved)

    for candidate in ordered_candidates:
        if candidate.exists():
            return candidate

    if path.parts and path.parts[0] == "backend" and len(path.parts) > 1:
        return (BACKEND_ROOT / Path(*path.parts[1:])).resolve(strict=False)
    return (BACKEND_ROOT / path).resolve(strict=False)
