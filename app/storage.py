"""
Supabase Storage에 업로드 원본 파일을 저장/조회/삭제하는 순수 입출력 모듈.
FastAPI를 모른다 — app/core/*.py와 같은 성격이지만 외부 저장소를 다루므로 core 밖에 둔다.
"""
import os

from supabase import Client, create_client

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    return _client


def _bucket():
    return _get_client().storage.from_(os.environ["SUPABASE_STORAGE_BUCKET"])


def save_upload(dataset_id: str, filename: str, content: bytes) -> str:
    object_key = f"{dataset_id}/{filename}"
    _bucket().upload(object_key, content, {"upsert": "true"})
    return object_key


def read_upload(object_key: str) -> bytes:
    return _bucket().download(object_key)


def delete_upload(dataset_id: str) -> None:
    files = _bucket().list(dataset_id)
    if files:
        _bucket().remove([f"{dataset_id}/{f['name']}" for f in files])
