"""
Execute IT tasks via Browser Use Cloud (managed browser agent).

Docs: https://docs.browser-use.com/cloud/quickstart
API v3 uses env BROWSER_USE_API_KEY (keys start with bu_).

Note: The remote browser cannot reach http://127.0.0.1 on your machine.
Set ADMIN_BASE_URL to a URL that is reachable from the public internet
(e.g. ngrok, Cloudflare Tunnel, or a deployed Flask app).
"""

from __future__ import annotations

import json
import os
import threading
import time
import webbrowser
from typing import Any

from browser_use_sdk.v3 import BrowserUse
from browser_use_sdk.v3.helpers import SessionStream

from agent.planner import resolve_step_values


def _log(msg: str) -> None:
    print(f"[Agent] {msg}", flush=True)


def _steps_to_bullets(steps: list[dict[str, Any]], entities: dict[str, Any]) -> str:
    lines: list[str] = []
    for i, step in enumerate(steps):
        s = resolve_step_values(step, entities)
        lines.append(f"{i + 1}. {json.dumps(s, ensure_ascii=False)}")
    return "\n".join(lines)


def _is_password_reset_request(user_request: str, steps: list[dict[str, Any]]) -> bool:
    t = user_request.lower()
    if "reset" in t and any(x in t for x in ("password", "passwd", "pwd")):
        return True
    for step in steps:
        if step.get("op") == "click" and str(step.get("name", "")).lower() == "reset password":
            return True
    return False


def _autonomy_policy_for_reset(entities: dict[str, Any]) -> str:
    email = (entities.get("email") or "").strip() or "(target email from request)"
    local = email.split("@")[0] if "@" in email else email
    suggested_name = local[:1].upper() + local[1:] if local else "User"

    return f"""
## CRITICAL — Finish autonomously (do not ask for human confirmation)

- **Never** end with "please confirm", "should I create", or similar. Complete the full workflow in this session.
- If a native **confirm()** dialog appears (e.g. before reset), **accept / OK** it.
- **Password reset** for `{email}`:
  1. Open Dashboard, fill **Search by email** with `{email}`, click **Search**.
  2. **If** the user row / email link appears: click that link → on user detail click **Reset password** → read the green flash for the new password → **done**.
  3. **If** there is no matching user (empty table, "No matches", or no link for that email): click sidebar **Create User**. Fill **Email** = `{email}`, **Name** = `{suggested_name}` (or title-case the local-part of the email), **Role** = **user**, leave **Password (optional — random if empty)** blank, click **Create user**. Then **Dashboard** → search `{email}` → open user → **Reset password** → capture new password from the flash message.
- Final output must state that the password was reset and include the new password if the UI showed it.
""".strip()


def build_browser_use_task(user_request: str, entities: dict[str, Any], steps: list[dict[str, Any]]) -> str:
    base = os.environ.get("ADMIN_BASE_URL", "").rstrip("/")
    if not base:
        raise RuntimeError("ADMIN_BASE_URL is not set")

    ui_guide = """
## IT Admin UI (use only clicks and forms in the browser)

- **Dashboard** (path /): heading "Users". Nav links "Dashboard" and "Create User".
  - **Search by email** field + **Search** button. User emails in the table are links.
- **Create User** (path /users/new): fields **Email**, **Name**, **Role** (dropdown: user, admin, contractor),
  **Password (optional — random if empty)**. Submit button text: **Create user** (lowercase u).
- **User detail**: button **Reset password** (submits form; a new password appears in a green flash message).

Complete the user's request only through this website. Do not assume private APIs.
""".strip()

    plan_block = _steps_to_bullets(steps, entities)
    entities_block = json.dumps(entities, indent=2, ensure_ascii=False)
    reset_extra = ""
    if _is_password_reset_request(user_request, steps):
        reset_extra = "\n\n" + _autonomy_policy_for_reset(entities) + "\n"

    return f"""Open the IT admin panel at: {base}

{ui_guide}
{reset_extra}
## Original request
{user_request}

## Parsed entities (JSON)
{entities_block}

## Planned low-level steps (JSON ops — follow the real UI; adapt if the page differs)
{plan_block}

## What to do
1. Navigate to {base} first.
2. Execute the request using the admin panel UI. Use the planned steps as a guide but fix paths if needed.
3. When finished, summarize what you did and what you see on the page (e.g. user visible in list, password reset confirmation).
4. If the critical autonomy section above applies, follow it exactly — **do not stop early** when the user is missing; create them then reset.
"""


