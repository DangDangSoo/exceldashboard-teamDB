# TeamDB 마이그레이션 인수인계 노트

이 저장소(`exceldashboard-teamDB`)는 [`exceldashboard-team`](https://github.com/DangDangSoo/exceldashboard-team)의 완성된 상태(Day1~3: 계정 인증, 소유권 접근제어, 견고화·문서)를 그대로 복사해서 만든 곳입니다. **1단계(DB/스토리지 이관)와 2단계(Render 배포) 모두 완료됐습니다.**

## 왜 이 작업을 했는가

지금까지 만든 Excel2Dashboard(Basic→Pro→Team)를 **온라인에 올려서 다른 사람(강의 수강생 등)이 직접 접속해서 테스트할 수 있게** 하려는 목적입니다. 기존 구조(SQLite 파일 DB + 로컬 디스크 업로드)는 로컬 실행 전제라 그대로는 클라우드 호스팅에 못 올렸습니다.

## 최종 인프라 (완료)

| 구성요소 | 이전(exceldashboard-team) | 현재 |
|---|---|---|
| DB | SQLite(`data/app.db`) | **Supabase(Postgres)**, 커넥션 풀러(포트 6543) 경유 |
| 파일 저장 | 로컬 디스크(`uploads/`) | **Supabase Storage** (버킷: `uploads`) |
| 앱 호스팅 | 로컬(`uvicorn ... --reload`) | **Render** Web Service (무료 티어) — `https://exceldashboard-teamdb.onrender.com` |

## 1단계에서 확정된 결정 사항

1. **DB 드라이버**: `psycopg`(raw SQL 직접 작성, ORM 미사용) — `app/db.py`
2. **커넥션 풀러**: 사용함 (PgBouncer, transaction mode, 포트 6543). `psycopg.connect(..., prepare_threshold=None)`으로 서버사이드 prepared statement 비활성화 필수 — 안 하면 풀러 환경에서 깨짐.
3. **JSON 컬럼**(`columns_json`, `spec_json`): TEXT 유지 (JSONB로 전환 안 함)
4. **인증 로직**: 자체 로그인(bcrypt + `sessions` 테이블) 그대로 유지, Supabase Auth로 교체 안 함
5. **Storage 클라이언트**: `supabase-py` 공식 SDK (Storage 전용, DB에는 안 씀)

## 2단계(Render 배포)에서 겪은 문제와 해결

### 1. `psycopg-binary==3.2.3` 빌드 실패
Render 빌드 환경 기본 Python이 3.14인데, `psycopg[binary]==3.2.3`은 그 버전용 wheel이 없어 빌드가 실패함. → `requirements.txt`에서 `psycopg[binary]==3.2.13`으로 상향(3.2.10 이상부터 wheel 존재).

### 2. 간헐적 세그폴트(exit code 139)로 배포 인스턴스 크래시
psycopg 버전을 올린 뒤에도, 파일 업로드 요청(DB 쓰기 + Storage 호출이 겹치는 무거운 요청) 처리 중 프로세스가 이유 없이 죽는 현상이 간헐적으로 발생(Render Events 탭에 `Exited with status 139`로 기록됨 — SIGSEGV, OOM이 아님). Python 3.14가 최신 버전이라 일부 네이티브 확장 모듈(psycopg 등)이 아직 충분히 안정화되지 않은 것으로 추정. → Render 환경변수에 `PYTHON_VERSION=3.13.14` 추가해 Python 버전을 명시적으로 고정. 이후 반복 테스트(연속 업로드 5회 등)에서 크래시 재현 안 됨.

**만약 이 프로젝트를 복사해서 새 Render 서비스를 또 만든다면, 처음부터 `PYTHON_VERSION`을 지정해두는 걸 권장합니다.**

### 3. GitHub App 설치 시 "No repositories found"
Render의 GitHub 연동이 조직/워크스페이스 단위로 걸려서, 저장소 선택 화면에 원하는 repo가 안 보일 수 있음. → Render의 "New Web Service" 화면에서 "GitHub" 버튼을 다시 눌러 GitHub App 설치/권한 화면으로 재진입하면 해결. 이 과정에서 GitHub이 보안을 위해 이메일 인증(sudo mode)을 요구할 수 있음(정상 동작).

## Render 환경변수 (필수 4개 + Python 버전)

| 변수 | 설명 |
|---|---|
| `DATABASE_URL` | Supabase Postgres 커넥션 풀러 문자열 (포트 6543) |
| `SUPABASE_URL` | `https://<project-ref>.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase API Keys의 secret key (`sb_secret_...` 또는 legacy `service_role`) |
| `SUPABASE_STORAGE_BUCKET` | `uploads` |
| `PYTHON_VERSION` | `3.13.14` (위 "간헐적 세그폴트" 항목 참고) |

로컬 개발 시에는 저장소 루트에 `.env.example`을 참고해서 `.env`를 만들면 됩니다(`.gitignore`에 등록되어 있어 커밋되지 않음).

## 회원가입 초대코드

기본값 `CHANGEME`는 소스코드(`app/db.py`)에 그대로 노출되어 있어 **이 저장소가 public이므로 반드시 변경**했습니다. 실제 값은 이 문서에 적지 않습니다(공개 저장소에 커밋되는 파일이라 노출 방지) — Supabase 대시보드 Table Editor의 `settings` 테이블에서 `invite_code` 값을 확인하거나, 필요시 그 자리에서 직접 바꿀 수 있습니다.

## 참고 문서
- [PRD_Excel2Dashboard_Team_v0.1.md](./PRD_Excel2Dashboard_Team_v0.1.md) — Team 단계 전체 설계 배경
- [README.md](./README.md) — 아키텍처·API 설명 (SQLite 기준으로 작성됨, Supabase 반영한 갱신은 아직 안 함 — 후속 작업으로 남겨둠)
- [EVALUATION.md](./EVALUATION.md) — 지금까지 자체평가 이력
- `app/db.py`, `app/storage.py` — 이번에 재작성한 파일들

## 앞으로 새 데모 프로젝트가 생기면

"새 저장소 → 같은 Render 계정에 새 Web Service 연결"만 반복하면 됩니다(계정 1개로 여러 프로젝트 가능, 서비스별 URL이 각각 생김 — `이름.onrender.com` 형태의 경로 통합은 기본 지원 안 됨). 빌드 실패 시 위 "2단계에서 겪은 문제와 해결" 항목을 먼저 확인하세요.

## 다음 학습/개발 방향 제안

1단계·2단계(DB/스토리지 이관, Render 배포)까지 끝낸 시점에서 다음으로 도움이 될 만한 주제:

- **자동화 테스트 + CI**: `pytest`로 API 엔드포인트 테스트를 작성하고, GitHub Actions에서 push마다 돌려서 "고장난 채로 push → Render에서 실패 확인" 사이클을 배포 전에 미리 잡기. 다만 앱 로직 버그는 잡아도, 이번에 겪은 psycopg wheel/세그폴트 같은 인프라 레벨 이슈까지는 못 막음.
- **로깅/모니터링**: Sentry 같은 에러 트래킹 도입. 이번에 크래시 원인을 Render 대시보드 로그를 일일이 스크린샷으로 확인하며 찾았는데, 에러 자동 수집·알림 구조가 있었으면 훨씬 빨랐을 것.
- 그 외 방향(프론트엔드 프레임워크 도입, 성능 최적화 등)도 후보. 아직 확정된 선택은 아님 — 다음 대화에서 사용자와 다시 논의 후 진행.

## 지켜야 할 원칙 (지금까지 이 프로젝트 전체에서 일관되게 지켜온 것)

- 구현 시작 전에 Plan Mode로 계획을 먼저 세우고 승인받은 뒤 진행
- `app/core/*.py`(파싱·통계·차트 등 순수 로직)는 이번에도 무수정
- 작은 변경도 실제로 서버 띄워서 브라우저/curl로 검증 후 완료 보고
- 커밋은 사용자가 명시적으로 요청할 때만
