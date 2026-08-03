import datetime as dt
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI
from pydantic import BaseModel, Field


CHATBOT_DIR = Path(__file__).resolve().parent
load_dotenv(CHATBOT_DIR / ".env")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
MEMORY_SERVICE_URL = os.getenv(
    "MEMORY_SERVICE_URL",
    "http://127.0.0.1:8000",
).rstrip("/")
MEMORY_SERVICE_PORTS = [
    int(port.strip())
    for port in os.getenv("MEMORY_SERVICE_PORTS", "8000").split(",")
    if port.strip().isdigit()
]
CHATBOT_TENANT_ID = os.getenv("CHATBOT_TENANT_ID", "tenant_a")
CHATBOT_USER_ID = os.getenv("CHATBOT_USER_ID", "user_demo")
CHATBOT_AGENT_ID = os.getenv("CHATBOT_AGENT_ID", "chatbot")
CHATBOT_AGENT_ROLE = os.getenv("CHATBOT_AGENT_ROLE", "assistant")
CHATBOT_WORKSPACE_ID = os.getenv("CHATBOT_WORKSPACE_ID", "chatbot_ws")
CHATBOT_DATA_DIR = Path(os.getenv("CHATBOT_DATA_DIR", CHATBOT_DIR / "data"))
CHATBOT_DB_PATH = CHATBOT_DATA_DIR / "chatbot.db"
_memory_service_url_cache: str | None = None


class AsciiJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("ascii")


app = FastAPI(
    title="Agent Memory Service 本地记忆聊天机器人",
    default_response_class=AsciiJSONResponse,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "X-Development-Tenant-ID",
        "X-Development-Principal-ID",
        "X-Trace-ID",
    ],
    expose_headers=["X-Trace-ID"],
    max_age=600,
)
def get_llm_client() -> AsyncOpenAI:
    if not DEEPSEEK_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="chatbot/.env 中缺少 DEEPSEEK_API_KEY",
        )
    return AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str = ""
    workspace_id: str = ""
    memory_limit: int = Field(default=5, ge=0, le=20)
    history_limit: int = Field(default=12, ge=0, le=50)
    save_memory: bool = True


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    memory_context: str
    memory_saved: bool
    memory_path: str | None = None
    memory_save_error: str | None = None
    history_count: int = 0
    memory_service_url: str = ""
    memory_metadata: dict[str, Any] = Field(default_factory=dict)


class SessionCreateRequest(BaseModel):
    title: str = ""


class SessionResponse(BaseModel):
    session_id: str
    title: str
    created_at: str
    updated_at: str


class MessageResponse(BaseModel):
    id: int
    session_id: str
    role: str
    content: str
    created_at: str


def _slug(value: str, fallback: str = "chat") -> str:
    value = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff_-]+", "-", value).strip("-_")
    return value[:60] or fallback


