#!/usr/bin/env python3
"""★19 한경 글로벌마켓 라이브를 방송 중에 녹음해 음성 받아쓰기로 남긴다.

월스트리트나우(월나우)는 방송이 끝나면 채널 멤버십 전용으로 바뀌어(2026-09-30 확인)
방송 뒤에 도는 수집기로는 자막도 오디오도 받을 수 없다. 방송 중에는 공개라서,
라이브가 시작되면 yt-dlp --live-from-start 로 오디오를 처음부터 받아 두고
방송이 끝나면 Whisper 로 받아쓴다.

결과는 수집기와 같은 형식으로 transcripts/<id>.enc 에 암호화해 두고,
색인 항목은 _out/live/<id>.json 에 남긴다. 커밋은 워크플로의 Commit 단계가
최신 main 위에서 하고, index.json 반영은 merge_live_index.py 가 한다.

환경변수
  YT_COOKIES, TRANSCRIPT_KEY  수집기와 같은 시크릿
  VIDEO_ID                    이 영상만 기다려 녹음(수동 실행용). 없으면 채널에서 찾는다.
  POLL_UNTIL_KST              라이브를 찾는 마감(HH:MM, 기본 07:40). VIDEO_ID 가 있으면 시작 후 90분.
  TITLE_FILTER                제목 정규식(비우면 채널의 모든 라이브)
결과는 _out/result.txt 에 한 줄로 남긴다(recorded / no_live / failed: …).
"""
import glob
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
CHANNEL = {"key": "hkgm", "name": "한경 글로벌마켓", "id": "UCWskYkV4c4S9D__rsfOl2JA"}
CLIENTS = ["default", "tv", "web_safari", "mweb"]
TMP, STAGE = "_live_tmp", "_out"
POLL_SEC = 90
REC_TIMEOUT = 130 * 60        # 녹음 한 번의 최대 시간(월나우는 40분 안팎)
MIN_COVERAGE = 0.5            # 받은 오디오가 방송 길이의 절반도 안 되면 버린다
WHISPER_MODEL = "small"
DOMAIN_PROMPT = (
    "미국 증시와 반도체 시장 브리핑입니다. "
    "엔비디아, 삼성전자, SK하이닉스, 마이크론, 브로드컴, TSMC, 인텔, AMD, "
    "HBM, 파운드리, 오픈AI, 앤트로픽, 팔란티어, 테슬라, 애플, 알파벳, "
    "연준, FOMC, 파월, 워시 의장, 국채금리, 나스닥, S&P500, 다우, 코스피, "
    "환율, 관세, 희토류, CATL, BYD 등이 언급됩니다."
)

os.makedirs(os.path.join(STAGE, "live"), exist_ok=True)


def result(msg):
    open(os.path.join(STAGE, "result.txt"), "w", encoding="utf-8").write(msg + "\n")
    print("[결과] " + msg)


KEY = os.environ.get("TRANSCRIPT_KEY", "").strip()
if not KEY:
    result("failed: TRANSCRIPT_KEY 시크릿이 없음")
    raise SystemExit(1)

base = []
if os.environ.get("YT_COOKIES", "").strip():
    with open("cookies.txt", "w") as f:
        f.write(os.environ["YT_COOKIES"])
    base += ["--cookies", "cookies.txt"]
base += ["--sleep-requests", "1.5"]


class _Fail:
    def __init__(self, msg):
        self.returncode, self.stdout, self.stderr = 1, "", msg


def run(args, timeout=300):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return _Fail(f"타임아웃({timeout}초) 초과")
    except Exception as e:
        return _Fail(f"실행 실패: {type(e).__name__}: {str(e)[-200:]}")


def last_error(stderr):
    lines = [l.strip() for l in (stderr or "").splitlines() if l.strip()]
    err = [l for l in lines if l.startswith("ERROR")]
    return (err[-1] if err else (lines[-1] if lines else "(출력 없음)"))[:200]


def probe(url):
    """(id, live_status, title, release_timestamp) 또는 None"""
    r = run(["yt-dlp", "--skip-download", "--ignore-no-formats-error", "--no-warnings",
             "--print", "%(id)s\t%(live_status)s\t%(title)s\t%(release_timestamp)s",
             *base, url], timeout=120)
    for line in (r.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) == 4 and len(parts[0]) == 11:
            ts = int(parts[3]) if parts[3].isdigit() else 0
            return parts[0], parts[1], parts[2], ts
    return None


