# AI IT Support Agent

An **AI worker** completes IT-style tasks by using a **web admin console** like a human: it reads a natural-language request, plans steps with **OpenAI**, then **Browser Use Cloud** drives a real browser against your **Flask** app. Data is stored in **Neon Postgres**. The agent does **not** call your Flask routes from Python to “cheat”—it only interacts through the UI.

---

## Table of contents

1. [User flow](#user-flow)
2. [High-level design (HLD)](#high-level-design-hld)
3. [Low-level design (LLD)](#low-level-design-lld)
4. [Repository layout](#repository-layout)
5. [Why `ADMIN_BASE_URL` must be public](#why-admin_base_url-must-be-public)
6. [Setup and run](#setup-and-run)
7. [Testing](#testing)
8. [Official documentation links](#official-documentation-links)

---

## User flow

Two ways to use the system: **manual** (human in the browser) or **automated** (CLI agent).

```mermaid
flowchart TD
    subgraph Manual["Human IT admin — local browser"]
        M1[Open http://127.0.0.1:5000] --> M2[Dashboard: list / search users]
        M2 --> M3{Action?}
        M3 -->|Create| M4[Create User form → submit]
        M3 -->|Edit| M5[Click email → User detail]
        M5 --> M6[Reset password if needed]
        M4 --> M2
        M6 --> M2
    end

    subgraph Auto["AI agent — CLI"]
        A1[Run python -m agent with NL request] --> A2[OpenAI: plan JSON steps + entities]
        A2 --> A3[Build rich task for Browser Use Cloud]
        A3 --> A4[Remote browser opens ADMIN_BASE_URL]
        A4 --> A5[Click / type like a human on Flask UI]
        A5 --> A6[Flask writes to Neon]
        A6 --> A7[Terminal: live steps + final summary]
    end
```

**Typical automated request examples**

- Create user: `python -m agent "Create user jane@company.com with name Jane Doe and role user"`
- Reset password: `python -m agent "Reset password for jane@company.com"`
- Optional flags: `--open-live` (open live browser view), `--recording` (session video when Cloud provides URLs)

### Example: IT Support threads (Teams-style)

Illustrative chat snippets similar to **Microsoft Teams** IT channels. The automated responder is labeled **Agent** (an app/bot posting ticket updates).

---

**User** — *Just now*  
My 2FA authenticator got wiped when I reset my phone. Locked out of everything.  
*1 reply*

**Agent · APP** — *Just now*  
Identity verified. 2FA reset and new backup codes sent to your recovery email. Re-enroll your authenticator app when ready — you're back in.  
*Ticket resolved*

---

**User** — *Just now*  
My laptop keeps freezing during Zoom calls. It's happened 3 times today.  
*1 reply*

**Agent · APP** — *Just now*  
Done! A Figma Professional seat has been provisioned to sofia@company.com. Check your inbox for the activation link.  
*Ticket resolved*

---

**User** — *Just now*  
We’re running out of space on the marketing shared drive — can we expand it?  
*1 reply*

**Agent · APP** — *Just now*  
Storage expanded from 500GB to 1TB for the marketing shared drive. Current usage is now at 48%. Let me know if you need a usage report.  
*Ticket resolved*

---

## High-level design (HLD)

**System context:** the operator runs a command on their machine; external services (OpenAI, Browser Use, Neon) and a tunneled Flask app cooperate to complete the task.

```mermaid
flowchart LR
    subgraph Operator["Your machine"]
        CLI[python -m agent]
    end

    subgraph External["External services"]
        OAI[OpenAI API\nPlanner]
        BUC[Browser Use Cloud\nRemote browser + agent]
        Neon[(Neon Postgres)]
    end

    subgraph Hosted["Public URL required"]
        Tunnel[ngrok / tunnel]
        Flask[Flask admin app]
    end

    CLI --> OAI
    CLI --> BUC
    BUC --> Tunnel
    Tunnel --> Flask
    Flask --> Neon
```

**Logical pipeline** (what happens in one agent run):

```mermaid
sequenceDiagram
    participant U as Operator
    participant CLI as Agent CLI
    participant P as OpenAI Planner
    participant B as Browser Use Cloud
    participant F as Flask UI
    participant D as Neon DB

    U->>CLI: Natural language request
    CLI->>P: Plan task (JSON)
    P-->>CLI: entities + steps[]
    CLI->>B: Session + full task text
    loop Remote browser
        B->>F: HTTP GET/POST (real UI)
        F->>D: SQL
        D-->>F: Rows updated
        F-->>B: HTML responses
    end
    B-->>CLI: Streamed steps + final output
    CLI-->>U: Logs + result text
```

---

## Low-level design (LLD)

### Agent process (Python package `agent/`)

```mermaid
flowchart TB
    subgraph Entry["Entry"]
        MAIN[agent/__main__.py\nargparse, load_dotenv]
    end

    subgraph Planning["Planning"]
        PL[planner.py\nplan_task → OpenAI chat\nJSON: entities, steps]
    end

    subgraph Execution["Execution"]
        EX[executor.py\nbuild_browser_use_task\nSessionStream + live_url]
    end

    MAIN --> PL
    MAIN --> EX
    PL --> EX
```

| Module | Responsibility |
|--------|----------------|
| `agent/__main__.py` | Parses CLI (`request`, `--recording`, `--skills`, `--open-live`), calls planner then executor. |
| `agent/planner.py` | `SYSTEM_PROMPT` + OpenAI JSON output: `entities` (email, name, role, …) and `steps` (`goto`, `click`, `fill`, `select`). |
| `agent/executor.py` | Merges plan into one **Browser Use task** string; optional **reset-password autonomy** block; `sessions.create` + `SessionStream` for live logs; polls `live_url`. |

### Flask application (`app/`)

```mermaid
flowchart LR
    subgraph FlaskApp["Flask app"]
        W[wsgi.py\ncreate_app]
        INIT[app/__init__.py\nFlask factory + init-db CLI]
        DB[db.py\npsycopg + get_conn]
        R[routes.py\nBlueprint main]
        T[templates/*.html]
    end

    W --> INIT
    INIT --> R
    R --> DB
    R --> T
```

### HTTP routes and pages

```mermaid
flowchart TB
    subgraph Routes["routes.py"]
        D["GET /\nDashboard + ?q= search"]
        C["GET|POST /users/new\nCreate user"]
        U["GET /users/id\nUser detail"]
        RP["POST /users/id/reset-password\nNew random password"]
    end

    D --> Neon[(users table)]
    C --> Neon
    U --> Neon
    RP --> Neon
```

### Database (Neon)

```mermaid
erDiagram
    users {
        int id PK
        string email UK
        string name
        string role
        string password
    }
```

**Initialization:** `flask --app wsgi init-db` runs `CREATE TABLE IF NOT EXISTS users (...)`.

### Data flow: who writes to the database?

Only **Flask** runs SQL when forms are submitted from the browser. The **agent CLI never** uses `psycopg` to mutate users for task completion—the Cloud browser submits the same forms a human would.

---

## Repository layout

```
tru/
├── wsgi.py                 # Flask entry: app = create_app()
├── requirements.txt
├── .env.example
├── app/
│   ├── __init__.py         # create_app(), flask init-db
│   ├── db.py               # Neon connection
│   ├── routes.py           # Blueprint + routes
│   └── templates/          # Jinja2 UI
└── agent/
    ├── __main__.py         # CLI
    ├── planner.py          # OpenAI → JSON plan
    └── executor.py         # Browser Use Cloud
```

---

## Why `ADMIN_BASE_URL` must be public

Browser Use runs the browser on **their** infrastructure. It cannot reach `http://127.0.0.1:5000` on your laptop. Use **ngrok** (or similar), set `ADMIN_BASE_URL` to the **HTTPS** forwarding URL, and keep Flask on port 5000 locally.

**Security:** This demo has **no authentication** on the admin UI. Do not expose real data.

---

## Setup and run

### Prerequisites

- Python 3.11+
- [Neon](https://neon.tech/) database
- [OpenAI](https://platform.openai.com/) API key
- [Browser Use](https://cloud.browser-use.com/) API key (`bu_…`)

### Commands (PowerShell)

```powershell
cd E:\tru
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# Edit .env: DATABASE_URL, OPENAI_*, BROWSER_USE_API_KEY, SECRET_KEY, later ADMIN_BASE_URL
flask --app wsgi init-db
flask --app wsgi run --host 127.0.0.1 --port 5000
```

**Tunnel (for the agent):**

```powershell
ngrok http 5000
```

Set `ADMIN_BASE_URL=https://YOUR-NGROK-HOST` in `.env`.

**Run the agent:**

```powershell
cd E:\tru
.\.venv\Scripts\Activate.ps1
python -m agent "Create user demo@company.com with name Demo User and role user"
python -m agent "Reset password for demo@company.com"
python -m agent "Reset password for demo@company.com" --open-live
```

**Watch live:** CLI prints a **LIVE BROWSER** URL and streamed `›` step lines; see [Browser Use FAQ — live URL](https://docs.browser-use.com/cloud/faq).

---

## Testing

### A. Admin panel only (no Cloud)

1. `flask --app wsgi init-db` and run Flask.
2. Open `http://127.0.0.1:5000`.
3. Test dashboard, search, create user, user detail, reset password.

### B. Full stack

1. Valid `.env`, Flask + ngrok, `ADMIN_BASE_URL` public.
2. Run agent create + reset commands; verify rows in Neon or UI.

### C. Recording

```powershell
python -m agent "Reset password for demo@company.com" --recording
```

---

## Official documentation links

- [Flask](https://flask.palletsprojects.com/)
- [Neon — Connect from any app](https://neon.tech/docs/connect/connect-from-any-app)
- [psycopg 3](https://www.psycopg.org/psycopg3/docs/)
- [Browser Use Cloud — Quick start](https://docs.browser-use.com/cloud/quickstart)
- [Browser Use — Agent (v3)](https://docs.browser-use.com/cloud/agent/quickstart)
- [OpenAI API](https://platform.openai.com/docs/overview)
