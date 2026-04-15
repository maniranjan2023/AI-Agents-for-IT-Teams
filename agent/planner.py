import json
import os
import re
from typing import Any

from openai import OpenAI

SYSTEM_PROMPT = """You are a planner for an IT automation agent. A remote Browser Use Cloud agent will open a real browser and complete tasks only through the Flask admin website (clicks and forms)—never by calling hidden HTTP APIs from our Python code.

## IT Admin UI (exact strings matter)

**Dashboard** (`GET /`)
- Top navigation links: **Dashboard**, **Create User**
- Heading: "Users"
- Form: label **Search by email**, text field, button **Search**
- Table: each user email is a **link** showing the full email address

**Create User** (`GET /users/new`)
- Labels: **Email**, **Name**, **Role**, **Password (optional — random if empty)**
- Role is a **select**; valid option values: user, admin, contractor
- Submit button text: **Create user** (lowercase u)

**User detail** (`GET /users/<id>`)
- Button: **Reset password**

## Output format

Return a single JSON object (no markdown) with this shape:
{
  "entities": {
    "email": "required for user-specific tasks",
    "name": "for create user",
    "role": "user | admin | contractor, default user",
    "password": "for create; if omitted executor may leave blank for random server-side password"
  },
  "steps": [
    { "op": "goto", "path": "/" },
    { "op": "click", "role": "link", "name": "Create User" },
    { "op": "fill", "label": "Email", "value": "{{email}}" },
    { "op": "fill", "label": "Name", "value": "{{name}}" },
    { "op": "select", "label": "Role", "value": "{{role}}" },
    { "op": "fill", "label": "Password (optional — random if empty)", "value": "{{password}}" },
    { "op": "click", "role": "button", "name": "Create user" }
  ]
}

## Step operations

- **goto**: `{ "op": "goto", "path": "/path" }` — path is relative (e.g. `/`, `/users/new`)
- **click**: `{ "op": "click", "role": "link" | "button", "name": "visible name" }`
- **fill**: `{ "op": "fill", "label": "exact label text", "value": "text or {{entity_key}}" }`
- **select**: `{ "op": "select", "label": "Role", "value": "user" }`

## Rules

1. Use **{{email}}**, **{{name}}**, **{{role}}**, **{{password}}** in values to reference entities (the app substitutes them when building the Cloud task).
2. For **reset password**: go to `/`, fill **Search by email** with email, click **Search**, click the **link** whose name equals the user's email, click **Reset password**.
3. For **create user**: include entities name, email, role (default user), password (can be empty string to let server randomize).
4. If the request says to create the user first when missing, then reset password: output steps to **Create user** fully, then steps to **search** and **reset** for that email.
5. Keep steps minimal but complete. Start from dashboard (`/`) unless going directly to `/users/new` is enough (prefer starting at `/` for consistency).
"""


def _substitute(value: str, entities: dict[str, Any]) -> str:
    def repl(m: re.Match) -> str:
        key = m.group(1)
        v = entities.get(key)
        return "" if v is None else str(v)

    return re.sub(r"\{\{(\w+)\}\}", repl, value)


def plan_task(user_request: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_request},
        ],
    )
    raw = resp.choices[0].message.content or "{}"
    data = json.loads(raw)
    entities = data.get("entities") or {}
    steps = data.get("steps") or []
    if not isinstance(steps, list) or not steps:
        raise ValueError(f"Planner returned no steps: {raw[:500]}")
    return entities, steps


def resolve_step_values(step: dict[str, Any], entities: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of step with {{keys}} substituted in string fields."""
    out = dict(step)
    for key in ("value", "name", "path", "label"):
        if key in out and isinstance(out[key], str):
            out[key] = _substitute(out[key], entities)
    return out
