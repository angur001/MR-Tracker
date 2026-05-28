"""GitLab REST API helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests

from config import AppConfig, parse_project_path


class GitLabError(Exception):
    """GitLab API or connectivity failure."""


@dataclass
class RepoResult:
    repo_url: str
    project: str
    count: int = 0
    ok: bool = True
    error: str = ""


@dataclass
class ReviewerAssignment:
    project: str
    mr_id: int
    iid: int
    title: str
    web_url: str

    @property
    def key(self) -> str:
        return f"{self.project}#{self.mr_id}"


def _headers(access_token: str) -> dict[str, str]:
    return {"PRIVATE-TOKEN": access_token.strip()}


def _request_json(
    base_url: str,
    access_token: str,
    path: str,
    params: dict[str, Any] | None = None,
) -> Any:
    base = base_url.rstrip("/")
    try:
        response = requests.get(
            f"{base}/api/v4{path}",
            headers=_headers(access_token),
            params=params or {},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise GitLabError("Could not reach GitLab server") from exc

    if response.status_code == 401:
        raise GitLabError("Invalid access token")
    if response.status_code == 404:
        raise GitLabError("Project not found")
    if not response.ok:
        raise GitLabError(f"GitLab error ({response.status_code})")

    return response.json(), response.headers


def _paginate(
    base_url: str,
    access_token: str,
    path: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 1
    query = dict(params or {})
    query.setdefault("per_page", 100)

    while True:
        query["page"] = page
        batch, headers = _request_json(base_url, access_token, path, query)
        if not batch:
            break
        items.extend(batch)
        next_page = headers.get("X-Next-Page")
        if not next_page:
            break
        page = int(next_page)

    return items


def get_current_user_id(config: AppConfig) -> int:
    data, _ = _request_json(config.api_base_url(), config.access_token, "/user")
    user_id = data.get("id")
    if not user_id:
        raise GitLabError("Could not read GitLab user profile")
    return int(user_id)


def fetch_open_mr_count(base_url: str, access_token: str, project_path: str) -> int:
    """Return the number of open merge requests for a project."""
    encoded_project = quote(project_path, safe="")
    params = {"state": "opened", "per_page": 1}

    _, headers = _request_json(
        base_url,
        access_token,
        f"/projects/{encoded_project}/merge_requests",
        params,
    )

    total = headers.get("X-Total")
    if total is not None:
        return int(total)

    items = _paginate(
        base_url,
        access_token,
        f"/projects/{encoded_project}/merge_requests",
        {"state": "opened"},
    )
    return len(items)


def fetch_reviewer_assignments(
    config: AppConfig,
    user_id: int,
) -> list[ReviewerAssignment]:
    """Open MRs on watched repos where the user is assigned as reviewer."""
    watched = config.watched_repos()
    if not watched:
        return []

    base = config.api_base_url()
    token = config.access_token
    assignments: list[ReviewerAssignment] = []

    for repo in watched:
        project = parse_project_path(repo.url)
        encoded_project = quote(project, safe="")
        merge_requests = _paginate(
            base,
            token,
            f"/projects/{encoded_project}/merge_requests",
            {
                "state": "opened",
                "reviewer_id": user_id,
            },
        )
        for mr in merge_requests:
            assignments.append(
                ReviewerAssignment(
                    project=project,
                    mr_id=int(mr["id"]),
                    iid=int(mr["iid"]),
                    title=str(mr.get("title", "Merge request")),
                    web_url=str(mr.get("web_url", "")),
                )
            )

    return assignments


def poll_all_repos(config: AppConfig) -> list[RepoResult]:
    """Poll every configured repository."""
    if not config.is_configured():
        raise GitLabError("Not configured")

    base = config.api_base_url()
    token = config.access_token
    results: list[RepoResult] = []

    for repo in config.repos:
        try:
            project = parse_project_path(repo.url)
            count = fetch_open_mr_count(base, token, project)
            results.append(
                RepoResult(repo_url=repo.url, project=project, count=count, ok=True)
            )
        except ValueError as exc:
            results.append(
                RepoResult(
                    repo_url=repo.url,
                    project=repo.url,
                    ok=False,
                    error=str(exc),
                )
            )
        except GitLabError as exc:
            try:
                project = parse_project_path(repo.url)
            except ValueError:
                project = repo.url
            results.append(
                RepoResult(
                    repo_url=repo.url,
                    project=project,
                    ok=False,
                    error=str(exc),
                )
            )

    return results