def candidates():
    """채널 /streams 탭 최근 5건의 videoId"""
    r = run(["yt-dlp", "--flat-playlist", "--playlist-end", "5", "--print", "%(id)s",
             *base, f"https://www.youtube.com/channel/{CHANNEL['id']}/streams"], timeout=120)
    return [l.strip() for l in (r.stdout or "").splitlines() if len(l.strip()) == 11]


def already_done(vid):
    idx = os.path.join("transcripts", "index.json")
    try:
        e = json.load(open(idx, encoding="utf-8")).get(vid, {})
    except Exception:
        e = {}
    return e.get("ok") and os.path.exists(os.path.join("transcripts", f"{vid}.enc"))


def find_live():
    """라이브가 시작될 때까지 기다린다. (id, title, release_ts) 또는 None"""
    want = os.environ.get("VIDEO_ID", "").strip()
    pat = os.environ.get("TITLE_FILTER", "").strip()
    pat = re.compile(pat) if pat else None
    now = datetime.now(KST)
    if want:
        until = now + timedelta(minutes=90)
    else:
        hh, mm = map(int, (os.environ.get("POLL_UNTIL_KST") or "07:40").split(":"))
        until = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    print(f"[i] 라이브 찾기: {'videoId ' + want if want else '채널 ' + CHANNEL['name']} — {until:%H:%M} KST까지")
    finished = set()          # 이미 끝났거나 라이브가 아닌 영상은 다시 묻지 않는다
    while True:
        ids = [want] if want else ([None] + candidates())
        seen = []
        for vid in ids:
            if vid in finished:
                continue
            url = (f"https://www.youtube.com/watch?v={vid}" if vid
                   else f"https://www.youtube.com/channel/{CHANNEL['id']}/live")
            p = probe(url)
            if not p:
                continue
            pid, status, title, rts = p
            seen.append(f"{pid}:{status}")
            if status == "is_live":
                if already_done(pid):
                    print(f"[i] {pid} 이미 받아 둠 — 건너뜀")
                    finished.add(pid)
                elif pat and not pat.search(title):
                    print(f"[i] {pid} 라이브지만 제목 필터에 안 맞음: {title}")
                    finished.add(pid)
                else:
                    print(f"[+] 라이브 발견: {pid} {title}")
                    return pid, title, rts
            elif status in ("was_live", "not_live", "post_live") and vid:
                finished.add(vid)
        print(f"[i] {datetime.now(KST):%H:%M:%S} 확인 {len(ids)}건 → {' '.join(seen) or '응답 없음'}")
        if datetime.now(KST) >= until:
            return None
        time.sleep(POLL_SEC)


def record(vid):
    """방송 처음부터 끝까지 오디오를 받는다. (파일 경로, 녹음 종료 epoch, 오류)"""
    url = f"https://www.youtube.com/watch?v={vid}"
    errs = []
    attempts = [(c, True) for c in ("default", "web_safari", "tv")] + [("default", False)]
    for client, from_start in attempts:
        shutil.rmtree(TMP, ignore_errors=True)
        os.makedirs(TMP, exist_ok=True)
        args = ["yt-dlp", "-f", "bestaudio/best", "--no-part",
                "--retries", "10", "--fragment-retries", "10", "--socket-timeout", "30",
                "--extractor-args", f"youtube:player_client={client}",
                "-o", os.path.join(TMP, "%(id)s.%(ext)s"), *base, url]
        if from_start:
            args.insert(1, "--live-from-start")
        t0 = time.time()
        print(f"[i] 녹음 시작: client={client} live_from_start={from_start}")
        r = run(args, timeout=REC_TIMEOUT)
        files = [p for p in glob.glob(os.path.join(TMP, f"{vid}*"))
                 if not p.endswith((".json", ".ytdl")) and os.path.getsize(p) > 1_000_000]
        took = int(time.time() - t0)
        if files:
            print(f"[i] 녹음 끝: {took}초, {os.path.getsize(files[0]) // 1_000_000}MB")
            return max(files, key=os.path.getsize), time.time(), ""
        errs.append(f"[{client}/{'start' if from_start else 'now'}] {last_error(r.stderr)}")
        print("[!] " + errs[-1])
        # 방송이 이미 끝났으면(멤버십 전환 등) 더 시도해도 소용없다
        p = probe(url)
        if not p or p[1] != "is_live":
            break
        time.sleep(5)
    return None, time.time(), " | ".join(errs)[-600:]