def _print_live_banner(url: str, *, open_browser: bool) -> None:
    _log("")
    _log("=" * 64)
    _log("LIVE BROWSER — open this URL to watch the remote session (video stream):")
    _log(url)
    _log("Tip: open it now in Chrome/Edge; keep this terminal open while it runs.")
    _log("=" * 64)
    _log("")
    if open_browser:
        try:
            webbrowser.open(url)
            _log("(Opened your default browser to the live view.)")
        except Exception as e:
            _log(f"(Could not auto-open browser: {e} — paste the URL manually.)")


def _resolve_live_url(client: BrowserUse, session_id: str, created) -> str | None:
    u = getattr(created, "live_url", None)
    if u:
        return u
    for _ in range(40):
        try:
            s = client.sessions.get(session_id)
            if s.live_url:
                return s.live_url
        except Exception:
            pass
        time.sleep(0.5)
    return None


def _spawn_late_live_url_watcher(
    client: BrowserUse,
    session_id: str,
    *,
    open_browser: bool,
    live_already: bool,
) -> None:
    if live_already:
        return

    def watch() -> None:
        for _ in range(90):
            try:
                s = client.sessions.get(session_id)
                if s.live_url:
                    _log("")
                    _log("LIVE BROWSER URL (now available — open this link):")
                    _log(s.live_url)
                    _log("")
                    if open_browser:
                        try:
                            webbrowser.open(s.live_url)
                        except Exception:
                            pass
                    return
            except Exception:
                pass
            time.sleep(1)

    threading.Thread(target=watch, daemon=True).start()


def run_browser_use_task(
    user_request: str,
    entities: dict[str, Any],
    steps: list[dict[str, Any]],
    *,
    enable_recording: bool = False,
    skills: bool = False,
    open_live_browser: bool = False,
) -> Any:
    """
    Run a Cloud session with streamed step logs + live preview URL.
    """
    api_key = os.environ.get("BROWSER_USE_API_KEY")
    if not api_key:
        raise RuntimeError("BROWSER_USE_API_KEY is not set (get a key at https://cloud.browser-use.com/settings)")

    auto_open = open_live_browser or os.environ.get("AGENT_AUTO_OPEN_LIVE", "").lower() in ("1", "true", "yes")

    task = build_browser_use_task(user_request, entities, steps)
    model = os.environ.get("BROWSER_USE_MODEL")

    kwargs: dict[str, Any] = {
        "enable_recording": enable_recording,
        "skills": skills,
    }
    if model:
        kwargs["model"] = model

    _log("Starting Browser Use Cloud session…")
    with BrowserUse(api_key=api_key) as client:
        created = client.sessions.create(task, **kwargs)
        sid = str(created.id)

        _log(f"Session id: {sid}")
        _log("Dashboard: https://cloud.browser-use.com (find this session if links below fail)")

        live = _resolve_live_url(client, sid, created)
        if live:
            _print_live_banner(live, open_browser=auto_open)
        else:
            _log("Live URL not returned yet — watching in background; you still get step-by-step logs below.")
        _spawn_late_live_url_watcher(client, sid, open_browser=auto_open, live_already=bool(live))

        _log("— Live activity (from Cloud; each line is a real browser/agent step) —")
        stream = SessionStream(created, client.sessions, None)
        try:
            for msg in stream:
                parts: list[str] = []
                if (msg.summary or "").strip():
                    parts.append(msg.summary.strip())
                elif (msg.type or "").strip():
                    parts.append(f"[{msg.type}]")
                    if (msg.data or "").strip():
                        parts.append((msg.data.strip()[:160] + "…") if len(msg.data) > 160 else msg.data.strip())
                if parts:
                    _log("  › " + " ".join(parts))
                su = getattr(msg, "screenshot_url", None)
                if su:
                    _log(f"  · screenshot: {su}")
        finally:
            pass

        result = stream.result
        if result is None:
            raise RuntimeError("Browser Use stream ended without a result")

    if getattr(result.session, "recording_urls", None):
        _log(f"Recording URLs: {result.session.recording_urls}")

    _log("Browser Use task finished.")
    return result
