#!/bin/bash
# 발송 워크플로(send-briefing.yml) 실행이 끝날 때까지 기다린다.
#
# 사용법:
#   date -u +%Y-%m-%dT%H:%M:%SZ > /tmp/hkgm_S0        # actions_run_trigger 직전에 적는다
#   bash /tmp/hkgm/briefing/wait_send.sh <YYYY-MM-DD>
#
# 30초 간격으로 GitHub API(인증 없음)를 읽어 S0 이후 만들어진 "briefing <date>" 실행을 찾는다. 최대 15분.
# 출력: SENT <url> / FAILED <conclusion> <url> / TIMEOUT
# 종료 코드: 0 발송 성공, 2 시간 초과(실행을 못 찾았거나 안 끝남), 3 사용법·S0 오류, 4 실행 실패
{
set -u
DATE="${1:-}"
[[ "$DATE" =~ ^20[0-9]{2}-[0-9]{2}-[0-9]{2}$ ]] || { sed -n '4,6p' "$0"; exit 3; }
S0=$(cat /tmp/hkgm_S0 2>/dev/null | tr -d '[:space:]')
[[ "$S0" =~ ^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9:]{8}Z$ ]] || { echo "S0 오류: /tmp/hkgm_S0 에 UTC 시각이 없다(값: '$S0')"; exit 3; }
API="${WAIT_API_URL:-https://api.github.com/repos/lds96054341/hkgm-transcripts/actions/workflows/send-briefing.yml/runs?per_page=10}"
INTERVAL="${WAIT_INTERVAL:-30}"
POLLS="${WAIT_POLLS:-30}"

for i in $(seq 1 "$POLLS"); do
  R=$(curl -sS --max-time 20 "$API" 2>/dev/null | python3 -c '
import json, sys
s0, date = sys.argv[1], sys.argv[2]
try:
    runs = json.load(sys.stdin).get("workflow_runs", [])
except Exception:
    sys.exit(0)
runs = [r for r in runs if r.get("created_at", "") >= s0 and (r.get("display_title") or "").startswith("briefing " + date)]
if runs:
    r = max(runs, key=lambda r: r["created_at"])
    print(r.get("status"), r.get("conclusion") or "-", r.get("html_url"))
' "$S0" "$DATE")
  if [ -n "$R" ]; then
    read -r STATUS CONCL URL <<< "$R"
    if [ "$STATUS" = "completed" ]; then
      if [ "$CONCL" = "success" ]; then echo "SENT $URL"; exit 0; fi
      echo "FAILED $CONCL $URL"; exit 4
    fi
  fi
  [ "$i" -lt "$POLLS" ] && sleep "$INTERVAL"
done
echo "TIMEOUT ${R:-실행을 찾지 못함}"
exit 2
}
