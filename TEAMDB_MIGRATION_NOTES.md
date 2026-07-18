# TeamDB 마이그레이션 인수인계 노트

이 저장소(`exceldashboard-teamDB`)는 [`exceldashboard-team`](https://github.com/DangDangSoo/exceldashboard-team)의 완성된 상태(Day1~3: 계정 인증, 소유권 접근제어, 견고화·문서)를 그대로 복사해서 만든 곳입니다. **아직 코드는 하나도 안 바뀐 상태**(SQLite 그대로)이고, 여기서부터 인프라 전환 작업을 시작합니다.

## 왜 이 작업을 하는가

지금까지 만든 Excel2Dashboard(Basic→Pro→Team)를 **온라인에 올려서 다른 사람(강의 수강생 등)이 직접 접속해서 테스트할 수 있게** 하려는 목적입니다. 지금 구조(SQLite 파일 DB + 로컬 디스크 업로드)는 로컬 실행 전제라 그대로는 클라우드 호스팅에 못 올립니다.

## 최종 목표 인프라

| 구성요소 | 지금(exceldashboard-team) | 바꿀 것 |
|---|---|---|
| DB | SQLite(`data/app.db`) | **Supabase(Postgres)** |
| 파일 저장 | 로컬 디스크(`uploads/`) | **Supabase Storage** |
| 앱 호스팅 | 로컬(`uvicorn ... --reload`) | **Render** (무료 티어, 카드 불필요, GitHub 연동 자동배포) |

## 이 저장소에서 할 작업 (1단계 — DB/스토리지 이관)

`app/db.py`(SQLite 직접 사용)와 `app/storage.py`(로컬 디스크 저장)를 Supabase 연동으로 바꾸는 작업입니다. Render 배포는 이 작업이 끝나고 별도로 진행하는 2단계입니다.

### ⚠️ 아직 사용자 확정 안 된 결정 4가지 (새 대화에서 먼저 확인할 것)

이전 대화에서 Claude가 추천안을 냈지만, 사용자가 저장소 복사 쪽으로 화제를 돌리면서 **명시적으로 확정하지 않았습니다.** 새 대화를 시작하면 아래 4가지부터 사용자에게 확인받고 진행해야 합니다:

1. **DB 드라이버**: `psycopg`(raw SQL 직접 작성) 추천 — 지금 `sqlite3` 직접 사용 스타일과 일관되고, 이 프로젝트가 계속 지켜온 "ORM 미사용" 원칙과도 맞음. (대안: `supabase-py` 클라이언트, SQLAlchemy)
2. **커넥션 풀러 사용 여부**: Render처럼 요청마다 짧게 DB에 연결하는 환경에는 Supabase가 제공하는 PgBouncer 기반 풀러 접속 주소(보통 포트 6543) 사용을 추천 — Supabase 프로젝트 생성 후 대시보드에서 정확한 주소 확인 필요.
3. **JSON 컬럼 타입**: 지금 `columns_json`, `spec_json`은 SQLite에서 그냥 TEXT였음. Postgres의 네이티브 `JSONB`로 바꿀지, 그냥 TEXT로 유지할지 — 지금 코드에서 JSON 내부 값으로 검색하는 로직은 없어서 TEXT 유지가 더 단순하지만 확정 안 됨.
4. **인증 로직 유지 여부**: 지금 있는 자체 로그인(bcrypt 해싱 + `sessions` 테이블, `app/auth.py`)을 그대로 Postgres로 옮길지, 아니면 Supabase Auth로 통째로 교체할지. **유지 추천**(변경 범위 최소화, 이미 검증된 코드 재사용). Supabase Auth로 가면 "비밀번호 재설정 불가"라는 알려진 한계를 해결할 수 있다는 장점은 있지만 Day1 작업을 상당 부분 다시 해야 함.

### 참고 문서
- [PRD_Excel2Dashboard_Team_v0.1.md](./PRD_Excel2Dashboard_Team_v0.1.md) — Team 단계 전체 설계 배경
- [README.md](./README.md) — 지금(SQLite 기준) 아키텍처·API 설명, 마이그레이션 후 갱신 필요
- [EVALUATION.md](./EVALUATION.md) — 지금까지 자체평가 이력
- `app/db.py`, `app/storage.py` — 이번에 다시 쓸 파일들
- `app/main.py` — DB/스토리지 함수를 호출하는 쪽. 인터페이스(함수 시그니처)를 유지하면 이 파일은 거의 안 건드려도 됨

### 사전 준비 (사용자가 직접 해야 하는 것 — 새 대화에서 먼저 확인)
- Supabase 가입 + 새 프로젝트 생성이 아직 안 됐다면, 코드 작업 전에 먼저 해야 함
- Postgres 접속 정보, API 키(anon/service_role), Storage 버킷 생성까지 끝낸 상태여야 실제 연동 테스트 가능

## 2단계 (이 저장소 작업 이후, 별도 진행)

- Render 계정 생성(사용자가 직접) → GitHub 연동 → Web Service 생성
- Build Command `pip install -r requirements.txt`, Start Command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`(`--reload` 빼야 함)
- 환경변수(Supabase 접속정보)를 Render 대시보드에 등록
- 앞으로 새 데모 프로젝트가 생겨도 "새 저장소 → 같은 Render 계정에 새 Web Service 연결"만 반복하면 됨(계정 1개로 여러 프로젝트 가능, 서비스별 URL이 각각 생김 — `이름.onrender.com` 형태의 경로 통합은 기본 지원 안 됨)

## 지켜야 할 원칙 (지금까지 이 프로젝트 전체에서 일관되게 지켜온 것)

- 구현 시작 전에 Plan Mode로 계획을 먼저 세우고 승인받은 뒤 진행
- `app/core/*.py`(파싱·통계·차트 등 순수 로직)는 이번에도 무수정
- 작은 변경도 실제로 서버 띄워서 브라우저/curl로 검증 후 완료 보고
- 커밋은 사용자가 명시적으로 요청할 때만
