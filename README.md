# Durable AI Agent (P27) 🛡️⚡

A resilient, production-ready AI Agent architecture built with **LangGraph**, **FastAPI**, and **React + Vite**. It implements durable execution with human-in-the-loop (HITL) approval gates, crash survival across process restarts, TTL-bounded approval windows, and real multi-step tool execution.

---

## 🚀 Key Features

- **Durable Execution & State Persistence**: Built on LangGraph with `AsyncSqliteSaver` checkpointer. Every step, state transition, and interrupt is persisted to SQLite, surviving crashes and server restarts.
- **Human-in-the-Loop (HITL) Approval Gates**:
  - **Safe Tools** (e.g., `search_web`, `analyze_data`, `read_file`): Executed autonomously without interrupting the user.
  - **Consequential Tools** (e.g., `execute_code`, `modify_database`, `send_email`): Graph suspends via `interrupt()`, waiting for human review.
- **TTL-Bounded Approval Windows**: Enforces configurable Time-To-Live (TTL) deadlines on approval requests. Expired actions are automatically abandoned to prevent stale executions.
- **Background Sweeper & Crash Recovery**: A background worker continuously monitors active TTLs and sweeps expired runs. When restarting after downtime, expired runs are automatically reconciled.
- **Interactive Modern Web Dashboard**: React + Vite UI featuring real-time run inspection, step-by-step progress tracking, interactive approval cards with live countdown timers, and run history.
- **Comprehensive Test Suite**: Unit, integration, and durability tests covering crash-recovery simulations, TTL expirations, and real-world multi-step workflows.

---

## 🏗️ Architecture

```mermaid
flowchart TD
    User([User / Web UI]) -->|POST /agent/runs| API[FastAPI Server]
    API -->|Initialize Thread & State| LG[LangGraph Engine]
    
    subgraph Graph Execution
        Plan[Plan Node] -->|Generate Steps| Exec[Execute Node]
        Exec -->|Safe Tool| ExecSafe[Execute Safe Tool & Save Checkpoint]
        ExecSafe --> Exec
        Exec -->|Consequential Tool| Gate[Approval Gate Node]
        Gate -->|interrupt\(\)| Persist[(SQLite Checkpoints & TTL DB)]
        
        Persist -.->|Suspend Execution| Wait([Wait for Approval / Rejection / TTL Expiry])
        Wait -->|POST /approve or /reject| Gate
        Gate -->|Approved| ExecConseq[Execute Consequential Tool]
        ExecConseq --> Exec
        Gate -->|Rejected / Expired| Finalize[Finalize Node]
        Exec -->|All Steps Done| Finalize
    end

    Finalize --> End([Result / Completed State])
    
    subgraph Background Service
        Sweeper[TTL Sweeper Task] -->|Check Deadlines| Persist
        Sweeper -->|Expire Timeout Runs| LG
    end
```

---

## 🛠️ Tool Registry

| Tool | Type | Description | Approval Required |
| :--- | :--- | :--- | :---: |
| `search_web` | Safe | Live search using DuckDuckGo (`ddgs`) | ❌ No |
| `analyze_data` | Safe | Statistical, text, and JSON/CSV data analysis | ❌ No |
| `read_file` | Safe | Read local file contents (under 50 KB safety limit) | ❌ No |
| `execute_code` | Consequential | Execute Python code with captured stdout/stderr | ⚠️ **Yes** |
| `modify_database`| Consequential | Execute SQL queries on sandboxed SQLite database | ⚠️ **Yes** |
| `send_email` | Consequential | Send emails via SMTP (supports dry-run mode) | ⚠️ **Yes** |

---

## 📁 Project Structure