def _now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _connect_db() -> sqlite3.Connection:
    CHATBOT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CHATBOT_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            )
            """,
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_session_id_id "
            "ON messages(session_id, id)"
        )


init_db()


def ensure_session(session_id: str, first_message: str = "") -> str:
    session_id = session_id.strip() or str(uuid4())
    now = _now_iso()
    title = first_message.strip().replace("\n", " ")[:40] or "新会话"
    with _connect_db() as conn:
        existing = conn.execute(
            "SELECT id FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO sessions(id, title, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (session_id, title, now, now),
            )
        else:
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
    return session_id


def create_session(title: str = "") -> SessionResponse:
    session_id = str(uuid4())
    now = _now_iso()
    title = title.strip() or "新会话"
    with _connect_db() as conn:
        conn.execute(
            "INSERT INTO sessions(id, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (session_id, title, now, now),
        )
    return SessionResponse(
        session_id=session_id,
        title=title,
        created_at=now,
        updated_at=now,
    )


def list_sessions(limit: int = 50) -> list[SessionResponse]:
    with _connect_db() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at, updated_at FROM sessions "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        SessionResponse(
            session_id=row["id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


def add_message(session_id: str, role: str, content: str) -> None:
    now = _now_iso()
    with _connect_db() as conn:
        conn.execute(
            "INSERT INTO messages(session_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            (session_id, role, content, now),
        )
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (now, session_id),
        )


def get_messages(session_id: str, limit: int = 100) -> list[MessageResponse]:
    with _connect_db() as conn:
        rows = conn.execute(
            """
            SELECT id, session_id, role, content, created_at
            FROM messages
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    rows = list(reversed(rows))
    return [
        MessageResponse(
            id=int(row["id"]),
            session_id=row["session_id"],
            role=row["role"],
            content=row["content"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


def get_recent_llm_messages(session_id: str, limit: int) -> list[dict[str, str]]:
    if limit <= 0:
        return []
    return [
        {"role": msg.role, "content": msg.content}
        for msg in get_messages(session_id, limit)
    ]


async def _memory_service_health(base_url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
            response = await client.get(f"{base_url.rstrip('/')}/health")
            response.raise_for_status()
            data = response.json()
        return data.get("status") == "ok" or bool(data.get("ok"))
    except Exception:
        return False


async def discover_memory_service_url() -> str:
    global _memory_service_url_cache
    if _memory_service_url_cache and await _memory_service_health(
        _memory_service_url_cache
    ):
        return _memory_service_url_cache

    candidates = [MEMORY_SERVICE_URL]
    candidates.extend(f"http://127.0.0.1:{port}" for port in MEMORY_SERVICE_PORTS)
    candidates.extend(f"http://localhost:{port}" for port in MEMORY_SERVICE_PORTS)

    seen: set[str] = set()
    for candidate in candidates:
        candidate = candidate.rstrip("/")
        if candidate in seen:
            continue
        seen.add(candidate)
        if await _memory_service_health(candidate):
            _memory_service_url_cache = candidate
            return candidate

    _memory_service_url_cache = MEMORY_SERVICE_URL
    return MEMORY_SERVICE_URL


def _memory_service_headers(
    trace_id: str | None = None,
    *,
    tenant_id: str | None = None,
    principal_id: str | None = None,
) -> dict[str, str]:
    return {
        "X-Development-Tenant-ID": tenant_id or CHATBOT_TENANT_ID,
        "X-Development-Principal-ID": principal_id or CHATBOT_USER_ID,
        "X-Trace-ID": trace_id or f"trace_chatbot_{uuid4().hex}",
    }


async def _memory_service_post(
    path: str,
    payload: dict[str, Any],
    *,
    trace_id: str | None = None,
    tenant_id: str | None = None,
    principal_id: str | None = None,
) -> dict[str, Any]:
    base_url = await discover_memory_service_url()
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        response = await client.post(
            f"{base_url}{path}",
            json=payload,
            headers=_memory_service_headers(
                trace_id,
                tenant_id=tenant_id,
                principal_id=principal_id,
            ),
        )
        response.raise_for_status()
        return response.json()


def _format_memory_context(data: dict[str, Any]) -> str:
    package = data.get("context_package", {}) or {}
    grouped_items: list[tuple[str, dict[str, Any]]] = []
    for group_name in ("facts", "preferences", "constraints", "decisions", "progress"):
        for item in package.get(group_name, []) or []:
            grouped_items.append((group_name, item))

    lines: list[str] = []
    for group_name, item in grouped_items:
        memory_id = item.get("memory_id", "")
        memory_type = item.get("memory_type", group_name)
        confidence = float(item.get("confidence") or 0.0)
        matched_reason = item.get("matched_reason", "")
        lines.append(
            "========== "
            f"{group_name}/{memory_type} memory_id={memory_id} "
            f"confidence={confidence:.2f} reason={matched_reason}"
            " =========="
        )
        lines.append(str(item.get("content", "")))

    checkpoint = package.get("task_checkpoint")
    if checkpoint:
        lines.append("========== task_checkpoint ==========")
        resume_context = checkpoint.get("resume_context") or {}
        lines.append(json.dumps(resume_context, ensure_ascii=False))
    return "\n".join(lines)


async def search_memory(
    query: str,
    limit: int,
    session_id: str,
    *,
    workspace_id: str | None = None,
    tenant_id: str | None = None,
    principal_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    if limit <= 0:
        return "", {}
    payload = {
        "mode": "auto",
        "query": query,
        "task_id": session_id,
        "workspace_id": workspace_id or CHATBOT_WORKSPACE_ID,
        "agent_id": CHATBOT_AGENT_ID,
        "agent_role": CHATBOT_AGENT_ROLE,
        "need_evidence": False,
        "token_budget": 1200,
        "top_k": limit,
    }
    try:
        data = await _memory_service_post(
            "/v1/memory/read",
            payload,
            tenant_id=tenant_id,
            principal_id=principal_id,
        )
    except Exception as exc:
        return "", {"memorydemo_search_error": str(exc)}

    if "context_package" not in data:
        return "", {"memorydemo_search_error": "memorydemo 检索响应缺少 context_package"}
    return _format_memory_context(data), data


async def save_turn(
    session_id: str,
    user_message: str,
    assistant_answer: str,
    *,
    workspace_id: str | None = None,
    tenant_id: str | None = None,
    principal_id: str | None = None,
) -> tuple[str | None, str | None]:
    trace_id = f"trace_chatbot_{uuid4().hex}"

    async def write_event(role: str, content: str) -> dict[str, Any]:
        event_id = f"evt_chatbot_{uuid4().hex}"
        payload = {
            "type": "event",
            "idempotency_key": f"idem_{event_id}",
            "workspace_id": workspace_id or CHATBOT_WORKSPACE_ID,
            "event": {
                "event_id": event_id,
                "event_type": "chat_message",
                "role": role,
                "content": content,
                "source": "chatbot",
                "session_id": session_id,
                "task_id": session_id,
                "created_at": _now_iso(),
                "file_refs": [],
                "tool_result_refs": [],
                "artifact_refs": [],
            },
            "signals": {},
        }
        return await _memory_service_post(
            "/v1/memory/write",
            payload,
            trace_id=trace_id,
            tenant_id=tenant_id,
            principal_id=principal_id,
        )

    try:
        user_result = await write_event("user", user_message)
        assistant_result = await write_event("assistant", assistant_answer)
        consolidate_result = await _memory_service_post(
            "/v1/memory/write",
            {
                "type": "consolidate",
                "workspace_id": workspace_id or CHATBOT_WORKSPACE_ID,
                "trigger": "manual",
            },
            trace_id=trace_id,
            tenant_id=tenant_id,
            principal_id=principal_id,
        )
    except Exception as exc:
        return None, str(exc)
    operation_ids = [
        str(user_result.get("operation_id", "")),
        str(assistant_result.get("operation_id", "")),
        str(consolidate_result.get("operation_id", "")),
    ]
    return ",".join(op for op in operation_ids if op), None


def build_messages(
    user_message: str,
    memory_context: str,
    history_messages: list[dict[str, str]],
) -> list[dict[str, str]]:
    system = (
        "你是一个本地聊天机器人。请使用和用户相同的语言回答。"
        "优先遵循用户本轮消息。"
        "如果提供了 Agent Memory Service 记忆上下文，请把它当作用户长期记忆和历史事实参考。"
        "不要编造记忆上下文中不存在的事实。"
    )
    if memory_context:
        system += f"\n\n以下是从 Agent Memory Service 检索到的相关记忆：\n{memory_context}"
    return [
        {"role": "system", "content": system},
        *history_messages,
        {"role": "user", "content": user_message},
    ]


@app.get("/health")
async def health() -> dict[str, Any]:
    memory_service_ok = False
    memory_service_health: dict[str, Any] = {}
    memory_service_url = await discover_memory_service_url()
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            response = await client.get(f"{memory_service_url}/health")
            response.raise_for_status()
            memory_service_health = response.json()
        memory_service_ok = (
            memory_service_health.get("status") == "ok"
            or bool(memory_service_health.get("ok"))
        )
    except Exception as exc:
        memory_service_health = {"error": str(exc)}
    return {
        "ok": True,
        "memory_service_url": memory_service_url,
        "memory_service_ok": memory_service_ok,
        "memory_service_health": memory_service_health,
        "model": DEEPSEEK_MODEL,
        "db_path": str(CHATBOT_DB_PATH),
    }


@app.post("/sessions", response_model=SessionResponse)
async def new_session(request: SessionCreateRequest) -> SessionResponse:
    return create_session(request.title)


@app.get("/sessions", response_model=list[SessionResponse])
async def sessions(limit: int = 50) -> list[SessionResponse]:
    return list_sessions(limit)


@app.get("/sessions/{session_id}/messages", response_model=list[MessageResponse])
async def session_messages(session_id: str, limit: int = 100) -> list[MessageResponse]:
    return get_messages(session_id, limit)


def _development_identity_from_request(request: Request) -> tuple[str | None, str | None]:
    tenant_id = request.headers.get("X-Development-Tenant-ID")
    principal_id = request.headers.get("X-Development-Principal-ID")
    return tenant_id, principal_id


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, http_request: Request) -> ChatResponse:
    session_id = ensure_session(request.session_id, request.message)
    history_messages = get_recent_llm_messages(session_id, request.history_limit)
    tenant_id, principal_id = _development_identity_from_request(http_request)
    workspace_id = request.workspace_id.strip() or CHATBOT_WORKSPACE_ID
    memory_context, memory_metadata = await search_memory(
        request.message,
        request.memory_limit,
        session_id,
        workspace_id=workspace_id,
        tenant_id=tenant_id,
        principal_id=principal_id,
    )

    completion = await get_llm_client().chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=build_messages(request.message, memory_context, history_messages),
    )
    answer = completion.choices[0].message.content or ""

    add_message(session_id, "user", request.message)
    add_message(session_id, "assistant", answer)

    if request.save_memory:
        memory_path, memory_save_error = await save_turn(
            session_id,
            request.message,
            answer,
            workspace_id=workspace_id,
            tenant_id=tenant_id,
            principal_id=principal_id,
        )
    else:
        memory_path, memory_save_error = None, None
    return ChatResponse(
        session_id=session_id,
        answer=answer,
        memory_context=memory_context,
        memory_saved=memory_path is not None,
        memory_path=memory_path,
        memory_save_error=memory_save_error,
        history_count=len(history_messages),
        memory_service_url=await discover_memory_service_url(),
        memory_metadata=memory_metadata,
    )
