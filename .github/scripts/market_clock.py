#!/usr/bin/env python3
"""★27 미국 서머타임(DST)에 따라 월나우 녹음 시간표(KST)를 정한다.

월나우는 뉴욕 증시 마감(16:00 ET) 뒤에 방송한다. 마감은 미국 서머타임(EDT) 중이면 KST 05:00,
서머타임이 아니면(EST) KST 06:00 이라 방송 시각도 한 시간씩 움직인다.
  - 2026-10: EDT, 월나우 06:30~07:20 시작
  - 2026-11-01 서머타임 해제 뒤: EST, 월나우 07:00~08:30 시작
그래서 시각을 고정하지 않고, 지금 뉴욕이 서머타임인지 보고 마감 시각 기준으로 계산한다.
서머타임 시작(3월 둘째 일요일)·해제(11월 첫째 일요일)는 zoneinfo 의 America/New_York 규칙을 따른다.
전환은 일요일 새벽(ET)이라 방송일(KST 화~토 = ET 월~금)에는 실행 시점과 마감 시점의 서머타임 여부가 같다.

시간표(마감 기준, 괄호는 EDT / EST 일 때 KST)
  handoff      마감 -60분  (04:00 / 05:00)  이보다 일찍 뜬 record-live 는 이때 새 실행에 넘긴다(330분 상한)
  wait_start   마감 +60분  (06:00 / 07:00)  record-live 가 라이브를 찾기 시작하는 시각
  warn_after   마감 +100분 (06:40 / 07:40)  수집기가 '녹음 없음' 경고를 내기 시작하는 시각
  deadline     마감 +180분 (08:00 / 09:00)  라이브를 찾는 마감
  caption_cap  마감 +210분 (08:30 / 09:30)  녹음 실패 시 자막 대체를 기다리는 마감

명령줄로 실행하면 key=value 를 출력한다(워크플로에서 $GITHUB_OUTPUT 으로 쓴다).
  python3 market_clock.py [ISO 시각]     예) python3 market_clock.py 2026-11-06T05:00:00+09:00
"""
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

KST = timezone(timedelta(hours=9))
ET = ZoneInfo("America/New_York")

OFFSETS_MIN = {            # 마감(16:00 ET) 기준 분
    "handoff": -60,
    "wait_start": 60,
    "warn_after": 100,
    "deadline": 180,
    "caption_cap": 210,
}


def schedule(now=None):
    """오늘(KST) 방송의 시간표. dict: dst(bool), zone('EDT'|'EST'), close·각 시각(KST datetime)"""
    now = (now or datetime.now(KST)).astimezone(KST)
    # 오늘 KST 방송의 기준이 되는 뉴욕 거래일 = KST 날짜의 전날(ET). 그날 16:00 ET 를 KST 로 바꾼다.
    trade_day = (now - timedelta(days=1)).date()
    close_et = datetime(trade_day.year, trade_day.month, trade_day.day, 16, 0, tzinfo=ET)
    dst = bool(close_et.dst())
    close = close_et.astimezone(KST)
    out = {"dst": dst, "zone": "EDT" if dst else "EST", "close": close}
    for k, m in OFFSETS_MIN.items():
        out[k] = close + timedelta(minutes=m)
    return out


def describe(s):
    return (f"미국 {'서머타임(EDT)' if s['dst'] else '표준시(EST)'} — 뉴욕 마감 {s['close']:%H:%M} KST · "
            f"라이브 찾기 {s['wait_start']:%H:%M}~{s['deadline']:%H:%M} KST")


if __name__ == "__main__":
    now = datetime.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else None
    s = schedule(now)
    print(f"zone={s['zone']}")
    print(f"dst={'true' if s['dst'] else 'false'}")
    for k in ("close", *OFFSETS_MIN):
        print(f"{k}={s[k]:%H:%M}")
        print(f"{k}_epoch={int(s[k].timestamp())}")
    print(f"summary={describe(s)}")
