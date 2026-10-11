#!/usr/bin/env bash
# 백엔드(FastAPI)와 프런트엔드(Vite)를 백그라운드로 띄운다.
#   주소·포트: 프로젝트 루트 .env.local (HOST, PORT, WEB_HOST, WEB_PORT). 없으면 .env.example을 복사해 만든다.
#              실제 값은 `python -m app config --ports`로 백엔드와 같은 규칙으로 정한다.
#   로그: logs/backend.log, logs/frontend.log (실행할 때마다 이어 붙인다)
#   PID:  logs/backend.pid, logs/frontend.pid / 쓴 포트: logs/run.env (stop_mac.sh가 읽는다)
#   처음 실행이면 .venv와 web/node_modules를 만든다.
# 사용: ./start_mac.sh [--no-browser] [--lan]   (실행 권한이 없으면: bash start_mac.sh, 또는 chmod +x *.sh)
#       APP_ENV=prod ./start_mac.sh             (.env.local의 APP_ENV 대신)
#   --lan  화면을 이 Mac 밖(태블릿·Tailscale)에서도 열 수 있게 한다.
#          개발 설정은 인증이 꺼져 있으니 믿을 수 있는 네트워크에서만.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOGS="$ROOT/logs"
WEB="$ROOT/web"
PY="$ROOT/.venv/bin/python"
OPEN_BROWSER=1
VITE_HOST_ARG=""
for arg in "$@"; do
  case "$arg" in
    --no-browser) OPEN_BROWSER=0 ;;
    --lan) VITE_HOST_ARG="--host" ;;
    *) echo "모르는 옵션: $arg (쓸 수 있는 것: --no-browser, --lan)"; exit 2 ;;
  esac
done
mkdir -p "$LOGS"
cd "$ROOT"

need() { command -v "$1" >/dev/null 2>&1 || { echo "[오류] '$1'을(를) 찾지 못했어요. $2"; exit 1; }; }
alive() { local f="$LOGS/$1.pid"; [ -f "$f" ] && kill -0 "$(cat "$f")" 2>/dev/null; }
port_pid() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -n1 || true; }
probe_host() { case "${1:-}" in "" | 0.0.0.0 | "::") echo 127.0.0.1 ;; *) echo "$1" ;; esac; }

# ---- 1. 처음 한 번: .env.local, 가상환경, 화면 의존성 ----
if [ ! -f "$ROOT/.env.local" ]; then
  cp "$ROOT/.env.example" "$ROOT/.env.local"
  echo ".env.local 이 없어 .env.example 을 복사해 만들었어요. 주소·포트·Ollama 노드는 여기서 고쳐요."
fi
need npm "Node.js 20 이상을 설치해 주세요 (brew install node)."
need curl "curl이 필요해요."
need lsof "lsof가 필요해요."
if [ ! -x "$PY" ]; then
  need python3 "Python 3.11 이상을 설치해 주세요 (brew install python@3.12)."
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || { echo "[오류] Python 3.11 이상이 필요해요 (지금: $(python3 --version))."; exit 1; }
  echo "가상환경(.venv)을 만들어요. 처음 한 번만, 몇 분 걸려요..."
  python3 -m venv "$ROOT/.venv"
  "$PY" -m pip install --upgrade pip
  "$PY" -m pip install -e "$ROOT[dev]"
fi
if [ ! -d "$WEB/node_modules" ]; then
  echo "화면 의존성(web/node_modules)을 설치해요. 처음 한 번만..."
  npm --prefix "$WEB" install --no-audit --no-fund
fi

# ---- 2. 주소·포트 정하기 (백엔드와 같은 규칙: 기본값 < config/<APP_ENV>.env < .env.local < 환경 변수) ----
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
CFG="$("$PY" -m app config --ports)" || { echo "[오류] 설정을 읽지 못했어요 (.env.local 확인: .venv/bin/python -m app config)"; exit 1; }
cfg() { printf '%s\n' "$CFG" | sed -n "s/^$1=//p"; }
APP_ENV="$(cfg APP_ENV)"; HOST="$(cfg HOST)"; PORT="$(cfg PORT)"; WEB_HOST="$(cfg WEB_HOST)"; WEB_PORT="$(cfg WEB_PORT)"
[ -n "$PORT" ] && [ -n "$WEB_PORT" ] || { echo "[오류] PORT/WEB_PORT를 정하지 못했어요."; exit 1; }
# 두 프로세스가 똑같은 값을 보도록 환경 변수로 넘긴다(Vite는 이 값을 .env.local보다 먼저 본다)
export APP_ENV HOST PORT WEB_HOST WEB_PORT
API_PROBE="$(probe_host "$HOST")"
if [ -n "$VITE_HOST_ARG" ]; then WEB_PROBE=127.0.0.1; else WEB_PROBE="$(probe_host "$WEB_HOST")"; fi

