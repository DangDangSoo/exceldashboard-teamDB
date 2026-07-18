"""
Supabase(Postgres) 영속 계층 (Team 마이그레이션 1단계 핵심 변경 지점).
app/session_store.py와 역할이 다르다: session_store는 "지금 이 프로세스가 들고 있는
DataFrame 캐시"고, 여기는 "진짜 저장소"(dataset 메타데이터·태그) — 서버를 껐다 켜도 남는다.
psycopg를 직접 사용한다(ORM 미사용, Pro PRD §2 결정). JSON 직렬화는 이 모듈 안에서만
일어나고, 호출자(app/main.py)는 항상 ColumnMeta 객체로만 다룬다.
"""
import json
import os

import psycopg
from psycopg.rows import dict_row

from app.models import ColumnMeta

_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id),
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS datasets (
        id TEXT PRIMARY KEY,
        filename TEXT NOT NULL,
        file_path TEXT NOT NULL,
        row_count INTEGER NOT NULL,
        col_count INTEGER NOT NULL,
        columns_json TEXT NOT NULL,
        uploaded_at TEXT NOT NULL,
        owner_id TEXT NOT NULL REFERENCES users(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dataset_tags (
        dataset_id TEXT NOT NULL REFERENCES datasets(id),
        tag TEXT NOT NULL,
        PRIMARY KEY (dataset_id, tag)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS saved_analyses (
        id TEXT PRIMARY KEY,
        dataset_id TEXT NOT NULL REFERENCES datasets(id),
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        spec_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
]

_DEFAULT_INVITE_CODE = "CHANGEME"


def get_connection() -> psycopg.Connection:
    # prepare_threshold=None: PgBouncer transaction-mode 풀러는 커넥션마다 물리 서버가
    # 바뀔 수 있어 서버사이드 prepared statement가 깨진다 — 매번 새로 연결하므로 꺼둔다.
    conn = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, prepare_threshold=None)
    for statement in _SCHEMA_STATEMENTS:
        conn.execute(statement)
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
        ("invite_code", _DEFAULT_INVITE_CODE),
    )
    conn.commit()
    return conn


def normalize_tags(raw_tags: list[str]) -> list[str]:
    """앞뒤 공백 제거 + 영문 소문자 통일 + 빈 문자열/중복 제거 (Pro PRD §2 결정)."""
    normalized: list[str] = []
    for tag in raw_tags:
        cleaned = tag.strip().lower()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def _row_to_dataset_dict(row: dict) -> dict:
    d = dict(row)
    d["columns"] = [ColumnMeta(**c) for c in json.loads(d.pop("columns_json"))]
    return d


def insert_dataset(
    dataset_id: str,
    filename: str,
    file_path: str,
    row_count: int,
    col_count: int,
    columns: list[ColumnMeta],
    uploaded_at: str,
    tags: list[str],
    owner_id: str,
) -> None:
    columns_json = json.dumps([c.model_dump() for c in columns])
    normalized_tags = normalize_tags(tags)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO datasets (id, filename, file_path, row_count, col_count, columns_json, uploaded_at, owner_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (dataset_id, filename, file_path, row_count, col_count, columns_json, uploaded_at, owner_id),
        )
        if normalized_tags:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO dataset_tags (dataset_id, tag) VALUES (%s, %s)",
                    [(dataset_id, tag) for tag in normalized_tags],
                )


