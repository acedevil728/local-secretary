# 공유형 개인 비서 & 대시보드

사람이 자유롭게 적은 노트를 로컬 LLM이 "추적 항목 + 규칙 + 이력"으로 구조화하고, 날짜 계산은 결정론적
스케줄러가 맡아 대시보드와 알림으로 보여 준다. **LLM은 읽고 구조화만, 날짜 계산은 코드가** 한다.

```
노트(people/<id>/notes.md) ──▶ 섹션·이력 줄 파싱 ──▶ 추출(로컬 LLM, 연결됐을 때만) ──▶ 검증·판정 ──▶ 스케줄러 ──▶ API ──▶ 대시보드·알림
        ▲                                                                                              │
        └──────────────────────────── 완료하면 이력 줄을 노트에 쓰고 다시 읽는다 ◀──────────────────────────┘
```

| 문서 | 내용 |
|---|---|
| [docs/requirements.md](docs/requirements.md) | 요구사항(F1~F13, 비기능), 구현 상태, 없앤 요구사항, 열린 질문과 임시 결정 |
| [docs/architecture.md](docs/architecture.md) | 현재 구조, 데이터 모델, 주요 흐름, 스레드, API, 설정, 결정 기록(ADR) |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | 버전별 변경(사용자 변화 / 아키텍처 / API / 운영자가 할 일) |
| 화면의 **도움말** (`#/help`) | 사용자용: 버튼마다 하는 일, 노트 쓰는 법 |

바탕이 된 설계 문서: 「공유형 개인 비서 & 대시보드 — 아키텍처 및 계획」, 프로토타입: 「개인 비서 대시보드」.

## 설정: `.env.local` (git에 올리지 않음)

주소·포트·Ollama 노드·알림 토큰처럼 **기기마다 다르거나 비밀인 값은 프로젝트 루트의 `.env.local`** 에만 둔다.
`.env.local`은 `.gitignore`에 있어 올라가지 않고, 키 목록과 예시는 `.env.example`(올라감)에 있다.

```bash
copy .env.example .env.local
```

macOS는 `cp .env.example .env.local`. 실행 스크립트는 `.env.local`이 없으면 예시를 복사해 만든다.

| 키 | 기본 | 뜻 |
|---|---|---|
| `APP_ENV` | `dev` | 프로필: `dev`(예시 데이터, 인증 끔) / `prod`(운영 데이터, 기기 토큰) |
| `HOST`, `PORT` | `127.0.0.1`, `8000` | 백엔드(FastAPI) |
| `WEB_HOST`, `WEB_PORT` | `127.0.0.1`, `5173` | 화면 개발 서버(Vite). Vite의 `/api` 프록시는 `HOST:PORT`로 간다 |
| `LLM_ENDPOINTS` | `http://127.0.0.1:11434` | Ollama 노드들(쉼표, `주소|모델`) |
| `LLM_MODEL` | `qwen2.5:7b-instruct` | 노드에 모델을 안 적었을 때 |
| `NTFY_URL`, `TELEGRAM_BOT_TOKEN`, `SMTP_*` | 없음 | 알림 채널(쓰는 것만) |

우선순위(뒤가 이긴다): 코드 기본값 < `config/<APP_ENV>.env`(올라가는 프로필, 동작 방식만) < `.env.local` < OS 환경 변수.
지금 적용되는 값은 `python -m app config`로 본다(토큰·비밀번호는 가려서 보여 준다). CI·테스트(`APP_ENV=ci`)는 `.env.local`을 읽지 않는다.

## 실행 스크립트 (백엔드 + 화면을 백그라운드로)

준비물: Python 3.11+, Node 20+, git. 처음 실행하면 `.env.local`, `.venv`, `web/node_modules`를 알아서 만든다.
주소·포트는 `.env.local`을 따른다(아래 설명의 8000·5173은 기본값).

