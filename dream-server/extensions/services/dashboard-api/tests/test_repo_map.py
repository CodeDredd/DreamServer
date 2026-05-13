"""Tests for the repo→Vikunja project map router."""

import json

import pytest


@pytest.fixture()
def repo_map_store(tmp_path, monkeypatch):
    """Point the router at an isolated JSON store under tmp_path."""
    store = tmp_path / "config" / "repo-project-map.json"
    import routers.repo_map as repo_map_module
    monkeypatch.setattr(repo_map_module, "_STORE_PATH", store)
    return store


def test_get_empty_returns_default_skeleton(test_client, repo_map_store):
    res = test_client.get("/api/repo-map", headers=test_client.auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["version"] == 1
    assert body["mappings"] == []
    assert "default_project_id" in body


def test_put_then_get_round_trip(test_client, repo_map_store):
    payload = {
        "default_project_id": 7,
        "mappings": [
            {"repo": "CodeDredd/DreamServer", "project_id": 1, "label": "Dream Server"},
            {"repo": "CodeDredd/openclaw", "project_id": 2},
        ],
    }
    res = test_client.put("/api/repo-map", json=payload, headers=test_client.auth_headers)
    assert res.status_code == 200, res.text

    body = res.json()
    assert body["default_project_id"] == 7
    repos = [m["repo"] for m in body["mappings"]]
    # Lowercased + alpha-sorted
    assert repos == ["codedredd/dreamserver", "codedredd/openclaw"]
    assert all("updated_at" in m for m in body["mappings"])

    # Persisted to disk
    on_disk = json.loads(repo_map_store.read_text())
    assert on_disk["default_project_id"] == 7
    assert len(on_disk["mappings"]) == 2


def test_post_upsert_replaces_existing(test_client, repo_map_store):
    test_client.put(
        "/api/repo-map",
        json={"default_project_id": 1, "mappings": [{"repo": "a/b", "project_id": 1}]},
        headers=test_client.auth_headers,
    )
    res = test_client.post(
        "/api/repo-map",
        json={"repo": "A/B", "project_id": 99, "label": "renamed"},
        headers=test_client.auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["project_id"] == 99

    listing = test_client.get("/api/repo-map", headers=test_client.auth_headers).json()
    assert len(listing["mappings"]) == 1
    assert listing["mappings"][0]["project_id"] == 99
    assert listing["mappings"][0]["label"] == "renamed"


def test_delete_removes_mapping(test_client, repo_map_store):
    test_client.put(
        "/api/repo-map",
        json={"default_project_id": 1, "mappings": [{"repo": "a/b", "project_id": 5}]},
        headers=test_client.auth_headers,
    )
    res = test_client.delete("/api/repo-map/a/b", headers=test_client.auth_headers)
    assert res.status_code == 200
    listing = test_client.get("/api/repo-map", headers=test_client.auth_headers).json()
    assert listing["mappings"] == []


def test_delete_missing_returns_404(test_client, repo_map_store):
    res = test_client.delete("/api/repo-map/no/such", headers=test_client.auth_headers)
    assert res.status_code == 404


def test_lookup_returns_explicit_mapping_case_insensitive(test_client, repo_map_store):
    test_client.put(
        "/api/repo-map",
        json={
            "default_project_id": 1,
            "mappings": [{"repo": "CodeDredd/DreamServer", "project_id": 42}],
        },
        headers=test_client.auth_headers,
    )
    res = test_client.get(
        "/api/repo-map/lookup",
        params={"repo": "codedredd/dreamserver"},
        headers=test_client.auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["project_id"] == 42
    assert body["source"] == "mapping"
    assert body["matched"] is True


def test_lookup_falls_back_to_default(test_client, repo_map_store):
    test_client.put(
        "/api/repo-map",
        json={"default_project_id": 9, "mappings": []},
        headers=test_client.auth_headers,
    )
    res = test_client.get(
        "/api/repo-map/lookup",
        params={"repo": "unknown/repo"},
        headers=test_client.auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["project_id"] == 9
    assert body["source"] == "default"
    assert body["matched"] is False


def test_lookup_404_when_no_mapping_and_no_default(test_client, repo_map_store):
    test_client.put(
        "/api/repo-map",
        json={"default_project_id": None, "mappings": []},
        headers=test_client.auth_headers,
    )
    res = test_client.get(
        "/api/repo-map/lookup",
        params={"repo": "unknown/repo"},
        headers=test_client.auth_headers,
    )
    assert res.status_code == 404


def test_invalid_repo_format_rejected(test_client, repo_map_store):
    res = test_client.post(
        "/api/repo-map",
        json={"repo": "not-a-valid-repo", "project_id": 1},
        headers=test_client.auth_headers,
    )
    assert res.status_code == 422


def test_unauthenticated_requests_rejected(test_client, repo_map_store):
    assert test_client.get("/api/repo-map").status_code == 401
    assert test_client.get("/api/repo-map/lookup", params={"repo": "a/b"}).status_code == 401