def get_dataset(dataset_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT d.*, u.username AS owner_username FROM datasets d
            JOIN users u ON u.id = d.owner_id
            WHERE d.id = %s
            """,
            (dataset_id,),
        ).fetchone()
        return _row_to_dataset_dict(row) if row is not None else None


def get_tags(dataset_id: str) -> list[str]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT tag FROM dataset_tags WHERE dataset_id = %s ORDER BY tag", (dataset_id,)
        ).fetchall()
        return [row["tag"] for row in rows]


def set_tags(dataset_id: str, raw_tags: list[str]) -> None:
    normalized_tags = normalize_tags(raw_tags)
    with get_connection() as conn:
        conn.execute("DELETE FROM dataset_tags WHERE dataset_id = %s", (dataset_id,))
        if normalized_tags:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO dataset_tags (dataset_id, tag) VALUES (%s, %s)",
                    [(dataset_id, tag) for tag in normalized_tags],
                )


def update_columns(dataset_id: str, columns: list[ColumnMeta]) -> None:
    columns_json = json.dumps([c.model_dump() for c in columns])
    with get_connection() as conn:
        conn.execute("UPDATE datasets SET columns_json = %s WHERE id = %s", (columns_json, dataset_id))


def list_datasets(tag: str | None = None) -> list[dict]:
    with get_connection() as conn:
        if tag:
            normalized = normalize_tags([tag])
            if not normalized:
                return []
            rows = conn.execute(
                """
                SELECT DISTINCT d.*, u.username AS owner_username FROM datasets d
                JOIN users u ON u.id = d.owner_id
                JOIN dataset_tags t ON t.dataset_id = d.id
                WHERE t.tag = %s
                ORDER BY d.uploaded_at DESC
                """,
                (normalized[0],),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT d.*, u.username AS owner_username FROM datasets d
                JOIN users u ON u.id = d.owner_id
                ORDER BY d.uploaded_at DESC
                """
            ).fetchall()

    result = []
    for row in rows:
        d = _row_to_dataset_dict(row)
        d["tags"] = get_tags(d["id"])
        result.append(d)
    return result


def _row_to_analysis_dict(row: dict) -> dict:
    d = dict(row)
    d["spec"] = json.loads(d.pop("spec_json"))
    return d


def insert_saved_analysis(
    analysis_id: str,
    dataset_id: str,
    kind: str,
    title: str,
    spec: dict,
    created_at: str,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO saved_analyses (id, dataset_id, kind, title, spec_json, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (analysis_id, dataset_id, kind, title, json.dumps(spec), created_at),
        )


def list_saved_analyses(dataset_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM saved_analyses WHERE dataset_id = %s ORDER BY created_at DESC",
            (dataset_id,),
        ).fetchall()
    return [_row_to_analysis_dict(row) for row in rows]


def get_saved_analysis(analysis_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM saved_analyses WHERE id = %s", (analysis_id,)).fetchone()
        return _row_to_analysis_dict(row) if row is not None else None


def delete_dataset(dataset_id: str) -> None:
    """datasets 행 + 딸린 dataset_tags/saved_analyses까지 함께 정리한다.
    FK에 ON DELETE CASCADE를 걸지 않았으므로 여기서 수동으로 지워야 고아 행이 안 남는다."""
    with get_connection() as conn:
        conn.execute("DELETE FROM saved_analyses WHERE dataset_id = %s", (dataset_id,))
        conn.execute("DELETE FROM dataset_tags WHERE dataset_id = %s", (dataset_id,))
        conn.execute("DELETE FROM datasets WHERE id = %s", (dataset_id,))


def delete_saved_analysis(analysis_id: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM saved_analyses WHERE id = %s", (analysis_id,))


def create_user(user_id: str, username: str, password_hash: str, created_at: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, created_at) VALUES (%s, %s, %s, %s)",
            (user_id, username, password_hash, created_at),
        )


def get_user_by_username(username: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = %s", (username,)).fetchone()
        return dict(row) if row is not None else None


def get_user_by_id(user_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
        return dict(row) if row is not None else None


def create_session(token: str, user_id: str, created_at: str, expires_at: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (%s, %s, %s, %s)",
            (token, user_id, created_at, expires_at),
        )


def get_session(token: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE token = %s", (token,)).fetchone()
        return dict(row) if row is not None else None


def delete_session(token: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM sessions WHERE token = %s", (token,))


def get_setting(key: str) -> str | None:
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = %s", (key,)).fetchone()
        return row["value"] if row is not None else None