| | Windows | macOS |
|---|---|---|
| 켜기 | `start_windows.bat` (더블클릭 가능) | `./start_mac.sh` (권한이 없으면 `bash start_mac.sh`) |
| 끄기 | `stop_windows.bat` | `./stop_mac.sh` |
| 옵션 | `-NoBrowser` 브라우저 안 열기, `-Lan` 태블릿에서 접속 허용, `-AppEnv prod` | `--no-browser`, `--lan`, `APP_ENV=prod ./start_mac.sh` |

- 백엔드(FastAPI) `http://localhost:8000`, 화면(Vite 개발 서버) `http://localhost:5173`. 화면은 **5173**으로 연다
  (8000의 `/`는 마지막으로 빌드한 `web/dist`라 오래됐을 수 있다).
- 로그는 `logs/backend.log`, `logs/frontend.log`에 실행할 때마다 이어 붙는다(`===== 시각 시작 =====` / `===== 시각 종료 =====`).
- PID는 `logs/backend.pid`, `logs/frontend.pid`, 실제로 쓴 포트는 `logs/run.env`. 끄기 스크립트는 이 PID와 자식 프로세스를
  강제 종료하고, PID 파일이 없으면 그 포트(없으면 `.env.local`의 포트)를 잡은 프로세스 중 **이 프로젝트 것만**
  (명령줄에 프로젝트 경로·`-m app serve`·`vite`) 종료한다.
- 이미 떠 있거나 포트를 다른 프로그램이 쓰고 있으면 켜지 않고 알려 준다. 뜨지 못하면 로그 끝 25줄을 보여 주고 정리한다.
- 화면은 기본으로 이 PC에서만 열린다. `-Lan`/`--lan`은 개발 설정이 인증 없이 돌므로 Tailscale 같은 믿을 수 있는 망에서만 쓴다.

## 빠른 시작 (개발, 수동)

