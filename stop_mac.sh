#!/usr/bin/env bash
# start_mac.sh로 띄운 백엔드·프런트엔드를 강제 종료한다(kill -9, 자식 프로세스까지).
#   1. logs/*.pid 에 적힌 PID와 그 자식들
#   2. PID 파일이 없거나 남은 것이 있으면 백엔드·화면 포트를 잡은 프로세스 중
#      이 프로젝트 것(명령줄에 프로젝트 경로, "-m app serve", "vite"가 있는 것)만
#      포트는 logs/run.env(start가 실제로 쓴 값) → python -m app config --ports(.env.local) → 8000·5173 순으로 정한다.
# 사용: ./stop_mac.sh   (실행 권한이 없으면: bash stop_mac.sh)
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOGS="$ROOT/logs"
QUIET=0
[ "${1:-}" = "--quiet" ] && QUIET=1
killed=()

# 자식부터 모두 모은 뒤 한꺼번에 죽인다(부모를 먼저 죽이면 자식이 고아가 되어 못 찾는다)
tree() {
  local pid="$1" child
  echo "$pid"
  for child in $(pgrep -P "$pid" 2>/dev/null); do tree "$child"; done
}
# 포트를 잡은 프로세스에서 위로 올라가며 이 프로젝트 것(npm 등)까지 찾아 맨 위에서부터 죽인다
our_top() {
  local pid="$1" ppid i
  for i in 1 2 3 4 5 6; do
    ppid="$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')"
    [ -n "$ppid" ] && [ "$ppid" -gt 1 ] || break
    case "$(ps -o command= -p "$ppid" 2>/dev/null)" in
      *"$ROOT"*) pid="$ppid" ;;
      *) break ;;
    esac
  done
  echo "$pid"
}
kill_tree() {
  local pid="$1" why="$2" pids
  kill -0 "$pid" 2>/dev/null || return 0
  pids="$(tree "$pid" | tr '\n' ' ')"
  # shellcheck disable=SC2086
  kill -9 $pids 2>/dev/null || true
  killed+=("$why (PID $pid)")
}

for name in backend frontend; do
  f="$LOGS/$name.pid"
  if [ -f "$f" ]; then
    pid="$(tr -dc '0-9' < "$f")"
    [ -n "$pid" ] && kill_tree "$pid" "$name"
    rm -f "$f"
  fi
done

ports() {
  local src="" p w
  if [ -f "$LOGS/run.env" ]; then
    src="$(cat "$LOGS/run.env")"
  elif [ -x "$ROOT/.venv/bin/python" ]; then
    src="$(cd "$ROOT" && PYTHONUTF8=1 "$ROOT/.venv/bin/python" -m app config --ports 2>/dev/null || true)"
  fi
  p="$(printf '%s\n' "$src" | sed -n 's/^PORT=\([0-9][0-9]*\)$/\1/p')"
  w="$(printf '%s\n' "$src" | sed -n 's/^WEB_PORT=\([0-9][0-9]*\)$/\1/p')"
  echo "${p:-8000} ${w:-5173}"
}

sleep 0.3
for port in $(ports); do
  for pid in $(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null); do
    cmd="$(ps -o command= -p "$pid" 2>/dev/null || true)"
    case "$cmd" in
      *"$ROOT"* | *"-m app serve"* | *vite*) kill_tree "$(our_top "$pid")" "포트 $port" ;;
      *) [ "$QUIET" = 1 ] || echo "포트 $port 의 PID $pid 은(는) 이 프로젝트 프로세스가 아니라 그대로 둬요: $cmd" ;;
    esac
  done
done
rm -f "$LOGS/run.env"

stamp="$(date '+%Y-%m-%d %H:%M:%S')"
if [ "${#killed[@]}" -gt 0 ]; then
  for name in backend frontend; do
    [ -f "$LOGS/$name.log" ] && printf '===== %s 종료 (stop_mac) =====\n' "$stamp" >> "$LOGS/$name.log"
  done
  if [ "$QUIET" = 0 ]; then
    echo "강제 종료했어요:"
    for k in "${killed[@]}"; do echo "  $k"; done
  fi
elif [ "$QUIET" = 0 ]; then
  echo "실행 중인 프로세스가 없어요."
fi
exit 0
