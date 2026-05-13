import os
from typing import List, Optional

import config


def _clean_rel_path(path: str) -> str:
    return (path or "").strip().replace("\\", "/").lstrip("/")


def _safe_join(root: str, *parts: str) -> Optional[str]:
    root_abs = os.path.abspath(root)
    candidate = os.path.abspath(os.path.join(root_abs, *parts))
    try:
        if os.path.commonpath([root_abs, candidate]) != root_abs:
            return None
    except ValueError:
        return None
    return candidate


def media_relative_path(year_month: str, filename: str) -> str:
    return f"media/{year_month}/{filename}"


def _media_suffix(local_path: str) -> str:
    rel = _clean_rel_path(local_path)
    for prefix in ("webchat/media/", "media/"):
        if rel.startswith(prefix):
            return rel[len(prefix):]
    return rel


def media_path_candidates(
    local_path: str,
    media_root: Optional[str] = None,
    project_root: Optional[str] = None,
) -> List[str]:
    rel = _clean_rel_path(local_path)
    if not rel:
        return []

    roots_and_parts = []
    project = project_root or config.BASE_DIR
    media = media_root or config.WEBCHAT_MEDIA_ROOT
    roots_and_parts.append((project, rel))

    suffix = _media_suffix(rel)
    if suffix:
        roots_and_parts.append((media, suffix))

    out: List[str] = []
    seen = set()
    for root, part in roots_and_parts:
        candidate = _safe_join(root, part)
        if candidate and candidate not in seen:
            seen.add(candidate)
            out.append(candidate)
    return out


def resolve_media_path(
    local_path: str,
    media_root: Optional[str] = None,
    project_root: Optional[str] = None,
) -> str:
    candidates = media_path_candidates(local_path, media_root=media_root, project_root=project_root)
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return candidates[0] if candidates else ""
