#!/bin/bash
# 수집기 수동 실행(workflow_dispatch) 결과가 main 에 올라올 때까지 기다린다.
#
# 사용법:
#   date -u +%Y-%m-%dT%H:%M:%SZ > /tmp/hkgm_T0        # 수집기 실행 직전에 적는다
#   bash /tmp/hkgm/briefing/wait_collector.sh [--deadline-kst HH:MM] <videoId> [videoId ...]
#
# 실행 시각 T0 는 셸 변수가 아니라 /tmp/hkgm_T0 파일에서 읽는다(Bash 호출끼리 변수가 이어지지 않는다).
# 2분 간격으로 저장소를 새로 clone 해서 확인한다. 최대 45분, --deadline-kst 를 주면 그 시각(KST)까지 중 이른 쪽.
# 마감이 이미 지났어도 한 번은 확인한다.
# 끝나는 조건은 셋 중 하나다.
#   - 넘긴 영상 모두 transcripts/<id>.enc 가 있고 index.json 에서 ok 다.
#   - status.json 의 last_run_utc 가 T0 이후다(수동 실행이 끝나 커밋까지 됐다).
#   - GitHub API 에서 도는·대기 중인 수집기 실행이 하나도 없고, T0 이후 가장 나중 실행이 성공하지 못했다.
#     (대기 중인 수동 실행이 새 예약 실행에 밀려 취소된 경우는 새 실행이 끝날 때까지 기다린다. API 를 못 읽으면 건너뛴다.)
# 끝나면 /tmp/hkgm 를 그 최신 clone 으로 바꾸고 영상마다 한 줄씩 결과를 출력한다.
#   <id> OK <caption|audio> <글자 수>자
#   <id> MISSING <state> retry=<yes|no|stale> <오류 요약>
#     yes = 방송 직후 준비 중이라 10분 뒤 다시 돌릴 만하다. stale = 상태가 T0 이전 것이라 판단 근거가 없다.
# 종료 코드: 0 모두 확보, 1 수동 실행은 끝났지만 일부 없음, 2 마감 초과, 3 사용법·T0 오류,
#           4 T0 이후 실행이 모두 끝났는데 성공한 실행이 없음.
#
# 스크립트 전체를 { } 로 감싸 먼저 다 읽게 했다. 도중에 /tmp/hkgm 를 바꿔도 안전하다.
{
set -u
DEADLINE_KST=""
if [ "${1:-}" = "--deadline-kst" ]; then
  DEADLINE_KST="${2:-}"; shift 2 || true
fi
if [ $# -lt 1 ]; then
  sed -n '4,6p' "$0"
  exit 3
fi
IDS="$*"
T0_FILE="/tmp/hkgm_T0"
REPO="https://github.com/lds96054341/hkgm-transcripts.git"
API="${WAIT_API_URL:-https://api.github.com/repos/lds96054341/hkgm-transcripts/actions/workflows/fetch-transcripts.yml/runs?per_page=5}"
INTERVAL="${WAIT_INTERVAL:-120}"   # 테스트용 덮어쓰기(WAIT_INTERVAL, WAIT_API_URL)
NEW="/tmp/hkgm_collector_check"

# T0 확인: 파일이 있고, 시간대가 붙은 ISO 시각이어야 한다.
T0=$(cat "$T0_FILE" 2>/dev/null | tr -d '[:space:]')
if ! python3 - "$T0" <<'PY'
import sys
from datetime import datetime
try:
    t = datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
    sys.exit(0 if t.tzinfo else 1)
except Exception:
    sys.exit(1)
PY
then
  echo "T0 오류: $T0_FILE 에 시간대가 붙은 UTC 시각이 없다(값: '${T0}'). 수집기 실행 직전에 date -u +%Y-%m-%dT%H:%M:%SZ > $T0_FILE 를 먼저 한다."
  exit 3
fi

# 최대 확인 횟수: 45분(2분 간격 23회), --deadline-kst 가 더 이르면 그때까지. 최소 1회.
POLLS=$(python3 - "$T0" "$DEADLINE_KST" 2>/dev/null <<'PY'
import sys
from datetime import datetime, timezone, timedelta
t0 = datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
end = t0 + timedelta(minutes=45)
d = sys.argv[2]
if d:
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    hh, mm = map(int, d.split(":"))
    dl = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    end = min(end, dl)
left = (end - datetime.now(timezone.utc)).total_seconds()
print(max(1, min(23, int(left // 120))))
PY
) || { echo "--deadline-kst 는 HH:MM 형식이다"; exit 3; }
echo "T0=$T0, 최대 ${POLLS}회 확인(2분 간격)"

report() {
  rm -rf /tmp/hkgm && mv "$NEW" /tmp/hkgm
  python3 - /tmp/hkgm "$T0" $IDS <<'PY'
import json, os, sys
from datetime import datetime
root, t0, ids = sys.argv[1], sys.argv[2], sys.argv[3:]
st = json.load(open(os.path.join(root, "status.json"), encoding="utf-8"))
idx = json.load(open(os.path.join(root, "transcripts", "index.json"), encoding="utf-8"))
res = {r.get("id"): r for r in st.get("results", [])}
last = st.get("last_run_utc") or ""
p = lambda x: datetime.fromisoformat(x.replace("Z", "+00:00"))
try:
    fresh = bool(last) and p(last) > p(t0)   # T0 이후 실행이 쓴 상태인가
except Exception:
    fresh = False
print("last_run_utc:", last)
for v in ids:
    e = idx.get(v, {})
    if os.path.exists(os.path.join(root, "transcripts", f"{v}.enc")) and e.get("ok"):
        print(f"{v} OK {e.get('source', '?')} {e.get('chars', 0)}자")
    else:
        r = res.get(v, {})
        full = r.get("error") or ""
        # 방송 직후라 아직 준비되지 않은 경우: 10분 뒤 다시 돌리면 받을 가능성이 높다
        retry = r.get("state") == "live_pending" or "PARTIAL" in full or "fragment" in full
        # 상태가 T0 이전 것이면(수동 실행이 커밋하지 못하고 끝남) 재시도 판단 근거가 아니다
        tag = ("yes" if retry else "no") if fresh else "stale"
        err = full[-200:].replace("\n", " ")
        print(f"{v} MISSING {r.get('state', '목록에 없음')} retry={tag} {err}")
PY
}

for i in $(seq 1 "$POLLS"); do
  sleep "$INTERVAL"
  rm -rf "$NEW"
  if ! git clone -q --depth 1 "$REPO" "$NEW" 2>/dev/null; then
    echo "[$i] $(date -u +%H:%M:%S) clone 실패, 다음 회차에 다시 시도"
    continue
  fi
  # 수집기 실행 상태(읽지 못하면 빈 값)
  RUN=$(curl -sS --max-time 20 "$API" 2>/dev/null | python3 -c '
import json, sys
from datetime import datetime
t0 = datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
try:
    runs = json.load(sys.stdin).get("workflow_runs", [])
except Exception:
    runs = []
mine = [r for r in runs if datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) >= t0]
# 같은 concurrency 그룹이라 도는·대기 중인 실행이 하나라도 있으면 그 실행이 결과를 올린다.
# 대기 중인 수동 실행은 새 예약 실행이 들어오면 취소되고 그 실행이 대신 돈다(취소 = 실패 아님).
busy = [r for r in runs if r.get("status") != "completed"]
if busy:
    print("active", busy[0]["status"], busy[0]["html_url"])
elif mine:
    r = mine[0]   # T0 이후 가장 나중에 만들어진 실행
    print(r["status"], r.get("conclusion") or "-", r["html_url"])
' "$T0" 2>/dev/null)
  VERDICT=$(python3 - "$NEW" "$T0" $IDS <<'PY'
import json, os, sys
from datetime import datetime
root, t0, ids = sys.argv[1], sys.argv[2], sys.argv[3:]
idx = json.load(open(os.path.join(root, "transcripts", "index.json"), encoding="utf-8"))
have = [v for v in ids
        if os.path.exists(os.path.join(root, "transcripts", f"{v}.enc")) and idx.get(v, {}).get("ok")]
if len(have) == len(ids):
    print("ALL"); sys.exit()
try:
    st = json.load(open(os.path.join(root, "status.json"), encoding="utf-8"))
    last = st.get("last_run_utc", "")
    done = bool(last) and datetime.fromisoformat(last.replace("Z", "+00:00")) > datetime.fromisoformat(t0.replace("Z", "+00:00"))
except Exception:
    last, done = "?", False
print("DONE" if done else f"WAIT {len(have)}/{len(ids)} last_run_utc={last}")
PY
)
  echo "[$i] $(date -u +%H:%M:%S) $VERDICT ${RUN:+(실행: $RUN)}"
  case "$VERDICT" in
    ALL)  report; exit 0 ;;
    DONE) report; exit 1 ;;
  esac
  case "$RUN" in
    "completed success"*|"") ;;
    completed*)
      echo "수집기 실행이 성공하지 못하고 끝났다: $RUN"
      report; exit 4 ;;
  esac
done
echo "TIMEOUT: 마감까지 수동 실행 결과가 main 에 올라오지 않았다"
exit 2
}
