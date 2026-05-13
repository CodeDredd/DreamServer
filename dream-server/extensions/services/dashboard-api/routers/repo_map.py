"""Repo → Vikunja project mapping.

Lets the dashboard maintain a small JSON map of GitHub repository
``full_name`` (``owner/repo``) → Vikunja project id, replacing the
previously hard-coded ``REPO_TO_PROJECT`` constant inside the n8n
``GitHub Issue → Vikunja Task`` workflow.

Storage:
    ``${DREAM_DATA_DIR}/config/repo-project-map.json``

Endpoints:
    GET    /api/repo-map                       → full map (auth)
    PUT    /api/repo-map                       → replace map (auth)
    POST   /api/repo-map                       → upsert one entry (auth)
    DELETE /api/repo-map/{repo:path}           → remove one entry (auth)
    GET    /api/repo-map/lookup?repo=<name>    → {project_id, source}
                                                 used by n8n (auth)

Per Dream Server design philosophy: narrow exception handling at the
I/O boundary only. JSON parse / file read errors raise HTTP 500 with
context — they are signal, not noise.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from config import DATA_DIR
from security import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["repo-map"])

# Atomic write lock — single-process FastAPI, but two concurrent PUTs
# could otherwise truncate each other.
_WRITE_LOCK = asyncio.Lock()

_STORE_PATH = Path(DATA_DIR) / "config" / "repo-project-map.json"
_REPO_RE = __import__("re").compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


# --- Schema ---------------------------------------------------------

class Mapping(BaseModel):
    repo: str = Field(..., description="GitHub full_name, e.g. 'CodeDredd/DreamServer'")
    project_id: int = Field(..., ge=1)
    label: str | None = None
    updated_at: str | None = None

    @field_validator("repo")
    @classmethod
    def _valid_repo(cls, v: str) -> str:
        v = v.strip()
        if not _REPO_RE.match(v):
            raise ValueError("repo must look like 'owner/name'")
        return v.lower()


class RepoMap(BaseModel):
    version: int = 1
    default_project_id: int | None = None
    mappings: list[Mapping] = Field(default_factory=list)


# --- Disk I/O -------------------------------------------------------

def _empty_map() -> dict[str, Any]:
    env_default = os.environ.get("VIKUNJA_DEFAULT_PROJECT_ID", "").strip()
    default_id = int(env_default) if env_default.isdigit() else None
    return {"version": 1, "default_project_id": default_id, "mappings": []}


def _read_store() -> dict[str, Any]:
    if not _STORE_PATH.exists():
        return _empty_map()
    raw = _STORE_PATH.read_text(encoding="utf-8")
    if not raw.strip():
        return _empty_map()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail=f"{_STORE_PATH} is not a JSON object")
    data.setdefault("version", 1)
    data.setdefault("default_project_id", _empty_map()["default_project_id"])
    mappings = data.get("mappings") or []
    if not isinstance(mappings, list):
        raise HTTPException(status_code=500, detail="repo-project-map.json: 'mappings' must be a list")
    data["mappings"] = mappings
    return data


def _write_store(data: dict[str, Any]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STORE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    os.replace(tmp, _STORE_PATH)


def _normalize_mappings(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate, lowercase repo keys, dedupe (last write wins)."""
    by_repo: dict[str, dict[str, Any]] = {}
    for raw in items:
        m = Mapping.model_validate(raw)
        entry = m.model_dump(exclude_none=True)
        entry["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        by_repo[entry["repo"]] = entry
    return sorted(by_repo.values(), key=lambda e: e["repo"])


# --- Endpoints ------------------------------------------------------

@router.get("/api/repo-map")
async def get_repo_map(api_key: str = Depends(verify_api_key)):
    """Return the full map (default + mappings)."""
    return await asyncio.to_thread(_read_store)


@router.put("/api/repo-map")
async def replace_repo_map(
    payload: dict[str, Any] = Body(...),
    api_key: str = Depends(verify_api_key),
):
    """Replace the map wholesale.

    Body: ``{"default_project_id": <int|null>, "mappings": [{repo, project_id, label?}, ...]}``
    """
    raw_default = payload.get("default_project_id")
    if raw_default is not None and (not isinstance(raw_default, int) or raw_default < 1):
        raise HTTPException(status_code=422, detail="default_project_id must be a positive integer or null")

    raw_mappings = payload.get("mappings", [])
    if not isinstance(raw_mappings, list):
        raise HTTPException(status_code=422, detail="mappings must be a list")

    try:
        normalized = _normalize_mappings(raw_mappings)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    data = {"version": 1, "default_project_id": raw_default, "mappings": normalized}
    async with _WRITE_LOCK:
        await asyncio.to_thread(_write_store, data)
    return data


@router.post("/api/repo-map")
async def upsert_mapping(
    payload: dict[str, Any] = Body(...),
    api_key: str = Depends(verify_api_key),
):
    """Insert or update a single mapping."""
    try:
        m = Mapping.model_validate(payload)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    entry = m.model_dump(exclude_none=True)
    entry["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    async with _WRITE_LOCK:
        data = await asyncio.to_thread(_read_store)
        others = [e for e in data["mappings"] if e.get("repo", "").lower() != entry["repo"]]
        data["mappings"] = sorted([*others, entry], key=lambda e: e["repo"])
        await asyncio.to_thread(_write_store, data)
    return entry


@router.delete("/api/repo-map/{repo:path}")
async def delete_mapping(repo: str, api_key: str = Depends(verify_api_key)):
    """Remove a mapping (404 if it didn't exist)."""
    needle = repo.strip().lower()
    if not _REPO_RE.match(needle):
        raise HTTPException(status_code=422, detail="repo must look like 'owner/name'")

    async with _WRITE_LOCK:
        data = await asyncio.to_thread(_read_store)
        before = len(data["mappings"])
        data["mappings"] = [e for e in data["mappings"] if e.get("repo", "").lower() != needle]
        if len(data["mappings"]) == before:
            raise HTTPException(status_code=404, detail=f"No mapping for '{repo}'")
        await asyncio.to_thread(_write_store, data)
    return {"deleted": needle}


@router.get("/api/repo-map/lookup")
async def lookup(repo: str, api_key: str = Depends(verify_api_key)):
    """Resolve a repo to a Vikunja project id.

    Used by the n8n ``GitHub Issue → Vikunja Task`` workflow. Returns the
    explicit mapping when present, otherwise ``default_project_id``, otherwise
    HTTP 404 so the workflow can surface a clear error.
    """
    needle = (repo or "").strip().lower()
    if not _REPO_RE.match(needle):
        raise HTTPException(status_code=422, detail="repo must look like 'owner/name'")

    data = await asyncio.to_thread(_read_store)
    for entry in data["mappings"]:
        if entry.get("repo", "").lower() == needle:
            return {
                "repo": needle,
                "project_id": int(entry["project_id"]),
                "source": "mapping",
                "matched": True,
                "label": entry.get("label"),
            }

    default_id = data.get("default_project_id")
    if default_id:
        return {
            "repo": needle,
            "project_id": int(default_id),
            "source": "default",
            "matched": False,
            "label": None,
        }

    raise HTTPException(
        status_code=404,
        detail=f"No mapping for '{repo}' and no default_project_id configured",
    )

