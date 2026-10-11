# 변경 이력

형식: 버전마다 **사용자에게 보이는 변화**, **아키텍처 변경**, **API 변경**, **운영자가 할 일**을 나눠 적는다.
구조 결정의 이유는 [architecture.md의 결정 기록](architecture.md#10-결정-기록-adr)에 번호로 남긴다.

## [0.2.3] - 2026-10-11

노트북에서 Ollama + gemma3:4b로 처음 실제 분석을 돌려 보니 결과가 거의 안 나왔다(6개 섹션 중 반영 0).
원인은 프롬프트·출력 형식이었다.

### 실측으로 찾은 문제 (gemma3:4b, 프롬프트 v1)
- RRULE을 틀리게 씀: `매달 25일` → `FREQ=MONTHLY;BYDAY=25`
- 선택 칸을 빼먹음: interval인데 `every` 없이 숫자를 RRULE에 넣음
- 지어냄: 주기 없는 '치과 다녀온 날 기록'에 '매주 화요일', 입력으로 준 기록 날짜·오늘·납부일을 '한 날'로 넣음
- 신뢰도는 늘 1.0, 알림 시점·허용 구간은 늘 0
- 평가셋 24문장: **1/24 (4%)**, 문장당 약 35초

### 변경 (프롬프트 v2, `PROMPT_VERSION=2026-10-11.4`)
- LLM 출력 형식: `kind`(interval/monthly/weekly/yearly/once/learned/none) + 단순한 칸, 모든 칸 필수, 근거 문장을 맨 앞에.
  RRULE·알림 시점·허용 구간·중요도·신뢰도는 코드가 정한다.
- 요일은 한글 한 글자("화", "목")로 받는다(영문 TU/TH를 헷갈렸다).
- 짧은 규칙 설명 + 예시 대화 11개(평가셋과 겹치지 않는 문장). 기록 날짜 대신 기록 개수만 넘긴다.
- 코드가 확실하게 읽는 값은 코드가 이긴다(`app/extraction/korean.py`, RuleMock과 공유):
  금액 계산, 간격형의 지난 날짜(60일 안의 앞날은 버리고 더 멀면 작년), "주말이어도 그날"·"휴일이면" 표현.
  요일이 붙은 interval은 weekly로 바꾼다.
- Ollama 옵션: `num_ctx`(`LLM_NUM_CTX`, 4096), `num_predict` 512, `keep_alive`(`LLM_KEEP_ALIVE`, 30m).
- 검증: 규칙 값(숫자·단위·요일·날짜)이 원문에 없으면 확인 필요. 원문에 없는 이력 날짜는 버린다.
  근거 문장이 원문과 다르면 거절 대신 본문 전체를 근거로 두고 확인 필요.
- 평가셋 24문장: **23/24 (96%)**, 문장당 약 14초(앞부분 프롬프트 캐시). 남은 1개(여권 만료일을 '매달 2일'로 읽음)는
  '반복을 뜻하는 말이 없음' 근거 확인에 걸려 확인 필요로 간다.

### 아키텍처 변경
- ADR 16. LLM에 맡기는 일을 줄이고(분류·규칙 종류·숫자 옮기기), 계산·형식 만들기·신뢰 판단은 코드로 옮겼다.
  v1 출력(`type`+`rrule`)은 평가셋·RuleMock용으로 계속 받는다. 저장 형식(`rule_json`)은 그대로.

### 운영자가 할 일
- 서버를 다시 켠다(`stop_*` → `start_*`).
- 예전 프롬프트로 '확인 필요'에 들어간 섹션은 자동으로 다시 분석되지 않는다. 노트 탭의 **다시 분석**을 사람마다 한 번 누른다.

### 문서
- README "로컬 LLM(Ollama)을 어떻게 부르나": 호출 흐름, 프롬프트 v2, 검증, 모델별 실측 표.

## [0.2.2] - 2026-10-11

사용자 요청: 포트·Ollama IP처럼 바뀔 수 있는 값은 env로, GitHub에 올리므로 보안 정보는 git 제외,
`.env.local` 기준으로 쓰고 `.env.example`에 예시.

### 추가
- `.env.example`(올림): 모든 설정 키와 예시. `.env.local`(안 올림)이 실제 값.
- 설정 `WEB_HOST`, `WEB_PORT`(화면 개발 서버). `python -m app config`(지금 값, 비밀은 가림), `python -m app config --ports`(스크립트용).
- `tests/test_config.py`: 우선순위, `.env.local`의 `APP_ENV`, CI가 `.env.local`을 안 읽는지, 올라가는 프로필에 주소·비밀이 없는지.

### 변경
- `config/dev.env`, `config/prod.env`에서 `LLM_ENDPOINTS`, `LLM_MODEL`, `HOST`, `PORT`를 뺐다(동작 방식만 남김).
- `APP_ENV`를 `.env.local`에 둘 수 있다(OS 환경 변수 → `.env.local` → `dev`).
- 실행 스크립트: 포트를 `.env.local`에서 받아 쓰고, 쓴 포트를 `logs/run.env`에 남긴다. 끄기는 `run.env` → `.env.local` → 기본값 순으로 포트를 찾는다.
  `.env.local`이 없으면 예시를 복사해 만든다. `-AppEnv`를 안 주면 `.env.local`의 `APP_ENV`를 따른다.
- `web/vite.config.ts`: 포트·주소·프록시 대상을 `.env.local`에서 읽는다(`@types/node` 추가). `strictPort` 기본.
- `.gitignore`: `.env`, `.env.*`(단 `.env.example` 제외), 키·인증서 파일, `.ci-data/`, `tests/cassettes/`(실제 노트 문장이 녹화될 수 있음),
  `*.log`, `*.pid`, 편집기·OS 파일.

### 아키텍처 변경
- 설정 규칙 하나를 백엔드·스크립트·Vite가 함께 쓴다 (ADR 15, [architecture.md §8](architecture.md#8-설정)). `load_settings(root=...)`로 테스트 가능.

### 운영자가 할 일
- `cp .env.example .env.local`(Windows `copy`) 후 값 입력. 예전에 `config/prod.env`에 적었던 Ollama 주소는 `.env.local`의 `LLM_ENDPOINTS`로 옮긴다.
- 운영 Mac mini는 `.env.local`에 `APP_ENV=prod`를 넣거나 launchd에서 `APP_ENV=prod`를 준다.

## [0.2.1] - 2026-10-10

### 추가
- 실행 스크립트: `start_windows.bat` / `stop_windows.bat` (본체는 `scripts/*.ps1`), `start_mac.sh` / `stop_mac.sh`.
  백엔드(:8000)와 Vite 화면(:5173)을 백그라운드로 함께 띄우고, 로그를 `logs/backend.log`·`logs/frontend.log`에 이어 붙인다.
  PID는 `logs/*.pid`. 끄기는 PID 트리를 강제 종료하고, PID 파일이 없으면 포트를 잡은 이 프로젝트 프로세스만 찾아 종료.
  처음 실행 시 `.venv`·`web/node_modules` 자동 준비. 옵션: 브라우저 안 열기, LAN 허용, `APP_ENV`.

### 변경
- Vite 개발 서버가 기본으로 `127.0.0.1`에서만 열린다(전에는 모든 네트워크). 개발 설정은 인증이 꺼져 있어 같은 와이파이의
  다른 기기가 `/api`까지 닿을 수 있었다. 태블릿 테스트는 `-Lan`/`--lan`으로 명시적으로 연다.
- `.gitattributes`: `*.bat`, `*.ps1`은 CRLF. `.ps1`은 UTF-8 BOM으로 저장(Windows PowerShell 5.1이 BOM 없는 파일을 cp949로 읽어 한글이 깨진다).
  `deploy/windows/register-task.ps1`도 BOM으로 다시 저장.

### 아키텍처 변경
- 없음(실행 도구만 추가). 운영 메모는 [architecture.md §9](architecture.md#9-운영-메모).

### 운영자가 할 일
- macOS로 옮길 때 실행 권한: `chmod +x start_mac.sh stop_mac.sh` (git이 아닌 방법으로 복사했다면).
- 확인한 환경: Windows 11(시작·중복 시작 거부·종료·PID 없이 포트로 종료·LAN 옵션). macOS 스크립트는 문법 검사만 했고 실제 Mac에서는 아직 안 돌려 봤다.

## [0.2.0] - 2026-10-10

사용자 요청: 도움말 페이지, LLM 상태를 빨간불/초록불로, 사람 추가·제거를 화면에서, 기준일 제거,
"LLM rule 모드" 없이 실제 LLM이 연결됐을 때만 분석.

### 추가
- **도움말 페이지** (`#/help`, 상단 바 "도움말"): 모든 버튼, 노트 쓰는 법, 배지 의미, LLM 불, 연결이 끊겼을 때.
- **사람 관리 페이지** (`#/people`, 상단 바 "사람 관리"): 추가(이름·색), 이름·색 저장, 일정·노트 바로가기, 삭제(확인 창).
  삭제한 사람의 노트는 `people/_archive/<id>-<시각>/`로 옮겨 남긴다. 이름을 바꾸면 다른 노트의 `(공동: 옛 이름)` 줄을 알려 준다.
- **LLM 불** (상단 바): 초록 = 연결됨, 빨강 = 연결 안 됨, 회색 = 확인 전, "대기 n" = 분석을 기다리는 섹션 수.
  누르면 노드별 상태(응답 없음 / 모델 미설치 + `ollama pull` 안내), 마지막 확인 시각, "지금 확인" 버튼.
- 문서: `docs/requirements.md`, `docs/architecture.md`, 이 파일.

### 변경
- 개발 기본 설정(`config/dev.env`)이 `LLM_MODE=ollama`, `LLM_ENDPOINTS=http://127.0.0.1:11434`. 설정 기본값도 `ollama`.
  Ollama가 꺼져 있으면 분석만 기다리고, 1분마다 확인해서 연결되면 이어서 한다.
- 화면의 "LLM rule 모드" 배지 삭제. RuleMock은 `LLM_MODE=rule`을 직접 줄 때만 쓰는 오프라인 개발 도구로 남김.
- 판정 날짜는 항상 실제 오늘(설정 시간대). 다른 날은 달력에서 날짜를 눌러 본다.
- 상단 바 정리: 대시보드가 아닐 때는 "사람"·"다음 N일"을 숨김. 앱 이름을 누르면 대시보드로.

### 제거
- 상단 바 "기준일" 입력, `PUT /api/v1/admin/clock`, 설정 `CLOCK_ADJUSTABLE`, `meta.clock_adjustable`.
  (`CLOCK_FIXED`는 테스트·CI 재현용으로만 남음)

### 수정
- 배포 뒤 빈 화면: 브라우저가 옛 `index.html`(사라진 번들을 가리킴)을 캐시하던 문제. `index.html` 등은 `no-cache`,
  `assets/`는 1년 캐시, 서비스 워커 캐시 이름 `pa-shell-v2`.
- 지운 사람의 노트를 파일 감시가 다시 만들 수 있던 경로 차단(목록에 없는 사람은 인덱싱·노트 생성 안 함).

### 아키텍처 변경
- `ExtractionService`에 LLM 준비 판정 `_llm_ready()` 추가 (ADR 10). 꺼진 걸 확인한 뒤 `LLM_RETRY_SECONDS` 동안은
  LLM을 부르지 않고 섹션을 `waiting_llm`으로 둔다. 상태가 바뀌면 SSE `llm` 이벤트.
- `LLMClient` 프로토콜에 `probe()` 추가: 노드별 `{url, model, reachable, has_model, error}`. 상태 확인은 첫 노드에서 멈추지 않고 모든 노드를 본다.
- `PeopleManager`(사람 추가·수정·삭제 오케스트레이션) 추가. `people.json`이 원본, 쓰기는 원자적 교체 (ADR 12).
  `NoteRepository.archive()`, 인덱서가 목록에 없는 사람을 건너뜀.
- 정적 파일 서빙을 `WebFiles`(캐시 헤더)로 교체 (ADR 13).
- 시계: 화면에서 바꾸는 경로 제거 (ADR 11). `JobRunner.date_changed()` 삭제.

### API 변경 (`/api/v1`)
- 추가: `POST /people`, `PATCH /people/{id}`, `DELETE /people/{id}`, `GET /llm`, `POST /llm/check`.
- 변경: `GET /people` 항목에 `note_path`, `sections`, `items`. `meta.llm`이 `checked_at`, `nodes[]`, `pending`을 포함.
- 제거: `PUT /admin/clock`, `meta.clock_adjustable`.
- SSE 이벤트 추가: `llm`, `people`. 제거: `clock`.

### 운영자가 할 일
- 개발 PC: 예전 `.dev-data`는 RuleMock이 분석한 결과라 지우고 다시 시작한다: `python -m app reset-dev-data`.
- Ollama를 설치·실행하고 모델을 받는다: `ollama pull qwen2.5:7b-instruct`(또는 `LLM_MODEL`/`LLM_ENDPOINTS`에 적은 모델).
- 화면을 다시 빌드한다: `npm --prefix web run build`. 태블릿은 한 번 새로고침.

## [0.1.0] - 2026-10-10

설계 문서와 프로토타입을 바탕으로 한 첫 구현.

### 추가
- 백엔드(FastAPI + SQLite): 노트 파서·이력 줄 쓰기·3-way 병합·git 커밋·파일 감시, LLM 추출 파이프라인
  (스키마 강제, 검증, 판정, 확인 필요, 캐시), 결정론적 스케줄러(interval/calendar RRULE/learned/once,
  한국 영업일·대체공휴일, 말일, 선언 vs 실제 주기 제안), 회차 조회·조작, 자금 요약, 알림(app/ntfy/텔레그램/이메일),
  기기 토큰 인증, SSE.
- LLM 클라이언트: Ollama(노드 순서대로 헬스체크·장애 넘김), RuleMock, FixtureMock, Replay/Record, 가짜 Ollama 서버(테스트).
- 화면(React + TS + Vite PWA): 전체 보기, 개인 보기(일정·노트), 날짜 상세, 항목 상세, 동작 창, 확인 필요, 납부, 테마, 오프라인 표시.
- 평가셋 24개와 `python -m app eval`, 테스트 82개, CI(Windows·macOS), launchd·작업 스케줄러 설정.

### 설계 문서와 다르게 한 것
ADR 2~8 참고: 미완료 회차만 저장, `event.section_id`, 직접 만든 달력, 스레드 정기 작업, 최상위 `web/`, `saving` 카테고리.