def audio_seconds(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path], timeout=60)
    try:
        return float((r.stdout or "0").strip())
    except ValueError:
        return 0.0


def bucketize(pairs, bucket=30):
    """[(초, 텍스트)] → '[HH:MM:SS] …' 30초 블록 문자열 (수집기와 같은 형식)"""
    blocks, cur, buf, last = [], None, [], None
    for t, txt in pairs:
        if txt == last:
            continue
        last = txt
        k = int(t // bucket) * bucket
        if cur is None:
            cur = k
        if k != cur:
            if buf:
                blocks.append((cur, " ".join(buf)))
            cur, buf = k, []
        buf.append(txt)
    if buf:
        blocks.append((cur, " ".join(buf)))
    out = []
    for t, txt in blocks:
        hh, rem = divmod(int(t), 3600)
        mm, ss = divmod(rem, 60)
        out.append(f"[{hh:02d}:{mm:02d}:{ss:02d}] {txt}")
    return "\n".join(out)


def encrypt_to(text, dest):
    src = os.path.join(TMP, "_plain.txt")
    with open(src, "w", encoding="utf-8") as f:
        f.write(text)
    r = subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000",
                        "-salt", "-a", "-in", src, "-out", dest, "-pass", "env:TRANSCRIPT_KEY"],
                       capture_output=True, text=True)
    os.remove(src)
    if r.returncode != 0:
        raise SystemExit("[!] 암호화 실패: " + (r.stderr or "")[-300:])


def main():
    found = find_live()
    if not found:
        result("no_live: 마감까지 라이브가 시작되지 않음")
        return
    vid, title, rts = found
    rec_start = time.time()
    apath, rec_end, err = record(vid)
    if not apath:
        result(f"failed: {vid} 녹음 실패 — {err}")
        return

    adur = audio_seconds(apath)
    # 방송 길이 추정: 실제 시작 시각(release_timestamp)부터 녹음 종료까지. 모르면 녹음 시간.
    expect = rec_end - (rts if rts and rts <= rec_start else rec_start)
    coverage = round(min(1.0, adur / expect), 2) if expect > 0 and adur else 0.0
    print(f"[i] 오디오 {int(adur)}초 / 방송 추정 {int(expect)}초 → 포함률 {coverage}")
    if coverage < MIN_COVERAGE:
        os.remove(apath)
        result(f"failed: {vid} 받은 오디오가 방송의 {int(coverage * 100)}%뿐 — 버림")
        return

    from faster_whisper import WhisperModel
    t0 = time.time()
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    try:
        segs, _ = model.transcribe(apath, language="ko", vad_filter=True, beam_size=5,
                                   initial_prompt=DOMAIN_PROMPT)
        pairs = [(s.start, s.text.strip()) for s in segs if s.text.strip()]
    finally:
        os.remove(apath)          # 음성 파일은 즉시 삭제
    print(f"[i] 받아쓰기 {int(time.time() - t0)}초")
    if not pairs:
        result(f"failed: {vid} 받아쓰기 결과가 비어 있음")
        return

    body = bucketize(pairs)
    ts = rts or int(rec_start)
    dur = int(adur)
    lang = f"whisper-{WHISPER_MODEL}"
    header = (f"# videoId: {vid}\n# channel: {CHANNEL['name']}\n# title: {title}\n"
              f"# uploaded_kst: {datetime.fromtimestamp(ts, KST):%Y-%m-%d %H:%M KST}\n"
              f"# uploaded_epoch: {ts}\n# duration_sec: {dur}\n"
              f"# source: audio (라이브 녹음 후 음성 받아쓰기(Whisper))\n"
              f"# lang: {lang}\n# client: live-record\n# live_coverage: {coverage}\n"
              f"# note: 30초 단위 블록, [HH:MM:SS]는 영상 내 위치\n\n")
    encrypt_to(header + body + "\n", os.path.join(STAGE, f"{vid}.enc"))
    entry = {"ok": True, "channel": CHANNEL["key"], "title": title,
             "uploaded_epoch": ts, "duration_sec": dur, "source": "audio",
             "lang": lang, "chars": len(body), "live_record": True, "coverage": coverage}
    json.dump(entry, open(os.path.join(STAGE, "live", f"{vid}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, sort_keys=True)
    result(f"recorded: {vid} {len(body)}자, 포함률 {coverage}")


try:
    main()
finally:
    shutil.rmtree(TMP, ignore_errors=True)
    if os.path.exists("cookies.txt"):
        os.remove("cookies.txt")
