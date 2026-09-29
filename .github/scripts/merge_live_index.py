#!/usr/bin/env python3
"""★19 라이브 녹음 결과(transcripts/live/<id>.json)를 transcripts/index.json 에 반영한다.

라이브 녹음(record-live.yml)과 수집기(fetch-transcripts.yml)는 서로 다른 실행에서
같은 index.json 을 고친다. 수집기의 Commit 단계는 충돌하면 자기 쪽(rebase -X theirs)을
택하므로, 녹음이 올린 ok 항목이 수집기의 ok:false 로 덮일 수 있다.
그래서 녹음 결과는 영상별 사이드카 파일에도 남기고, 두 워크플로 모두 커밋 직전에
이 스크립트로 사이드카를 index.json 에 다시 반영한다. .enc 가 있는 것만 반영한다.

출력: changed / same
"""
import glob
import json
import os
import time

OUT = "transcripts"
IDX = os.path.join(OUT, "index.json")
KEEP_DAYS = 45

index = {}
if os.path.exists(IDX):
    try:
        index = json.load(open(IDX, encoding="utf-8"))
    except Exception:
        index = {}

changed = False
for p in glob.glob(os.path.join(OUT, "live", "*.json")):
    vid = os.path.splitext(os.path.basename(p))[0]
    try:
        entry = json.load(open(p, encoding="utf-8"))
    except Exception:
        continue
    ep = entry.get("uploaded_epoch") or 0
    if ep and ep < time.time() - KEEP_DAYS * 86400:
        os.remove(p)          # 수집기가 .enc 를 정리하는 기준(45일)과 맞춘다
        continue
    if not os.path.exists(os.path.join(OUT, f"{vid}.enc")):
        continue
    if index.get(vid) != entry:
        index[vid] = entry
        changed = True

if changed:
    json.dump(index, open(IDX, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, sort_keys=True)
print("changed" if changed else "same")
