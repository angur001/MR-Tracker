"""Load and save user configuration."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

CONFIG_DIR = Path.home() / ".git_tray_app"
CONFIG_PATH = CONFIG_DIR / "config.json"
REVIEWER_STATE_PATH = CONFIG_DIR / "reviewer_state.json"
DEFAULT_POLL_INTERVAL = 60


def parse_project_path(repo_url: str) -> str:
    """Extract namespace/project from a GitLab web or SSH repo URL."""
    raw = repo_url.strip()
    if not raw:
        raise ValueError("Repository URL is empty")

    if raw.startswith("git@"):
        _, path_part = raw.split(":", 1)
        path = path_part
    else:
        parsed = urlparse(raw)
        path = parsed.path.lstrip("/")

    if path.endswith(".git"):
        path = path[:-4]

    if not path:
        raise ValueError("Could not parse project path from repository URL")

    return path


@dataclass
class RepoEntry:
    url: str
    watch_reviews: bool = False


@dataclass
class AppConfig:
    gitlab_url: str = "https://gitlab.com"
    access_token: str = ""
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL
    repos: list[RepoEntry] = field(default_factory=list)

    def is_configured(self) -> bool:
        return bool(
            self.gitlab_url.strip()
            and self.access_token.strip()
            and len(self.repos) > 0
        )

    def api_base_url(self) -> str:
        return self.gitlab_url.strip().rstrip("/")

    def watched_repos(self) -> list[RepoEntry]:
        return [repo for repo in self.repos if repo.watch_reviews]


def _parse_repo_entry(item: object) -> RepoEntry | None:
    if isinstance(item, str):
        url = item.strip()
        if not url:
            return None
        return RepoEntry(url=url, watch_reviews=True)
    if isinstance(item, dict):
        url = str(item.get("url", "")).strip()
        if not url:
            return None
        return RepoEntry(
            url=url,
            watch_reviews=bool(item.get("watch_reviews", False)),
        )
    return None


def load_config() -> AppConfig:
    if not CONFIG_PATH.exists():
        return AppConfig()

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return AppConfig()

    repos: list[RepoEntry] = []
    for item in data.get("repos", []):
        entry = _parse_repo_entry(item)
        if entry:
            repos.append(entry)

    if not repos and data.get("repo_url"):
        legacy = data.get("repo_url", "").strip()
        if legacy:
            repos.append(RepoEntry(url=legacy, watch_reviews=True))

    deduped: dict[str, RepoEntry] = {}
    for entry in repos:
        deduped[entry.url] = entry
    repos = list(deduped.values())

    return AppConfig(
        gitlab_url=data.get("gitlab_url", "https://gitlab.com"),
        access_token=data.get("access_token", ""),
        poll_interval_seconds=int(
            data.get("poll_interval_seconds", DEFAULT_POLL_INTERVAL)
        ),
        repos=repos,
    )


def save_config(config: AppConfig) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(asdict(config), indent=2),
        encoding="utf-8",
    )


def load_reviewer_state() -> set[str]:
    if not REVIEWER_STATE_PATH.exists():
        return set()
    try:
        data = json.loads(REVIEWER_STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    return set(data.get("assignments", []))


def save_reviewer_state(assignments: set[str]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    REVIEWER_STATE_PATH.write_text(
        json.dumps({"assignments": sorted(assignments)}, indent=2),
        encoding="utf-8",
    )
