"""System tray application with GitLab MR polling."""

from __future__ import annotations

import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pystray
from PIL import Image, ImageDraw, ImageFont

from config import (
    AppConfig,
    load_config,
    load_reviewer_state,
    parse_project_path,
    save_reviewer_state,
)
from gitlab_client import (
    GitLabError,
    RepoResult,
    ReviewerAssignment,
    fetch_reviewer_assignments,
    get_current_user_id,
    poll_all_repos,
)

_SETTINGS_SCRIPT = Path(__file__).resolve().parent / "open_settings.py"
APP_ICON_PATH = Path(__file__).resolve().parent / "icon.png"

ICON_SIZE = 32
_BASE_ICON: Image.Image | None = None


@dataclass
class TrayState:
    connected: bool = False
    open_mr_count: int | None = None
    status_line: str = "Not configured"
    detail: str = ""
    repo_results: list[RepoResult] = field(default_factory=list)


class TrayApp:
    def __init__(self) -> None:
        self.config = load_config()
        self.state = TrayState()
        self._stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._icon: pystray.Icon | None = None
        self._previous_mr_counts: dict[str, int] = {}
        self._known_reviewer_assignments = load_reviewer_state()
        self._reviewer_baseline_done = bool(self._known_reviewer_assignments)
        self._gitlab_user_id: int | None = None
        self._settings_process: subprocess.Popen[bytes] | None = None
        self._settings_lock = threading.Lock()

    def run(self) -> None:
        self._icon = pystray.Icon(
            "git_tray_app",
            self._render_icon(),
            self._tooltip(),
            menu=self._build_menu(),
        )
        self._icon.run(setup=self._on_setup)

    def _build_menu(self) -> pystray.Menu:
        items: list[pystray.MenuItem | pystray.Menu.SEPARATOR] = [
            pystray.MenuItem(self._menu_status_text, self._noop, enabled=False),
        ]

        if self.state.repo_results:
            items.append(pystray.Menu.SEPARATOR)
            for result in self.state.repo_results:
                items.append(
                    pystray.MenuItem(
                        self._repo_menu_text(result),
                        self._noop,
                        enabled=False,
                    )
                )

        items.extend(
            [
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Refresh now", self._on_refresh),
                pystray.MenuItem("Settings…", self._on_settings),
                pystray.MenuItem("Exit", self._on_exit),
            ]
        )
        return pystray.Menu(*items)

    def _repo_menu_text(self, result: RepoResult):
        def text(_icon: pystray.Icon) -> str:
            if result.ok:
                label = "1 MR" if result.count == 1 else f"{result.count} MRs"
                return f"{result.project}: {label}"
            return f"{result.project}: {result.error}"

        return text

    def _on_setup(self, icon: pystray.Icon) -> None:
        icon.visible = True
        self._poll_once()
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="gitlab-poll",
            daemon=True,
        )
        self._poll_thread.start()

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            interval = max(15, self.config.poll_interval_seconds)
            if self._stop_event.wait(interval):
                break
            self._poll_once()

    def _poll_once(self) -> None:
        if not self.config.is_configured():
            self._set_disconnected(
                "Not configured",
                "Open Settings to add repositories and a token.",
            )
            return

        try:
            results = poll_all_repos(self.config)
        except GitLabError as exc:
            self._set_disconnected("Disconnected", str(exc))
            return

        ok_results = [r for r in results if r.ok]
        failed = [r for r in results if not r.ok]

        if not ok_results:
            first_error = failed[0].error if failed else "Unknown error"
            self._set_disconnected("Disconnected", first_error, results)
            return

        total = sum(r.count for r in ok_results)
        if failed:
            status = f"{total} open MRs ({len(failed)} repo(s) failed)"
            detail = ", ".join(r.project for r in failed)
        else:
            status = "1 open MR" if total == 1 else f"{total} open MRs"
            detail = f"{len(ok_results)} repo(s)"

        self._notify_new_mrs(ok_results)
        self._check_reviewer_assignments()
        self._set_connected(total, status, detail, results)

    def _notify_new_mrs(self, ok_results: list[RepoResult]) -> None:
        if not self._icon:
            return

        configured = {repo.url for repo in self.config.repos}
        self._previous_mr_counts = {
            url: count
            for url, count in self._previous_mr_counts.items()
            if url in configured
        }

        for result in ok_results:
            previous = self._previous_mr_counts.get(result.repo_url)
            if previous is not None and result.count > previous:
                delta = result.count - previous
                self._show_mr_notification(result, delta)
            self._previous_mr_counts[result.repo_url] = result.count

    def _show_mr_notification(self, result: RepoResult, delta: int) -> None:
        if delta == 1:
            message = (
                f"{result.project} has a new open merge request "
                f"({result.count} total)."
            )
        else:
            message = (
                f"{result.project}: {delta} new open merge requests "
                f"({result.count} total)."
            )
        self._icon.notify(message, "Git Tray App")

    def _check_reviewer_assignments(self) -> None:
        if not self._icon or not self.config.watched_repos():
            return

        try:
            user_id = self._get_gitlab_user_id()
            assignments = fetch_reviewer_assignments(self.config, user_id)
        except (GitLabError, ValueError):
            return

        current_keys = {assignment.key for assignment in assignments}
        watched_projects = {
            parse_project_path(repo.url)
            for repo in self.config.watched_repos()
        }
        self._known_reviewer_assignments = {
            key
            for key in self._known_reviewer_assignments
            if key.split("#", 1)[0] in watched_projects
        }

        if self._reviewer_baseline_done:
            known = self._known_reviewer_assignments
            for assignment in assignments:
                if assignment.key not in known:
                    self._show_reviewer_notification(assignment)
        else:
            self._reviewer_baseline_done = True

        self._known_reviewer_assignments = current_keys
        save_reviewer_state(current_keys)

    def _get_gitlab_user_id(self) -> int:
        if self._gitlab_user_id is None:
            self._gitlab_user_id = get_current_user_id(self.config)
        return self._gitlab_user_id

    def _show_reviewer_notification(self, assignment: ReviewerAssignment) -> None:
        message = (
            f"You were assigned as reviewer on !{assignment.iid}: "
            f"{assignment.title}"
        )
        self._icon.notify(message, assignment.project)

    def _set_connected(
        self,
        count: int,
        status_line: str,
        detail: str,
        results: list[RepoResult],
    ) -> None:
        self.state = TrayState(
            connected=True,
            open_mr_count=count,
            status_line=status_line,
            detail=detail,
            repo_results=results,
        )
        self._update_tray()

    def _set_disconnected(
        self,
        status_line: str,
        detail: str,
        results: list[RepoResult] | None = None,
    ) -> None:
        self.state = TrayState(
            connected=False,
            open_mr_count=None,
            status_line=status_line,
            detail=detail,
            repo_results=results or [],
        )
        self._update_tray()

    def _update_tray(self) -> None:
        if not self._icon:
            return
        self._icon.icon = self._render_icon()
        self._icon.title = self._tooltip()
        self._icon.menu = self._build_menu()
        self._icon.update_menu()

    def _render_icon(self) -> Image.Image:
        image = _load_base_icon()

        if not self.state.connected:
            return _draw_badge(image, "!", bg="#c5221f")

        count = self.state.open_mr_count
        if count is None:
            return _draw_badge(image, "?", bg="#5f6368")

        text = "99+" if count > 99 else str(count)
        return _draw_badge(image, text, bg="#1a73e8")

    def _tooltip(self) -> str:
        if self.state.connected and self.state.open_mr_count is not None:
            return f"{self.state.status_line} — {self.state.detail}"
        if self.state.detail:
            return f"{self.state.status_line}: {self.state.detail}"
        return self.state.status_line

    def _menu_status_text(self, _icon: pystray.Icon) -> str:
        return self.state.status_line

    @staticmethod
    def _noop(_icon: pystray.Icon, _item: object) -> None:
        pass

    def _on_refresh(self, _icon: pystray.Icon, _item: object) -> None:
        threading.Thread(target=self._poll_once, name="gitlab-refresh", daemon=True).start()

    def _on_settings(self, _icon: pystray.Icon, _item: object) -> None:
        threading.Timer(0.05, self._run_settings_process).start()

    def _run_settings_process(self) -> None:
        with self._settings_lock:
            if self._settings_process and self._settings_process.poll() is None:
                return
            self._settings_process = subprocess.Popen(
                [sys.executable, str(_SETTINGS_SCRIPT)],
                cwd=str(_SETTINGS_SCRIPT.parent),
            )

        self._settings_process.wait()
        with self._settings_lock:
            self._settings_process = None

        if self._stop_event.is_set():
            return

        self.config = load_config()
        self._gitlab_user_id = None
        self._known_reviewer_assignments = load_reviewer_state()
        self._reviewer_baseline_done = bool(self._known_reviewer_assignments)
        self._poll_once()

    def _close_settings_process(self) -> None:
        with self._settings_lock:
            process = self._settings_process
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()

    def _on_exit(self, _icon: pystray.Icon, _item: object) -> None:
        self._stop_event.set()
        self._close_settings_process()
        if self._icon:
            self._icon.stop()

def _load_base_icon() -> Image.Image:
    global _BASE_ICON
    if _BASE_ICON is None:
        if APP_ICON_PATH.exists():
            _BASE_ICON = Image.open(APP_ICON_PATH).convert("RGBA")
            _BASE_ICON = _BASE_ICON.resize(
                (ICON_SIZE, ICON_SIZE),
                Image.Resampling.LANCZOS,
            )
        else:
            _BASE_ICON = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), "#1a73e8")
    return _BASE_ICON.copy()


def _draw_badge(image: Image.Image, text: str, bg: str, fg: str = "#ffffff") -> Image.Image:
    """Draw a small count/status badge on the bottom-right of the app icon."""
    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    badge_size = 14 if len(text) <= 2 else 16
    x0 = ICON_SIZE - badge_size
    y0 = ICON_SIZE - badge_size
    draw.ellipse((x0, y0, ICON_SIZE - 1, ICON_SIZE - 1), fill=bg)
    font = _load_font(8 if len(text) > 2 else 9)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    cx = x0 + badge_size / 2
    cy = y0 + badge_size / 2
    draw.text(
        (cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]),
        text,
        fill=fg,
        font=font,
    )
    return canvas


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("arial.ttf", "segoeui.ttf", "calibri.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()