# ---- 3. 이미 돌고 있거나 포트가 막혀 있으면 멈춘다 ----
for name in backend frontend; do
  if alive "$name"; then
    echo "[중지] 이미 실행 중이에요 ($name, PID $(cat "$LOGS/$name.pid")). 먼저 ./stop_mac.sh 를 실행해 주세요."
    exit 1
  fi
  rm -f "$LOGS/$name.pid"
done
for pair in "PORT $PORT" "WEB_PORT $WEB_PORT"; do
  set -- $pair
  owner="$(port_pid "$2")"
  if [ -n "$owner" ]; then
    echo "[중지] 포트 $2 을(를) 다른 프로그램이 쓰고 있어요 (PID $owner, $(ps -o comm= -p "$owner"))."
    echo "       이 프로젝트가 띄운 것이면 ./stop_mac.sh 로 끄고, 아니면 .env.local 의 $1 을 바꿔 주세요."
    exit 1
  fi
done

# ---- 4. 백그라운드 실행 ----
export NO_COLOR=1 FORCE_COLOR=0
stamp="$(date '+%Y-%m-%d %H:%M:%S')"
printf 'PORT=%s\nWEB_PORT=%s\n' "$PORT" "$WEB_PORT" > "$LOGS/run.env"

printf '\n===== %s 시작 (backend, APP_ENV=%s, 포트 %s) =====\n' "$stamp" "$APP_ENV" "$PORT" >> "$LOGS/backend.log"
nohup "$PY" -m app serve >> "$LOGS/backend.log" 2>&1 < /dev/null &
echo $! > "$LOGS/backend.pid"

printf '\n===== %s 시작 (frontend, 포트 %s) =====\n' "$stamp" "$WEB_PORT" >> "$LOGS/frontend.log"
if [ -n "$VITE_HOST_ARG" ]; then
  nohup npm --prefix "$WEB" run dev -- --host >> "$LOGS/frontend.log" 2>&1 < /dev/null &
else
  nohup npm --prefix "$WEB" run dev >> "$LOGS/frontend.log" 2>&1 < /dev/null &
fi
echo $! > "$LOGS/frontend.pid"

# ---- 5. 뜰 때까지 기다린다 ----
wait_ready() { # 이름 URL
  local pid end
  pid="$(cat "$LOGS/$1.pid")"
  end=$((SECONDS + 90))
  while [ "$SECONDS" -lt "$end" ]; do
    kill -0 "$pid" 2>/dev/null || return 1
    curl -fsS -o /dev/null --max-time 2 "$2" 2>/dev/null && return 0
    sleep 0.7
  done
  return 1
}

echo "띄우는 중..."
for svc in "backend http://$API_PROBE:$PORT/healthz" "frontend http://$WEB_PROBE:$WEB_PORT/"; do
  set -- $svc
  if ! wait_ready "$1" "$2"; then
    echo "[실패] $1 이(가) 뜨지 않았어요. 로그 끝부분:"
    tail -n 25 "$LOGS/$1.log" | sed 's/^/  /'
    "$ROOT/stop_mac.sh" --quiet || bash "$ROOT/stop_mac.sh" --quiet
    exit 1
  fi
done

WEB_URL="http://localhost:$WEB_PORT"
echo ""
echo "실행 중 (백그라운드, APP_ENV=$APP_ENV)"
echo "  화면:   $WEB_URL   (Vite 개발 서버, 고치면 바로 반영)"
echo "  백엔드: http://$API_PROBE:$PORT   (API 문서 /docs)"
echo "  설정:   .env.local   (지금 값 보기: .venv/bin/python -m app config)"
echo "  로그:   logs/backend.log, logs/frontend.log   (tail -f logs/backend.log)"
echo "  PID:    backend $(cat "$LOGS/backend.pid"), frontend $(cat "$LOGS/frontend.pid")"
if [ -n "$VITE_HOST_ARG" ]; then
  echo "  태블릿: http://<이 Mac의 Tailscale 이름 또는 IP>:$WEB_PORT  (logs/frontend.log의 Network 주소)"
fi
echo "  끄기:   ./stop_mac.sh"
if [ "$OPEN_BROWSER" = 1 ]; then
  open "$WEB_URL" || true
fi
