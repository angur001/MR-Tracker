"""Tkinter settings dialog."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from config import AppConfig, RepoEntry, parse_project_path, save_config


def _format_repo_line(entry: RepoEntry) -> str:
    flag = "★" if entry.watch_reviews else " "
    return f"[{flag}] {entry.url}"


def open_settings_dialog(
    config: AppConfig,
    on_saved: Callable[[AppConfig], None] | None = None,
) -> None:
    root = tk.Tk()
    root.title("Git Tray App — Settings")
    root.resizable(True, True)
    root.minsize(480, 460)

    frame = ttk.Frame(root, padding=12)
    frame.grid(row=0, column=0, sticky="nsew")
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)

    row = 0

    ttk.Label(frame, text="GitLab URL (instance root):").grid(
        row=row, column=0, sticky="w", pady=(0, 4)
    )
    row += 1
    gitlab_var = tk.StringVar(value=config.gitlab_url)
    ttk.Entry(frame, textvariable=gitlab_var, width=52).grid(
        row=row, column=0, sticky="ew", pady=(0, 8)
    )
    row += 1

    ttk.Label(frame, text="Personal access token:").grid(
        row=row, column=0, sticky="w", pady=(0, 4)
    )
    row += 1
    token_var = tk.StringVar(value=config.access_token)
    ttk.Entry(frame, textvariable=token_var, width=52, show="*").grid(
        row=row, column=0, sticky="ew", pady=(0, 12)
    )
    row += 1

    ttk.Label(frame, text="Repositories ([★] = notify when assigned as reviewer):").grid(
        row=row, column=0, sticky="w", pady=(0, 4)
    )
    row += 1

    repos_frame = ttk.Frame(frame)
    repos_frame.grid(row=row, column=0, sticky="nsew", pady=(0, 8))
    repos_frame.columnconfigure(0, weight=1)
    repos_frame.rowconfigure(0, weight=1)
    frame.rowconfigure(row, weight=1)
    row += 1

    repos_listbox = tk.Listbox(repos_frame, height=8, width=60)
    repos_listbox.grid(row=0, column=0, sticky="nsew")
    scrollbar = ttk.Scrollbar(repos_frame, orient="vertical", command=repos_listbox.yview)
    scrollbar.grid(row=0, column=1, sticky="ns")
    repos_listbox.configure(yscrollcommand=scrollbar.set)

    repo_entries: list[RepoEntry] = list(config.repos)

    def refresh_listbox() -> None:
        repos_listbox.delete(0, tk.END)
        for entry in repo_entries:
            repos_listbox.insert(tk.END, _format_repo_line(entry))

    refresh_listbox()

    add_frame = ttk.Frame(frame)
    add_frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
    add_frame.columnconfigure(0, weight=1)
    row += 1

    new_repo_var = tk.StringVar()
    watch_new_var = tk.BooleanVar(value=True)
    new_repo_entry = ttk.Entry(
        add_frame,
        textvariable=new_repo_var,
        width=52,
    )
    new_repo_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

    def selected_index() -> int | None:
        selection = repos_listbox.curselection()
        return int(selection[0]) if selection else None

    def add_repo() -> None:
        url = new_repo_var.get().strip()
        if not url:
            return
        try:
            parse_project_path(url)
        except ValueError as exc:
            messagebox.showerror("Invalid repository", str(exc), parent=root)
            return
        if any(entry.url == url for entry in repo_entries):
            messagebox.showinfo(
                "Already added",
                "This repository is already in the list.",
                parent=root,
            )
            return
        repo_entries.append(
            RepoEntry(url=url, watch_reviews=watch_new_var.get())
        )
        new_repo_var.set("")
        refresh_listbox()
        new_repo_entry.focus_set()

    def remove_selected() -> None:
        index = selected_index()
        if index is None:
            messagebox.showinfo(
                "Nothing selected",
                "Select a repository to remove.",
                parent=root,
            )
            return
        repo_entries.pop(index)
        refresh_listbox()

    def toggle_review_watch() -> None:
        index = selected_index()
        if index is None:
            messagebox.showinfo(
                "Nothing selected",
                "Select a repository to toggle review notifications.",
                parent=root,
            )
            return
        entry = repo_entries[index]
        repo_entries[index] = RepoEntry(
            url=entry.url,
            watch_reviews=not entry.watch_reviews,
        )
        refresh_listbox()
        repos_listbox.selection_set(index)

    repo_actions = ttk.Frame(frame)
    repo_actions.grid(row=row, column=0, sticky="w", pady=(0, 12))
    row += 1
    ttk.Button(add_frame, text="Add", command=add_repo).grid(row=0, column=1)
    ttk.Checkbutton(
        add_frame,
        text="Watch reviews",
        variable=watch_new_var,
    ).grid(row=0, column=2, padx=(8, 0))
    ttk.Button(repo_actions, text="Remove selected", command=remove_selected).grid(
        row=0, column=0, padx=(0, 8)
    )
    ttk.Button(
        repo_actions,
        text="Toggle review notifications (★)",
        command=toggle_review_watch,
    ).grid(row=0, column=1)

    ttk.Label(frame, text="Poll interval (seconds):").grid(
        row=row, column=0, sticky="w", pady=(0, 4)
    )
    row += 1
    interval_var = tk.StringVar(value=str(config.poll_interval_seconds))
    ttk.Entry(frame, textvariable=interval_var, width=12).grid(
        row=row, column=0, sticky="w", pady=(0, 12)
    )
    row += 1

    hint = ttk.Label(
        frame,
        text=(
            "Token needs read_api scope. Mark repos with ★ to get notified when "
            "you are assigned as a reviewer on an open merge request."
        ),
        wraplength=440,
    )
    hint.grid(row=row, column=0, sticky="w", pady=(0, 12))
    row += 1

    def on_save() -> None:
        try:
            interval = int(interval_var.get().strip())
            if interval < 15:
                raise ValueError("Poll interval must be at least 15 seconds")
        except ValueError as exc:
            messagebox.showerror("Invalid settings", str(exc), parent=root)
            return

        new_config = AppConfig(
            gitlab_url=gitlab_var.get().strip(),
            access_token=token_var.get().strip(),
            poll_interval_seconds=interval,
            repos=list(repo_entries),
        )

        if not new_config.gitlab_url or not new_config.access_token:
            messagebox.showerror(
                "Invalid settings",
                "GitLab URL and access token are required.",
                parent=root,
            )
            return

        if not new_config.repos:
            messagebox.showerror(
                "Invalid settings",
                "Add at least one repository.",
                parent=root,
            )
            return

        save_config(new_config)
        if on_saved:
            on_saved(new_config)
        root.destroy()

    buttons = ttk.Frame(frame)
    buttons.grid(row=row, column=0, sticky="e")
    ttk.Button(buttons, text="Cancel", command=root.destroy).grid(
        row=0, column=0, padx=(0, 8)
    )
    ttk.Button(buttons, text="Save", command=on_save).grid(row=0, column=1)

    new_repo_entry.bind("<Return>", lambda _event: add_repo())
    root.mainloop()
