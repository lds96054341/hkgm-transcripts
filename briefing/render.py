#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""아침 브리핑 렌더러.

하루치 데이터(JSON) 하나로 세 가지를 만든다.
  visual.html  - 차트가 들어간 비주얼 리포트 (Artifact로 게시)
  email.html   - 메일 본문 HTML (인라인 CSS만, 상단에 비주얼 링크)
  email.txt    - 메일 평문 본문

사용법:
  python3 briefing/render.py <data.json> <출력폴더> [--allow-old-date]

데이터 형식은 briefing/README.md, 실제 예시는 briefing/examples/2026-09-24.json.
검사에 실패하면 아무것도 쓰지 않고 종료 코드 1로 끝난다.
"""
import html, json, os, re, sys

E = html.escape

# ────────────────────────── 검사 ──────────────────────────
CONCL_MAX = 130  # 680px 메일에서 약 3줄
BULLET_MAX = 130  # 영상 카드 불릿(결론+본문 합계), 메일에서 약 3줄
BANNED = ("PLACEHOLDER", "TODO", "TBD", "lorem ipsum", "{{", "XXX")

def check(d):
    errs = []
    def need(path, cond, msg):
        if not cond: errs.append(f"{path}: {msg}")
    for k in ("date", "window", "headline", "subject_keywords", "conclusions", "tickers", "synthesis"):
        need(k, k in d and d[k], "필수 항목이 비어 있음")
    need("videos", isinstance(d.get("videos"), list), "배열이어야 함(영상이 없는 날은 빈 배열)")
    if errs: return errs
    if not ALLOW_OLD_DATE:
        import datetime
        today = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")
        need("date", d["date"] == today, f"{d['date']}는 오늘(KST {today})이 아님. 예시 파일을 그대로 쓰지 않았는지 확인. 테스트면 --allow-old-date")
    need("visual_url", "83n4vubsTdwtuCBxHrzykh" not in d.get("visual_url", "") and "Kmz2XvjyY2NsWBrkPnfTk3" not in d.get("visual_url", ""), "테스트용 옛 비주얼 링크가 남아 있음. 오늘 게시한 URL로 바꾸거나 비운다")
    need("conclusions", len(d["conclusions"]) == 3, "결론은 정확히 3줄")
    for i, c in enumerate(d["conclusions"]):
        need(f"conclusions[{i}]", len(c) <= CONCL_MAX, f"{len(c)}자. 결론 한 줄은 메일에서 최대 3줄({CONCL_MAX}자 이하)로 줄인다")
    for i, v in enumerate(d["videos"]):
        p = f"videos[{i}]"
        for k in ("channel", "id", "title", "meta", "basis", "summary", "bullets"):
            need(f"{p}.{k}", v.get(k), "비어 있음")
        need(f"{p}.channel", v.get("channel") in ("A", "B"), "A 또는 B")
        need(f"{p}.id", re.fullmatch(r"[A-Za-z0-9_-]{11}", v.get("id", "")), "videoId 11자")
        for j, b in enumerate(v.get("bullets", [])):
            need(f"{p}.bullets[{j}]", isinstance(b, list) and len(b) == 2 and all(b), "[결론, 본문] 쌍")
        need(f"{p}.bullets", len(v.get("bullets", [])) <= 12, "불릿 12개 이하")
        need(f"{p}.summary", not re.search(r"\[\d{2}:\d{2}:\d{2}\]", v.get("summary", "")), "타임스탬프 금지")
        for h, t in v.get("bullets", []):
            need(f"{p}.bullets", not re.search(r"\[\d{2}:\d{2}:\d{2}\]", h + t), "타임스탬프 금지")
        for j, b in enumerate(v.get("bullets", [])):
            if isinstance(b, list) and len(b) == 2:
                n = len(b[0]) + 1 + len(b[1])
                need(f"{p}.bullets[{j}]", n <= BULLET_MAX, f"{n}자. 불릿 하나(결론+본문)는 메일에서 최대 3줄({BULLET_MAX}자 이하)로 줄인다")
    for k in ("common", "diverge", "only_b", "critical", "samsung", "events"):
        need(f"synthesis.{k}", isinstance(d["synthesis"].get(k), list) and d["synthesis"][k], "비어 있음")
    for i, c in enumerate(d.get("charts", [])):
        p = f"charts[{i}]"
        t = c.get("type")
        need(p, t in ("diverging", "dumbbell", "ranges", "bars"), f"알 수 없는 차트 종류 {t}")
        need(f"{p}.title", c.get("title"), "제목 없음")
        if t == "diverging":
            lo, hi = c["domain"]
            for it in c["items"]:
                need(f"{p} {it['label']}", lo <= it["value"] <= hi, f"값 {it['value']}이 축 범위 {c['domain']} 밖")
        if t == "dumbbell":
            for g in c["groups"]:
                lo, hi = g["domain"]
                for r in g["rows"]:
                    need(f"{p} {r['label']}", lo <= r["from"] <= hi and lo <= r["to"] <= hi, f"값이 축 범위 {g['domain']} 밖")
        if t == "ranges":
            lo, hi = c["domain"]
            for r in c["rows"]:
                need(f"{p} {r['label']}", lo <= r["lo"] <= r["hi"] <= hi, "범위가 축 밖이거나 lo>hi")
    return errs

def check_output(name, text):
    errs = [f"{name}: 금지 문자열 '{b}' 발견" for b in BANNED if b.lower() in text.lower()]
    if name.endswith(".html"):
        for tag in ("div", "ul", "li", "a", "table", "svg", "section"):
            o = len(re.findall(rf"<{tag}[\s>]", text)); c = text.count(f"</{tag}>")
            if o != c: errs.append(f"{name}: <{tag}> 열림 {o} / 닫힘 {c} 불일치")
    if len(text) < 3000: errs.append(f"{name}: 본문이 너무 짧음({len(text)}자)")
    return errs

# ────────────────────────── 차트 (SVG, 차트마다 선형 축 하나) ──────────────────────────
def lin(d0, d1, r0, r1):
    return lambda v: r0 + (v - d0) * (r1 - r0) / (d1 - d0)

def tickfmt(t, unit, signed=False):
    s = f"{t:+g}" if (signed and t) else f"{t:g}"
    return s + unit

def svg_diverging(c):
    items = sorted(c["items"], key=lambda r: r["value"], reverse=True)
    unit = c.get("unit", "%")
    W, L, R, rowh, top = 640, 140, 24, 26, 26
    H = top + rowh * len(items) + 8
    x = lin(c["domain"][0], c["domain"][1], L, W - R)
    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{E(c["title"])}">']
    for t in c["ticks"]:
        s.append(f'<line class="grid" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top-6}" y2="{H-6}"/>'
                 f'<text class="tick" x="{x(t):.1f}" y="{top-12}" text-anchor="middle">{tickfmt(t, unit, True) if t else "0"}</text>')
    s.append(f'<line class="base" x1="{x(0):.1f}" x2="{x(0):.1f}" y1="{top-6}" y2="{H-6}"/>')
    for i, it in enumerate(items):
        v, y = it["value"], top + i * rowh
        x0, x1 = sorted((x(0), x(v)))
        note = it.get("note", "")
        tip = f'{it["label"]} {v:+.2f}{unit}' + (f" · {note}" if note else "")
        s.append(f'<g class="mark" tabindex="0" data-tip="{E(tip)}"><rect class="hit" x="0" y="{y}" width="{W}" height="{rowh}"/>'
                 f'<rect class="{"up" if v > 0 else "down"}" x="{x0:.1f}" y="{y+6}" width="{max(x1-x0,1):.1f}" height="{rowh-12}" rx="3"/>'
                 f'<text class="lab" x="{L-10}" y="{y+rowh/2+4}" text-anchor="end">{E(it["label"])}</text>'
                 f'<text class="val" x="{(x1+6) if v > 0 else (x0-6):.1f}" y="{y+rowh/2+4}" text-anchor="{"start" if v > 0 else "end"}">{v:+.2f}{unit}{"*" if note else ""}</text></g>')
    s.append("</svg>")
    return "".join(s)

def svg_dumbbell_group(g, aria):
    unit, dec = g.get("unit", ""), g.get("decimals", 1)
    fv = lambda v: f"{v:.{dec}f}"
    W, L, R, rowh, top = 460, 104, 64, 40, 28
    H = top + rowh * len(g["rows"]) + 6
    x = lin(g["domain"][0], g["domain"][1], L, W - R)
    s = [f'<svg class="half" viewBox="0 0 {W} {H}" role="img" aria-label="{E(aria)}">']
    for t in g["ticks"]:
        s.append(f'<line class="grid" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top-6}" y2="{H-4}"/><text class="tick" x="{x(t):.1f}" y="{top-12}" text-anchor="middle">{tickfmt(t, unit)}</text>')
    if g.get("ref") is not None:
        s.append(f'<line class="ref" x1="{x(g["ref"]):.1f}" x2="{x(g["ref"]):.1f}" y1="{top-6}" y2="{H-4}"/><text class="reflab" x="{x(g["ref"])+5:.1f}" y="{H-8}">{E(g.get("ref_label",""))}</text>')
    for i, r in enumerate(g["rows"]):
        a, b = r["from"], r["to"]
        blab = r.get("to_label", fv(b))
        y = top + i * rowh + rowh / 2
        up = b >= a
        s.append(f'<g class="mark" tabindex="0" data-tip="{E(r["label"] + ": " + fv(a) + unit + " → " + blab + unit + (" · " + r["note"] if r.get("note") else ""))}"><rect class="hit" x="0" y="{y-rowh/2}" width="{W}" height="{rowh}"/>'
                 f'<text class="lab" x="{L-14}" y="{y+4}" text-anchor="end">{E(r["label"])}</text>'
                 f'<line class="stem" x1="{x(a):.1f}" x2="{x(b):.1f}" y1="{y}" y2="{y}"/>'
                 f'<circle class="prev" cx="{x(a):.1f}" cy="{y}" r="5"/><circle class="cur" cx="{x(b):.1f}" cy="{y}" r="6"/>'
                 f'<text class="val" x="{x(b)+(12 if up else -12):.1f}" y="{y+4}" text-anchor="{"start" if up else "end"}">{E(blab)}{unit}</text>'
                 f'<text class="tick" x="{x(a)+(-10 if up else 10):.1f}" y="{y+4}" text-anchor="{"end" if up else "start"}">{fv(a)}</text></g>')
    s.append("</svg>")
    return "".join(s)

def svg_ranges(c):
    unit = c.get("unit", "%")
    W, L, R, rowh, top = 460, 72, 96, 36, 28
    H = top + rowh * len(c["rows"]) + 22
    x = lin(c["domain"][0], c["domain"][1], L, W - R)
    s = [f'<svg class="half" viewBox="0 0 {W} {H}" role="img" aria-label="{E(c["title"])}">']
    for t in c["ticks"]:
        s.append(f'<line class="grid" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top-6}" y2="{H-20}"/><text class="tick" x="{x(t):.1f}" y="{top-12}" text-anchor="middle">{tickfmt(t, unit)}</text>')
    if c.get("ref") is not None:
        s.append(f'<line class="ref" x1="{x(c["ref"]):.1f}" x2="{x(c["ref"]):.1f}" y1="{top-6}" y2="{H-20}"/><text class="reflab" x="{x(c["ref"]):.1f}" y="{H-4}" text-anchor="middle">{E(c.get("ref_label",""))}</text>')
    for i, r in enumerate(c["rows"]):
        y = top + i * rowh + rowh / 2
        txt = f'{r["lo"]:g}~{r["hi"]:g}{unit}' if r["lo"] != r["hi"] else f'{r["lo"]:g}{unit}'
        s.append(f'<g class="mark" tabindex="0" data-tip="{E(r["label"] + ": " + txt)}"><rect class="hit" x="0" y="{y-rowh/2}" width="{W}" height="{rowh}"/>'
                 f'<text class="lab" x="{L-14}" y="{y+4}" text-anchor="end">{E(r["label"])}</text>'
                 f'<rect class="up" x="{x(r["lo"]):.1f}" y="{y-6}" width="{max(x(r["hi"])-x(r["lo"]),4):.1f}" height="12" rx="4"/>'
                 f'<text class="val" x="{x(r["hi"])+10:.1f}" y="{y+4}">{E(txt)}</text></g>')
    for dot in c.get("dots", []):
        y = top + dot["row"] * rowh + rowh / 2
        short = dot.get("short") or ("%g%s" % (dot["value"], unit))
        s.append(f'<g class="mark" tabindex="0" data-tip="{E(dot["label"])}"><circle class="cur" cx="{x(dot["value"]):.1f}" cy="{y}" r="5"/>'
                 f'<text class="tick" x="{x(dot["value"]):.1f}" y="{y-10}" text-anchor="middle">{E(short)}</text></g>')
    s.append("</svg>")
    return "".join(s)

def svg_bars(g, title):
    W, L, R, rowh = 640, 200, 90, 30
    H = rowh * len(g["rows"]) + 4
    x = lin(0, g["max"], L, W - R)
    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{E(title + " " + g.get("subtitle",""))}">']
    for i, r in enumerate(g["rows"]):
        y = i * rowh
        s.append(f'<g class="mark" tabindex="0" data-tip="{E(r["label"] + ": " + r["text"])}"><rect class="hit" x="0" y="{y}" width="{W}" height="{rowh}"/>'
                 f'<text class="lab" x="{L-12}" y="{y+rowh/2+4}" text-anchor="end">{E(r["label"])}</text>'
                 f'<rect class="{"emph" if r.get("emphasis") else "prevbar"}" x="{L}" y="{y+7}" width="{max(x(r["value"])-L,3):.1f}" height="{rowh-14}" rx="3"/>'
                 f'<text class="val" x="{x(r["value"])+8:.1f}" y="{y+rowh/2+4}">{E(r["text"])}</text></g>')
    s.append("</svg>")
    return "".join(s)

def legend(c):
    t = c["type"]
    if t == "diverging":
        return '<div class="legend"><span><i class="sw" style="background:var(--up)"></i>상승</span><span><i class="sw" style="background:var(--down)"></i>하락</span><span>* 출처 주석 있음(마우스 올려 확인)</span></div>'
    if t == "dumbbell":
        return (f'<div class="legend"><span><i class="sw dot hollow"></i>{E(c.get("legend_from","이전"))}</span>'
                f'<span><i class="sw dot" style="background:var(--ink)"></i>{E(c.get("legend_to","현재"))}</span></div>')
    if t == "ranges":
        return (f'<div class="legend"><span><i class="sw" style="background:var(--up)"></i>{E(c.get("legend_range","범위"))}</span>'
                + (f'<span><i class="sw dot" style="background:var(--ink)"></i>{E(c.get("legend_dot","확정"))}</span>' if c.get("dots") else "") + "</div>")
    return ""

def chart_panel(c):
    t = c["type"]
    if t == "diverging": body = svg_diverging(c)
    elif t == "dumbbell": body = "".join(svg_dumbbell_group(g, c["title"]) for g in c["groups"])
    elif t == "ranges": body = svg_ranges(c)
    else: body = "".join((f'<p class="subt">{E(g["subtitle"])}</p>' if g.get("subtitle") else "") + svg_bars(g, c["title"]) for g in c["groups"])
    wide = c.get("wide", t in ("diverging", "bars"))
    return (f'<div class="panel{" wide" if wide else ""}"><h3>{E(c["title"])}</h3>{legend(c)}'
            f'<div class="svgbox">{body}</div>' + (f'<p class="note">{E(c["note"])}</p>' if c.get("note") else "") + "</div>")

# ────────────────────────── 비주얼 페이지 ──────────────────────────
CSS = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "visual.css"), encoding="utf-8").read()
TIP_JS = """(function(){var tip=document.getElementById('tip');
function show(el,x,y){tip.textContent=el.getAttribute('data-tip');tip.hidden=false;var w=tip.offsetWidth,h=tip.offsetHeight;
var nx=Math.min(x+14,innerWidth-w-8),ny=y-h-12;if(ny<8)ny=y+16;tip.style.left=nx+'px';tip.style.top=ny+'px';}
document.querySelectorAll('[data-tip]').forEach(function(el){
el.addEventListener('pointermove',function(e){show(el,e.clientX,e.clientY);});
el.addEventListener('pointerleave',function(){tip.hidden=true;});
el.addEventListener('focus',function(){var r=el.getBoundingClientRect();show(el,r.left+r.width/2,r.top);});
el.addEventListener('blur',function(){tip.hidden=true;});});})();"""

SERIES = [("월나우", "김현석의 월스트리트나우"), ("월스트리트나우", "김현석의 월스트리트나우"), ("개장전요것만", "박신영의 개장전요것만"),
          ("월가아나토미", "박신영의 월가아나토미"), ("월가백브리핑", "월가백브리핑"), ("워싱턴나우", "이상은의 워싱턴나우"),
          ("실리콘밸리나우", "김인엽의 실리콘밸리나우"), ("바이아메리카", "바이아메리카 in NY"), ("브레이킹 뉴스", "김현석의 브레이킹 뉴스"),
          ("1분 시황", "당잠사 · 글로벌 1분 시황"), ("당잠사", "당신이 잠든 사이")]

def series(v):
    if v.get("series"): return v["series"]
    for k, name in SERIES:
        if k in v["title"]: return name
    return "한경 글로벌마켓" if v["channel"] == "A" else "한국경제TV"

def dur(v):
    parts = v["meta"].split(" · ")
    return parts[1] if len(parts) > 1 else ""

def vcard(v):
    url = f'https://www.youtube.com/watch?v={v["id"]}'
    b = "".join(f"<li><b>{E(h)}</b> {E(t)}</li>" for h, t in v["bullets"])
    return (f'<article class="vid"><a class="thumb {"tb" if v["channel"] == "B" else "ta"}" href="{url}" target="_blank" rel="noopener">'
            f'<span class="t-ser">{E(series(v))}</span><span class="t-dur">{E(dur(v))}</span><span class="t-play">유튜브에서 보기 ↗</span></a>'
            f'<div class="vbody"><h3><a href="{url}" target="_blank" rel="noopener">{E(v["title"])}</a></h3>'
            f'<p class="vmeta">{E(v["meta"])} · <span class="src">{E(v["basis"])}</span></p>'
            f'<p class="vsum">{E(v["summary"])}</p>'
            f'<details open><summary>주요 내용 {len(v["bullets"])}개</summary><ul class="bul">{b}</ul></details></div></article>')

def dir_cls(t): return {"up": "upr", "down": "dn"}.get(t.get("dir"), "flat")

def visual(d):
    cnt = d.get("counts", {})
    chips = [f'영상 {len(d["videos"])}건 · 자막 기반 {cnt.get("caption", 0)}건 · 기사 기반 {cnt.get("article", 0)}건',
             f'한경 글로벌마켓 {sum(v["channel"]=="A" for v in d["videos"])} · 당잠사 {sum(v["channel"]=="B" for v in d["videos"])}'] + d.get("notices", [])
    warn = "".join(f'<p class="alert">⚠️ {E(w)}</p>' for w in d.get("health_warnings", []))
    tick = "".join(f'<div class="tk"><span class="tk-n">{E(t["name"])}</span><span class="tk-v">{E(t["value"])}</span><span class="tk-d {dir_cls(t)}">{E(t["delta"])}</span></div>' for t in d["tickers"])
    drv = ""
    if d.get("drivers"):
        dr = d["drivers"]
        items = "".join(f'<li class="cause"><span class="c-no">{i+1}</span><div><b>{E(x["title"])}</b><span class="c-num">{E(x["num"])}</span><p>{E(x["text"])}</p></div></li>' for i, x in enumerate(dr["items"]))
        res = dr.get("result")
        drv = (f'<section class="sec"><div class="sec-h"><h2>{E(dr["title"])}</h2>' + (f'<p>{E(dr["intro"])}</p>' if dr.get("intro") else "") + f'</div>'
               f'<ol class="causes">{items}</ol>'
               + (f'<div class="result"><span>{E(res["label"])}</span><b class="big">{E(res["big"])}</b><span>{E(res["note"])}</span></div>' if res else "") + '</section>')
    charts = ""
    if d.get("charts"):
        charts = ('<section class="sec"><div class="sec-h"><h2>' + E(d.get("charts_title", "숫자로 본 하루")) + '</h2>'
                  '<p>막대와 점에 마우스를 올리거나 탭하면 값과 출처를 볼 수 있습니다. 상승은 빨강, 하락은 파랑입니다.</p></div>'
                  '<div class="grid2">' + "".join(chart_panel(c) for c in d["charts"]) + '</div></section>')
    b_band = d.get("b_band", "한국경제TV 「당잠사」")
    cardsA = "".join(vcard(v) for v in d["videos"] if v["channel"] == "A") or f'<p class="empty">{E(d.get("a_empty", "한경 글로벌마켓 신규 업로드 없음"))}</p>'
    cardsB = "".join(vcard(v) for v in d["videos"] if v["channel"] == "B") or f'<p class="empty">{E(d.get("b_empty", "당잠사 미업로드"))}</p>'
    syn = d["synthesis"]
    ul = lambda k: "<ul>" + "".join(f"<li>{E(i)}</li>" for i in syn[k]) + "</ul>"
    y, m, dd = d["date"].split("-")
    title = f"{int(m)}월 {int(dd)}일 아침 브리핑"
    return f'''<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@600;800&family=Noto+Sans+KR:wght@400;500;700&family=IBM+Plex+Mono:wght@400;600&display=swap">
<style>{CSS}</style>
<div class="wrap">
<header>
  <div class="eyebrow"><span>Hankyung Global Market · Daily Deep Dive</span></div>
  <h1>{E(d["headline"])}</h1>
  <p class="sub">{int(y)}년 {int(m)}월 {int(dd)}일 아침 브리핑 · 수집 시간창 {E(d["window"])}</p>
  <div class="chips">{"".join(f'<span class="chip">{E(c)}</span>' for c in chips)}</div>
  {warn}
</header>
<div class="tape" aria-label="{E(d.get("tickers_label", "직전 거래일 뉴욕 마감"))}">{tick}</div>
<section class="concl"><h2>오늘의 결론</h2><ol>{"".join(f"<li>{E(c)}</li>" for c in d["conclusions"])}</ol></section>
{drv}
{charts}
<section class="sec">
  <div class="band a">한경 글로벌마켓 · {sum(v["channel"]=="A" for v in d["videos"])}건</div>
  {cardsA}
  <div class="band b">{E(b_band)}</div>
  {cardsB}
</section>
<section class="synth">
  <h2>종합 뷰</h2>
  <div><h3>두 채널이 공통으로 강조한 이슈</h3>{ul("common")}</div>
  <div><h3>서로 엇갈리는 시각</h3>{ul("diverge")}</div>
  <div><h3>당잠사에만 있던 이슈</h3>{ul("only_b")}</div>
  <div class="box-w"><h3>비판적 점검</h3>{ul("critical")}</div>
  <div class="box-s"><h3>삼성 관점: 반도체·메모리·HBM·대미 통상</h3>{ul("samsung")}</div>
  <div><h3>오늘 주목할 이벤트</h3>{ul("events")}</div>
</section>
<footer>{E(d.get("footer", DEFAULT_FOOTER))}</footer>
</div>
<div id="tip" hidden></div>
<script>{TIP_JS}</script>
'''

DEFAULT_FOOTER = ("영상별 근거는 각 카드에 표기했습니다(자막=유튜브 자동생성 자막, 음성=음성 받아쓰기, 기사=기사·검색 기반). "
                  "한국경제TV는 「당잠사」 코너만 선별합니다. 자막 자동생성 특성상 오인식 가능성이 있으며 확인되지 않은 수치는 '자막 기준'으로 표기했습니다. 투자 자문이 아닙니다.")


# ────────────────────────── 메일 본문용 차트 (표 기반, 이미지·SVG 없음) ──────────────────────────
# 회사 메일(Outlook 포함)은 SVG와 외부 이미지를 막는 경우가 많아, 막대를 표 셀 배경색으로 그린다.
EC = {"up": "#d6453d", "down": "#2a6fc9", "prev": "#aab2bd", "ink": "#14181f", "track": "#eceef1", "muted": "#6b7380"}

def _bar_row(cells, h=12):
    """cells: [(width_pct, color or None)] 합이 100이 되게. 폭 0인 셀은 뺀다."""
    tds = []
    for w, c in cells:
        if w <= 0.05: continue
        attr = (' bgcolor="%s" style="background:%s;font-size:1px"' % (c, c)) if c else ' style="font-size:1px"'
        tds.append('<td width="%.0f%%" height="%d"%s></td>' % (w, h, attr))
    return '<table width="100%" cellpadding="0" cellspacing="0" border="0" style="table-layout:fixed"><tr>' + "".join(tds) + '</tr></table>'

def _row(label, bar, value, note=""):
    return (f'<tr><td width="30%" style="padding:5px 8px 5px 0;font-size:13px">{E(label)}</td>'
            f'<td style="padding:5px 0">{bar}</td>'
            f'<td width="22%" style="padding:5px 0 5px 8px;font:bold 13px Menlo,Consolas,monospace;white-space:nowrap">{E(value)}</td></tr>'
            + (f'<tr><td></td><td colspan="2" style="padding:0 0 4px;font-size:11px;color:{EC["muted"]}">{E(note)}</td></tr>' if note else ""))

def _tbl(rows):
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">{rows}</table>'

def email_chart(c):
    t = c["type"]; out = []
    if t == "diverging":
        lo, hi = c["domain"]; unit = c.get("unit", "%"); span = hi - lo
        zero = (0 - lo) / span * 100
        for it in sorted(c["items"], key=lambda r: r["value"], reverse=True):
            v = it["value"]; w = abs(v) / span * 100
            if v >= 0: cells = [(zero, None), (w, EC["up"]), (100 - zero - w, None)]
            else: cells = [(zero - w, None), (w, EC["down"]), (100 - zero, None)]
            out.append(_row(it["label"], _bar_row(cells), f"{v:+.2f}{unit}", it.get("note", "")))
        legend = f'<span style="color:{EC["up"]};">■</span> 상승 &nbsp; <span style="color:{EC["down"]};">■</span> 하락 · 가운데 기준선 0'
    elif t == "dumbbell":
        for g in c["groups"]:
            lo, hi = g["domain"]; span = hi - lo; unit = g.get("unit", ""); dec = g.get("decimals", 1)
            for r in g["rows"]:
                a, b = r["from"], r["to"]
                p0, p1 = (min(a, b) - lo) / span * 100, (max(a, b) - lo) / span * 100
                col = EC["up"] if b >= a else EC["down"]
                cells = [(p0, EC["track"]), (max(p1 - p0, 1.2), col), (100 - max(p1, p0 + 1.2), EC["track"])]
                val = f'{a:.{dec}f} → {r.get("to_label", f"{b:.{dec}f}")}{unit}'
                out.append(_row(r["label"], _bar_row(cells, 8), val, r.get("note", "")))
        legend = f'{E(c.get("legend_from","이전"))} → {E(c.get("legend_to","현재"))} · 색 구간이 변화 폭 (<span style="color:{EC["up"]};">■</span> 상승 <span style="color:{EC["down"]};">■</span> 하락), 회색은 축 범위'
    elif t == "ranges":
        lo, hi = c["domain"]; span = hi - lo; unit = c.get("unit", "%")
        for r in c["rows"]:
            p0, p1 = (r["lo"] - lo) / span * 100, (r["hi"] - lo) / span * 100
            cells = [(p0, EC["track"]), (max(p1 - p0, 1.5), EC["up"]), (100 - max(p1, p0 + 1.5), EC["track"])]
            val = f'{r["lo"]:g}~{r["hi"]:g}{unit}' if r["lo"] != r["hi"] else f'{r["lo"]:g}{unit}'
            out.append(_row(r["label"], _bar_row(cells, 8), val))
        for dot in c.get("dots", []):
            out.append(f'<tr><td></td><td colspan="2" style="padding:0 0 4px 0;font-size:11px;color:{EC["muted"]};">● {E(dot["label"])}</td></tr>')
        legend = f'축 {lo:g}~{hi:g}{unit}' + (f' · 기준선 {E(c.get("ref_label",""))}' if c.get("ref") is not None else "")
    else:
        legend = ""
        for g in c["groups"]:
            if g.get("subtitle"):
                out.append(f'<tr><td colspan="3" style="padding:8px 0 2px 0;font-size:12px;color:{EC["muted"]};">{E(g["subtitle"])}</td></tr>')
            for r in g["rows"]:
                w = r["value"] / g["max"] * 100
                out.append(_row(r["label"], _bar_row([(w, EC["down"] if r.get("emphasis") else EC["prev"]), (100 - w, None)]), r["text"]))
    return (f'<div style="border:1px solid #e3e5e8;border-radius:6px;padding:12px 14px;margin:0 0 12px 0;">'
            f'<div style="font-weight:bold;font-size:14px;margin:0 0 2px 0;">{E(c["title"])}</div>'
            + (f'<div style="font-size:11px;color:{EC["muted"]};margin:0 0 6px 0;">{legend}</div>' if legend else "")
            + _tbl("".join(out))
            + (f'<div style="font-size:12px;color:#555;margin:8px 0 0 0;line-height:1.6;">{E(c["note"])}</div>' if c.get("note") else "")
            + '</div>')

def dircol(t):
    return {"up": EC["up"], "down": EC["down"]}.get(t.get("dir"), "#555")

def email_visual(d):
    parts = []
    tk = d["tickers"]
    cells = "".join(
        f'<td width="{100/min(4,len(tk)):.0f}%" style="padding:8px 10px;border:1px solid #e0e2e5;vertical-align:top;">'
        f'<div style="font-size:11px;color:{EC["muted"]};">{E(t["name"])}</div>'
        f'<div style="font-size:16px;font-weight:bold;font-family:Menlo,Consolas,monospace;">{E(t["value"])}</div>'
        f'<div style="font-size:12px;font-family:Menlo,Consolas,monospace;color:{dircol(t)};">{E(t["delta"])}</div></td>'
        + ('</tr><tr>' if (i % 4 == 3 and i != len(tk) - 1) else "")
        for i, t in enumerate(tk))
    parts.append(f'<div style="font-size:12px;color:{EC["muted"]};margin:22px 0 6px 0;">{E(d.get("tickers_label","직전 거래일 뉴욕 마감"))}</div>'
                 f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;border-top:2px solid #111;"><tr>{cells}</tr></table>')
    if d.get("drivers"):
        dr = d["drivers"]
        rows = "".join(f'<tr><td style="padding:6px 8px 6px 0;vertical-align:top;font-weight:bold;color:{EC["up"]};font-family:Menlo,Consolas,monospace;width:18px;">{i+1}</td>'
                       f'<td style="padding:6px 0;vertical-align:top;font-size:14px;"><strong>{E(x["title"])}</strong> <span style="font-family:Menlo,Consolas,monospace;font-size:13px;">{E(x["num"])}</span><br><span style="color:#555;font-size:13px;">{E(x["text"])}</span></td></tr>'
                       for i, x in enumerate(dr["items"]))
        res = dr.get("result")
        parts.append(f'<h2 style="font-size:18px;margin:24px 0 6px 0;">{E(dr["title"])}</h2>'
                     + _tbl(rows)
                     + (f'<div style="background:#fbf7f2;border:1px solid #e8d9c8;border-left:4px solid #d6453d;color:#111;padding:12px 14px;margin:8px 0 0 0;"><span style="font-size:13px;color:#111;">{E(res["label"])}</span> '
                        f'<strong style="font-size:24px;font-family:Menlo,Consolas,monospace;color:#b3261e;">{E(res["big"])}</strong><br><span style="font-size:12px;color:#555;">{E(res["note"])}</span></div>' if res else ""))
    if d.get("charts"):
        parts.append(f'<h2 style="font-size:18px;margin:24px 0 8px 0;">{E(d.get("charts_title","숫자로 본 하루"))}</h2>' + "".join(email_chart(c) for c in d["charts"]))
    return "".join(parts)

def chart_text(c):
    t = c["type"]; L = [f"[{c['title']}]"]
    if t == "diverging":
        u = c.get("unit", "%")
        L += [f"  {it['label']} {it['value']:+.2f}{u}" + (f" ({it['note']})" if it.get("note") else "") for it in sorted(c["items"], key=lambda r: r["value"], reverse=True)]
    elif t == "dumbbell":
        for g in c["groups"]:
            dec, u = g.get("decimals", 1), g.get("unit", "")
            L += [f"  {r['label']} {r['from']:.{dec}f} → " + (r.get('to_label') or ('%.*f' % (dec, r['to']))) + u for r in g["rows"]]
    elif t == "ranges":
        u = c.get("unit", "%")
        L += [f"  {r['label']} {r['lo']:g}~{r['hi']:g}{u}" for r in c["rows"]] + [f"  · {x['label']}" for x in c.get("dots", [])]
    else:
        for g in c["groups"]:
            L += [f"  {r['label']} {r['text']}" for r in g["rows"]]
    if c.get("note"): L.append(f"  → {c['note']}")
    return L

# ────────────────────────── 메일 ──────────────────────────
def email_txt(d):
    L = [f'[한경 글로벌마켓+당잠사] {d["date"]} 아침 브리핑', f'수집 시간창: {d["window"]}']
    if d.get("visual_url"): L.append(f'인터랙티브 비주얼 리포트(claude.ai 소유자 계정 전용): {d["visual_url"]}')
    cnt = d.get("counts", {})
    L.append(f'근거: 자막 기반 {cnt.get("caption",0)}건 / 기사 기반 {cnt.get("article",0)}건')
    for n in d.get("notices", []): L.append(f"※ {n}")
    for w in d.get("health_warnings", []): L.append(f"⚠️ {w}")
    L += ["", "■ 오늘의 결론 3줄"] + [f"- {c}" for c in d["conclusions"]]
    L += ["", "■ " + d.get("tickers_label", "직전 거래일 뉴욕 마감")] + ["  " + " / ".join(f"{t['name']} {t['value']} ({t['delta']})" for t in d["tickers"])]
    if d.get("drivers"):
        L += ["", "■ " + d["drivers"]["title"]] + [f"  {i+1}. {x['title']} — {x['num']}: {x['text']}" for i, x in enumerate(d["drivers"]["items"])]
        if d["drivers"].get("result"):
            r = d["drivers"]["result"]; L.append(f"  ⇒ {r['label']} {r['big']} ({r['note']})")
    if d.get("charts"):
        L += ["", "■ " + d.get("charts_title", "숫자로 본 하루")]
        for c in d["charts"]: L += chart_text(c)
    for ch, name in (("A", "■■ 한경 글로벌마켓"), ("B", "■■ 한국경제TV 「당잠사」")):
        L += ["", name]
        vs = [v for v in d["videos"] if v["channel"] == ch]
        if not vs: L.append("   " + (d.get("b_empty", "당잠사 미업로드") if ch == "B" else d.get("a_empty", "한경 글로벌마켓 신규 업로드 없음")))
        for v in vs:
            L += ["", f'▶ {v["title"]}', f'   https://www.youtube.com/watch?v={v["id"]}', f'   {v["meta"]} · {v["basis"]}',
                  "   [전체 요약]", "   " + v["summary"], "   [주요 내용]"] + [f"   • {h} {t}" for h, t in v["bullets"]]
    L += ["", "■ 종합 뷰"]
    for k, t in (("common", "두 채널이 공통으로 강조한 이슈"), ("diverge", "서로 엇갈리는 시각"), ("only_b", "당잠사에만 있던 이슈"),
                 ("critical", "비판적 점검"), ("samsung", "삼성 관점"), ("events", "오늘 주목할 이벤트")):
        L.append(f"[{t}]"); L += [f"- {s}" for s in d["synthesis"][k]]; L.append("")
    L.append("고지: " + d.get("footer", DEFAULT_FOOTER))
    return "\n".join(L)

def email_html(d):
    def li(items, gap=8): return "".join(f'<li style="margin:0 0 {gap}px 0;line-height:1.7;">{E(i)}</li>' for i in items)
    def ulist(items): return f'<ul style="margin:6px 0 0 0;padding-left:20px;">{li(items)}</ul>'
    def card(v):
        url = f'https://www.youtube.com/watch?v={v["id"]}'
        b = "".join(f'<li style="margin:0 0 10px 0;line-height:1.7;"><strong style="color:#111;">{E(h)}</strong> <span style="color:#111;">{E(t)}</span></li>' for h, t in v["bullets"])
        return (f'<div style="border:1px solid #e3e5e8;border-radius:6px;padding:16px;margin:0 0 18px 0;background:#fff;">'
                f'<a href="{url}" style="text-decoration:none;"><img src="https://i.ytimg.com/vi/{v["id"]}/mqdefault.jpg" width="320" style="width:320px;max-width:100%;height:auto;border-radius:4px;display:block;" alt=""></a>'
                f'<h3 style="margin:12px 0 4px 0;font-size:17px;line-height:1.4;"><a href="{url}" style="color:#111;text-decoration:none;">{E(v["title"])}</a></h3>'
                f'<div style="font-size:13px;color:#666;margin:0 0 12px 0;">{E(v["meta"])} · <span style="color:#c0392b;">{E(v["basis"])}</span></div>'
                f'<div style="background:#f7f8f9;border-radius:4px;padding:12px 14px;margin:0 0 12px 0;font-size:15px;line-height:1.7;color:#111;"><strong>전체 요약</strong><br>{E(v["summary"])}</div>'
                f'<div style="font-size:14px;font-weight:bold;color:#666;margin:0 0 6px 0;">주요 내용</div>'
                f'<ul style="margin:0;padding-left:20px;font-size:15px;">{b}</ul></div>')
    def band(t, c):
        tint = {"#111": "#f2f3f5", "#1f4e79": "#eaf1f8"}.get(c, "#f2f3f5")
        return f'<div style="background:{tint};border-left:6px solid {c};color:{c};font-weight:bold;font-size:15px;padding:8px 14px;margin:24px 0 14px 0;">{E(t)}</div>'
    cnt = d.get("counts", {})
    badges = [("#111", "#fff", f'자막 기반 {cnt.get("caption",0)}건'), ("#e3e5e8", "#111", f'기사 기반 {cnt.get("article",0)}건')] + [("#1f4e79", "#fff", n) for n in d.get("notices", [])]
    badge_html = "".join(f'<span style="display:inline-block;border:1px solid {"#1f4e79" if bg == "#1f4e79" else "#8a919c"};color:{"#1f4e79" if bg == "#1f4e79" else "#111"};font-size:12px;padding:2px 9px;border-radius:12px;margin:0 6px 6px 0;">{E(t)}</span>' for bg, fg, t in badges)
    warn = "".join(f'<div style="background:#fff3f0;border:1px solid #f0c4b8;color:#8a2a1c;padding:8px 12px;margin:10px 0 0 0;font-size:14px;">⚠️ {E(w)}</div>' for w in d.get("health_warnings", []))
    vis = ""
    if d.get("visual_url"):
        vis = (f'<div style="margin:16px 0 0 0;"><a href="{E(d["visual_url"])}" style="display:inline-block;border:2px solid #1f4e79;color:#1f4e79;text-decoration:none;font-weight:bold;font-size:14px;padding:8px 16px;border-radius:4px;">📊 인터랙티브 비주얼 리포트 (claude.ai 소유자 계정 전용)</a>'
               f'<div style="font-size:12px;color:#666;margin:6px 0 0 0;">차트는 아래 메일 본문에도 모두 들어 있습니다. 링크는 claude.ai에 로그인한 소유자 계정에서만 열립니다.</div></div>')
    A = "".join(card(v) for v in d["videos"] if v["channel"] == "A") or f'<p style="color:#666;">{E(d.get("a_empty","한경 글로벌마켓 신규 업로드 없음"))}</p>'
    B = "".join(card(v) for v in d["videos"] if v["channel"] == "B") or f'<p style="color:#666;">{E(d.get("b_empty","당잠사 미업로드"))}</p>'
    s = d["synthesis"]
    nA = sum(v["channel"] == "A" for v in d["videos"])
    return f'''<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{d["date"]} 아침 브리핑</title></head>
<body style="margin:0;padding:0;background:#fff;">
<div style="max-width:680px;margin:0 auto;padding:20px 16px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;font-size:15px;line-height:1.7;color:#111;">
<div style="font-size:12px;letter-spacing:2px;color:#c0392b;font-weight:bold;">HANKYUNG GLOBAL MARKET • DAILY DEEP DIVE</div>
<h1 style="font-size:22px;margin:6px 0 6px 0;line-height:1.35;">{d["date"]} 아침 브리핑 — {E(d["headline"])}</h1>
<div style="font-size:13px;color:#666;">수집 시간창: {E(d["window"])}</div>
<div style="margin:10px 0 0 0;">{badge_html}</div>{warn}{vis}
<div style="background:#fbf7f2;border-left:4px solid #c0392b;padding:12px 16px;margin:18px 0 0 0;"><div style="font-weight:bold;margin:0 0 6px 0;">오늘의 결론 3줄</div><ul style="margin:0;padding-left:20px;">{li(d["conclusions"])}</ul></div>
{email_visual(d)}
{band(f"한경 글로벌마켓 — {nA}건", "#111")}{A}
{band(d.get("b_band", "한국경제TV 「당잠사」"), "#1f4e79")}{B}
<div style="border:2px solid #111;border-radius:6px;padding:16px;margin:24px 0 0 0;"><h2 style="font-size:18px;margin:0 0 12px 0;">종합 뷰</h2>
<div style="font-weight:bold;margin:10px 0 0 0;">두 채널이 공통으로 강조한 이슈</div>{ulist(s["common"])}
<div style="font-weight:bold;margin:14px 0 0 0;">서로 엇갈리는 시각</div>{ulist(s["diverge"])}
<div style="font-weight:bold;margin:14px 0 0 0;">당잠사에만 있던 이슈</div>{ulist(s["only_b"])}
<div style="background:#fff8f0;border:1px solid #f0d9c0;border-radius:4px;padding:12px 14px;margin:16px 0 0 0;"><div style="font-weight:bold;">비판적 점검</div>{ulist(s["critical"])}</div>
<div style="background:#f0f7f4;border-left:4px solid #2e8b57;border-radius:4px;padding:12px 14px;margin:14px 0 0 0;"><div style="font-weight:bold;">삼성 관점 — 반도체·메모리·HBM·대미 통상</div>{ulist(s["samsung"])}</div>
<div style="font-weight:bold;margin:16px 0 0 0;">오늘 주목할 이벤트</div>{ulist(s["events"])}</div>
<div style="font-size:12px;color:#666;line-height:1.6;margin:24px 0 0 0;border-top:1px solid #e3e5e8;padding-top:12px;">{E(d.get("footer", DEFAULT_FOOTER))}</div>
</div></body></html>'''

def subject(d):
    return f'[한경 글로벌마켓+당잠사] {d["date"]} 아침 브리핑 — 영상 {len(d["videos"])}건 ({d["subject_keywords"]})'

# ────────────────────────── main ──────────────────────────
ALLOW_OLD_DATE = False

def main():
    global ALLOW_OLD_DATE
    if "--allow-old-date" in sys.argv:
        ALLOW_OLD_DATE = True; sys.argv.remove("--allow-old-date")
    if len(sys.argv) != 3:
        print(__doc__); sys.exit(2)
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    errs = check(d)
    if errs:
        print("데이터 검사 실패:"); [print(" -", e) for e in errs]; sys.exit(1)
    out = {"visual.html": visual(d), "email.html": email_html(d), "email.txt": email_txt(d)}
    errs = [e for k, v in out.items() for e in check_output(k, v)]
    if errs:
        print("출력 검사 실패:"); [print(" -", e) for e in errs]; sys.exit(1)
    os.makedirs(sys.argv[2], exist_ok=True)
    for k, v in out.items():
        open(os.path.join(sys.argv[2], k), "w", encoding="utf-8").write(v)
    open(os.path.join(sys.argv[2], "subject.txt"), "w", encoding="utf-8").write(subject(d))
    print("OK", subject(d))
    print("visual_url:", d.get("visual_url") or "(없음 — 게시 후 JSON에 넣고 다시 렌더링)")
    for k, v in out.items(): print(f"  {k}: {len(v):,}자")

if __name__ == "__main__":
    main()
