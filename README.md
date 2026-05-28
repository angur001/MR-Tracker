# Git Tray App

Shows the number of **open merge requests** across one or more GitLab projects in the Windows system tray. Polls GitLab on a fixed interval and shows **Disconnected** when every repository fails or credentials are invalid.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
python main.py
```

On first run, right-click the tray icon → **Settings…** and configure:

| Field | Example |
|-------|---------|
| GitLab URL | `https://gitlab.com` |
| Personal access token | token with **read_api** scope |
| Repositories | add URLs; **★** = watch for reviewer assignments; use **Toggle review notifications** |
| Poll interval | seconds between checks (minimum 15) |

Settings are saved to `%USERPROFILE%\.git_tray_app\config.json`.

## Tray behavior

- **Blue icon with a number** — connected; number is total open MRs across all repos
- **Red icon with `!`** — disconnected (all repos failed, bad token, missing config, etc.)
- **Tray menu** lists each repository with its MR count (or error)
- Hover tooltip shows summary or error detail
- **Refresh now** forces an immediate check
- A **desktop notification** when a repo’s open MR count increases (not on first poll)
- A **desktop notification** when you are **assigned as reviewer** on an open MR in a ★-watched repo (not for MRs already assigned before you enabled watching)

## GitLab token

Create a personal access token in GitLab (**Preferences → Access tokens**) with the **read_api** scope.