준비물: Python 3.11+, Node 20+, git, (분석까지 보려면) [Ollama](https://ollama.com).

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -e ".[dev]"
```

macOS·Linux는 `.venv/bin/python`. `uv`가 있으면 `uv sync --extra dev`로 같은 환경을 만든다.

```bash
copy .env.example .env.local
```

```bash
npm --prefix web install
```

```bash
npm --prefix web run build
```

```bash
ollama pull qwen2.5:7b-instruct
```

```bash
.venv/Scripts/python -m app serve
```

`http://127.0.0.1:8000`(`.env.local`의 `HOST:PORT`)을 연다. 개발 프로필(`config/dev.env`):

- 처음 실행할 때 `data-sample/`(사람 3명 예시 노트)을 `.dev-data/`로 복사해서 쓴다. 원본은 건드리지 않는다.
- 같은 PC의 Ollama(`http://127.0.0.1:11434`)를 부른다. **Ollama가 꺼져 있으면 상단 LLM 불이 빨강**이고, 노트 분석만
  기다린다(대기 n). 일정·완료 기록·알림·달력은 그대로 돈다. 1분마다 다시 확인하고, 연결되면 밀린 분석을 이어서 한다.
- 판정은 항상 실제 오늘 날짜(Asia/Seoul) 기준이다. 다른 날은 달력에서 날짜를 누른다.
- 예시 데이터로 되돌리기: `python -m app reset-dev-data`

화면을 고치면서 볼 때는 백엔드를 띄운 채 `npm --prefix web run dev`(http://localhost:5173, `/api`는 8000으로 넘김).
위 실행 스크립트가 이 둘을 한 번에 해 준다.

### LLM 모드 (`LLM_MODE`)

| 값 | 쓰는 곳 |
|---|---|
| `ollama` (기본) | 운영·개발. `.env.local`의 `LLM_ENDPOINTS` 노드를 순서대로 확인해 응답하는 첫 노드를 쓴다. 노드마다 모델을 줄 수 있다(`.env.example` 참고) |
| `fixture` | 테스트·CI. 평가셋 표에서 찾아 답한다 |
| `record` / `replay` | 회귀 테스트. 실제 Ollama 응답을 `tests/cassettes/`에 녹화 / 재생. 녹화에는 실제 노트 문장이 들어갈 수 있어 `.gitignore`에 있다 |
| `rule` | GPU·Ollama 없이 화면만 만질 때 쓰는 정규식 mock. 정확도를 보장하지 않으며 기본값이 아니다 |

모델 이름은 예시다. Phase 0 평가셋 결과로 정한다.

### 로컬 LLM(Ollama)을 어떻게 부르나

- **모델**: `LLM_MODEL`(기본 `qwen2.5:7b-instruct`, RTX 3070 8GB에 들어가는 크기로 고른 임시값). 노드마다 다르게 하려면
  `LLM_ENDPOINTS`에 `주소|모델`. 7~8B와 14B를 평가셋으로 비교해 정하는 게 Phase 0이다.
- **호출 한 번** ([app/extraction/clients/ollama.py](app/extraction/clients/ollama.py)):
  1. 노드마다 `GET /api/tags`로 응답하는지, 모델이 설치돼 있는지 확인하고 되는 첫 노드를 쓴다.
  2. `POST /api/chat` 한 번: `stream: false`, `options.temperature: 0`, `format`에 JSON 스키마(구조화 출력).
     시스템 프롬프트는 [app/extraction/prompt.py](app/extraction/prompt.py)(규칙 4종, "날짜를 계산하지 마라", "근거 문장은 원문 그대로").
     사용자 메시지는 오늘 날짜, 섹션 제목·본문, 기존 이력 날짜, 기존 규칙을 담은 JSON.
  3. `LLM_TIMEOUT`(기본 120초) 안에 답이 없거나 연결이 끊기면 다음 노드로. 모두 안 되면 분석만 기다리고
     `LLM_RETRY_SECONDS`(기본 60초)마다 다시 확인한다.
- **앞뒤에서 코드가 하는 일**: 바뀐 섹션만 하나씩 순서대로 보낸다. 같은 문장·모델·`PROMPT_VERSION`이면 캐시를 쓴다.
  받은 뒤 검증한다([validate.py](app/extraction/validate.py)): 근거 문장이 원문에 있는지, 간격 1일~5년, RRULE 해석, 미래 이력 제외.
  신뢰도가 `CONFIDENCE_THRESHOLD`(기본 0.75) 이상이고 애매한 점이 없으면 반영하고, 규칙이 바뀌거나 신뢰도가 낮으면 '확인 필요'로 보낸다.
  JSON이 깨진 응답도 '확인 필요'로 간다.
- **아직 안 한 것** (실제 모델을 붙이면서 조정할 곳):
  - 실제 Ollama로는 아직 돌려 보지 않았다. 테스트는 가짜 Ollama 서버(`tests/fake_ollama/`)로만 했다.
  - 프롬프트에 예시 문장(few-shot)이 없다.
  - `num_ctx`(문맥 길이), `keep_alive`(모델을 메모리에 두는 시간)를 지정하지 않아 Ollama 기본값을 쓴다.
  - 깨진 JSON에 다시 묻지 않는다.
  - 실제 모델 정확도를 재지 않았다. 아래 "테스트"의 `eval --mode ollama`로 잰다.

## 테스트

```bash
.venv/Scripts/python -m pytest
```

90개. 스케줄러(머리 자르기 10/10 + 5주 = 11/14, 영업일·대체공휴일·말일), 노트 파서·병합, 추출 검증·판정, 가짜 Ollama 서버로
노드 장애·모델 없음·잘못된 JSON, HTTP 시나리오, 사람 관리, LLM 상태 불.

평가셋(Phase 0)으로 실제 모델 정확도 재기:

```bash
.venv/Scripts/python -m app eval --mode ollama -v
```

평가셋은 `tests/fixtures/extraction/*.json`(문장 → 기대 JSON), 지금 24개. 실제로 쓸 문장으로 30~50개까지 늘린다.
목표 90% 미만이면 종료 코드 1.

## 운영 (Mac mini + Tailscale)

1. Ollama 네이티브 설치(Docker 안 Ollama는 Apple GPU를 못 쓴다). 다른 기기에서 부르려면 `OLLAMA_HOST`를 Tailscale 주소에 바인딩.
2. `cp .env.example .env.local` 후 실제 값: `APP_ENV=prod`, `LLM_ENDPOINTS`(Mac mini·Windows PC의 Tailscale 주소), 알림 채널.
3. 기기 토큰: `APP_ENV=prod python -m app token create 거실태블릿` (한 번만 보여 준다. 태블릿 첫 화면에 붙여 넣는다)
4. HTTPS: `tailscale serve --bg 8000` → `https://<mac-mini>.<tailnet>.ts.net` (PWA·서비스 워커에 필요)
5. 자동 시작: `deploy/macos/com.local-secretary.plist` (Windows 테스트 PC는 `deploy/windows/register-task.ps1`)
6. Tailscale ACL: 태블릿은 백엔드 HTTPS만, 백엔드만 Ollama 포트에. 공인 인터넷에는 아무것도 열지 않는다.

- 백업·이전: `data/`(노트 git + `people.json`)만 옮긴다. DB는 `python -m app rebuild --full`로 다시 만든다.
- 사람 추가·삭제는 화면의 **사람 관리**에서. 지운 사람의 노트는 `data/people/_archive/`에 남는다.
- 모델·프롬프트를 바꾸면 `PROMPT_VERSION`을 올리고 eval → 노트 탭 "다시 분석".
- 운영용 수동 실행(화면에 없음): `POST /api/v1/admin/jobs/{morning|lead|regenerate|retry-llm|reindex}`

## 노트 형식

```markdown
# 지훈의 노트
이번 달은 지출 줄이기.            ← 제목 없는 메모: 추적 항목 아님

## 머리 자르기                     ← 섹션 하나 = 추적 항목 하나
나는 5주에 1번 머리를 잘라.          ← 사람의 영역: 앱은 고치지 않는다
<!-- history -->
- 2026-10-10 완료                  ← 앱의 영역: - YYYY-MM-DD 상태 [금액] [메모] [(대시보드)]
- 2026-11-13 완료 (대시보드)

## 아파트 관리비
매달 25일, 휴일이면 다음 영업일에 빠져나감. 보통 23만원 안팎
(공동: 수아)                        ← 공동 담당(코드가 읽는다)
<!-- history -->
- 2026-09-25 완료 228,400원
```

노트 폴더는 git 저장소이고 앱이 쓸 때마다 커밋한다. 외부 편집기(Obsidian 등)로 고쳐도 파일 감시가 다시 읽는다.

## 코드 구조

```
app/
  core/          설정, Clock, SQLite, SSE 버스
  scheduling/    규칙·다음 날짜 계산·한국 영업일 (DB·LLM 무관 순수 함수)
  notes/         노트 파서·이력 줄 쓰기·3-way 병합·git·인덱서·파일 감시
  extraction/    스키마·프롬프트·검증·판정·확인 필요·대기열 작업자·평가, clients/(ollama, fixture, replay, rule)
  occurrences/   회차 생성·조회·완료·미루기·날짜 변경, 항목 상세
  notify/        알림 채널·아침 요약·정기 작업
  people.py      사람 목록과 추가·수정·삭제
  api/           /api/v1 REST + SSE, OpenAPI 스키마, 기기 토큰
web/             React + TypeScript + Vite (PWA)
tests/           평가셋, 가짜 Ollama 서버, 녹화
data-sample/     개발용 예시 노트 3명
docs/            요구사항, 아키텍처, 변경 이력
```

자세한 구조와 설계 문서와 다르게 한 이유는 [docs/architecture.md](docs/architecture.md).
API 명세는 서버를 띄운 뒤 `/docs`(Swagger)와 `/openapi.json`.

## 유지보수 규칙

- 요구사항이 바뀌면 `docs/requirements.md` → 화면 도움말(`web/src/components/HelpPage.tsx`) → `docs/CHANGELOG.md` 순서로 고친다.
- 구조(모듈 경계, 데이터 모델, 스레드, API)를 바꾸면 `docs/architecture.md`와 결정 기록(ADR)에 한 줄을 더한다.
- 버전은 `app/__init__.py`, `pyproject.toml`, `web/package.json` 세 곳을 같이 올린다.
- API 응답 모양을 바꾸면 `app/api/schemas.py`와 `web/src/api/types.ts`를 같이 고친다.