```text
├── agent/                  # Agent logic and LangGraph definition
│   ├── graph.py            # StateGraph definition, nodes, routing, interrupt handling
│   ├── llm.py              # LLM provider integration (Groq / Mock fallback)
│   └── tools.py            # Safe and consequential tool definitions & registry
├── api/                    # FastAPI web layer
│   ├── routes.py           # REST endpoints for runs, approvals, and status
│   └── schemas.py          # Pydantic request/response schemas
├── frontend/               # React + Vite Single Page Application
│   ├── src/
│   │   ├── components/     # UI components (ApprovalCard, ChatView, Sidebar, StepBubble)
│   │   ├── api.js          # API client for backend communication
│   │   ├── App.jsx         # Main application layout
│   │   └── index.css       # Design system and theme styling
│   └── package.json
├── tests/                  # Pytest test suites
│   ├── conftest.py         # Test fixtures and mock state
│   ├── test_api.py         # API endpoint test cases
│   ├── test_durability.py  # Durability, crash recovery, and TTL tests
│   └── test_real_world.py  # Real tool integration tests
├── ttl/                    # TTL management and background sweeper
│   ├── manager.py          # SQLite-backed TTL tracking and state machine
│   └── sweeper.py          # Background worker for TTL expiration
├── config.py               # Configuration loader via environment variables
├── main.py                 # FastAPI application entry point and lifespan
├── requirements.txt        # Python dependencies
└── .env.example            # Sample environment variables
```

---

## ⚙️ Prerequisites & Setup

### 1. Backend Setup

- **Python**: Version 3.10+ recommended.

```bash
# Create and activate a virtual environment
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
# source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Create a `.env` file by copying `.env.example`:

```bash
cp .env.example .env
```

Configure the following variables in `.env`:

```ini
# Groq API Key (If omitted, system falls back to mock LLM for testing)
GROQ_API_KEY=gsk_your_groq_api_key_here
LLM_MODEL=llama-3.3-70b-versatile

# Databases
CHECKPOINT_DB=checkpoints.db
TTL_DB=ttl.db
AGENT_SANDBOX_DB=agent_sandbox.db

# TTL Configuration
DEFAULT_TTL_SECONDS=3600
SWEEPER_INTERVAL_SECONDS=60

# Server
HOST=0.0.0.0
PORT=8000

# SMTP (Optional - runs in dry-run mode if omitted)
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=
```

### 3. Frontend Setup

- **Node.js**: Version 18+ recommended.

```bash
cd frontend
npm install
```

---

## 🚦 Running the Application

### 1. Start Backend API Server

From the project root:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be accessible at:
- **API Base**: `http://localhost:8000`
- **Interactive OpenAPI Docs**: `http://localhost:8000/docs`

### 2. Start Frontend Dev Server

From the `frontend/` directory:

```bash
npm run dev
```

Open `http://localhost:5173` in your browser.

---

## 📡 API Reference

### Runs

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/agent/runs` | Submit a new task for the agent to plan and execute. |
| `GET` | `/agent/runs` | List all tracked runs with optional `?status=` filter. |
| `GET` | `/agent/runs/{thread_id}` | Retrieve full status, plan, step outputs, and TTL info for a run. |

### Human Approval

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/agent/runs/{thread_id}/approve` | Approve the pending consequential action and resume execution. |
| `POST` | `/agent/runs/{thread_id}/reject` | Reject the pending action and terminate the run cleanly. |

### System

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | Health check endpoint. |

---

## 🧪 Running Tests

Run the test suite using `pytest`:

```bash
# Run all tests
pytest

# Run tests with output logging
pytest -v -s

# Run durability & crash-recovery tests
pytest tests/test_durability.py

# Run real tool execution tests
pytest tests/test_real_world.py
```

---

## 🔒 Security & Sandboxing

1. **Database Operations**: The `modify_database` tool strictly targets `agent_sandbox.db`, keeping the application's checkpoint and TTL databases safe from unintended modifications.
2. **File System Safety**: The `read_file` tool imposes a strict 50 KB file size limit to prevent memory exhaustion.
3. **Email Protection**: If SMTP credentials are not configured, `send_email` automatically runs in safe **dry-run** mode.
4. **Approval Expiration**: Abandoned approval gates automatically time out via TTL, preventing unexpected future execution.

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details if applicable.
