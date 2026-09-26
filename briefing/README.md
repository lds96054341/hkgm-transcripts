# 아침 브리핑 렌더러

`render.py`는 하루치 브리핑 데이터(JSON) 하나로 비주얼 리포트, 메일 HTML, 메일 평문을 만든다.
표준 라이브러리만 쓴다(pip 설치 불필요).

```bash
python3 /tmp/hkgm/briefing/render.py data.json out/   # routine은 4절에서 받은 /tmp/hkgm clone을 쓴다
# out/visual.html   Artifact로 게시
# out/email.html    메일 htmlBody
# out/email.txt     메일 body
# out/subject.txt   메일 제목
```

렌더러는 쓰기 전에 데이터와 출력물을 검사한다. 하나라도 걸리면 아무것도 쓰지 않고 종료 코드 1로 끝난다.
검사 항목은 필수 항목 누락, `date`가 오늘(KST)이 아님(테스트는 `--allow-old-date`), 테스트용 옛 비주얼 링크, 결론이 3줄이 아님, 결론 한 줄이 130자(메일에서 약 3줄) 초과, 불릿 12개 초과, 타임스탬프 표기, 차트 값이 축 범위 밖,
금지 문자열(PLACEHOLDER, TODO 등), HTML 태그 짝 불일치, 지나치게 짧은 본문이다.

실제 예시: `examples/2026-09-24.json`

## 최상위 항목

| 키 | 필수 | 내용 |
|---|---|---|
| `date` | ✔ | `YYYY-MM-DD` (KST 기준 발송일) |
| `window` | ✔ | 수집 시간창 문자열 |
| `headline` | ✔ | 그날을 한 문장으로. 비주얼 제목과 메일 h1에 쓰인다 |
| `subject_keywords` | ✔ | 메일 제목 괄호 안 키워드 |
| `counts` | | `{"caption": n, "article": n}` 근거별 건수 |
| `notices` | | 배지로 보일 짧은 알림 (예: "당잠사 미업로드") |
| `health_warnings` | | 수집기 이상 경고 문구. 상단에 경고 박스로 뜬다 |
| `visual_url` | | 게시한 Artifact URL. 있으면 메일 상단에 버튼이 생긴다 |
| `conclusions` | ✔ | 정확히 3개. 각각 130자 이하(메일에서 최대 3줄) |
| `tickers` | ✔ | `[{name, value, delta, dir: "up"|"down"|"flat"}]` |
| `tickers_label` | | 시세 띠 접근성 라벨 (기본 "직전 거래일 뉴욕 마감") |
| `drivers` | | `{title, intro, items:[{title, num, text}], result:{label, big, note}}` |
| `charts_title` | | 차트 구역 제목 (기본 "숫자로 본 하루") |
| `charts` | | 아래 차트 종류 목록 |
| `b_band` | | 당잠사 띠 문구 |
| `b_empty` | | 당잠사 영상이 없을 때 문구 |
| `a_empty` | | 한경 글로벌마켓 영상이 없을 때 문구 |
| `videos` | ✔ | `[{channel: "A"|"B", id, title, meta, basis, summary, bullets: [[결론, 본문], ...], series?}]` |
| `synthesis` | ✔ | `{common, diverge, only_b, critical, samsung, events}` 각각 문자열 배열 |
| `footer` | | 하단 고지 (기본 문구 있음) |

`meta`는 `"2026-09-23 12:00 KST 업로드 · 16분 10초 · 조회 219,319회"` 형식을 지킨다.
두 번째 조각(영상 길이)이 비주얼 카드 타일에 쓰인다.

## 차트 종류

모든 차트는 차트마다 선형 축 하나를 쓴다. 이중 축은 없다. 상승은 빨강, 하락은 파랑이다.

- **`diverging`** 등락률처럼 0을 기준으로 오르내리는 값.
  `{type, title, note, unit, domain:[min,max], ticks:[...], items:[{label, value, note?}]}`.
  `note`가 있는 항목은 값 옆에 `*`가 붙고 마우스를 올리면 주석이 보인다.
- **`dumbbell`** 전 → 후 비교(PMI 전월→당월, 확률 전날→당일 등).
  `{type, title, note, legend_from, legend_to, groups:[{domain, ticks, unit, decimals, ref?, ref_label?, rows:[{label, from, to, to_label?, note?}]}]}`.
  단위가 다른 비교는 group을 나눠 각자 축을 준다.
- **`ranges`** 범위 값(채권 금리 제시 범위 등).
  `{type, title, note, unit, domain, ticks, ref?, ref_label?, legend_range, legend_dot?, rows:[{label, lo, hi}], dots?:[{row, value, label, short?}]}`.
- **`bars`** 크기 비교 막대. `{type, title, note, groups:[{subtitle?, max, rows:[{label, value, text, emphasis?}]}]}`.

`diverging`과 `bars`는 기본으로 한 줄 전체를 쓰고 나머지는 반 폭이다. `wide: true/false`로 바꿀 수 있다.

## 스타일

`visual.css`에 색과 글꼴 토큰이 있다. 라이트·다크 모드를 모두 정의했고, 상승·하락 색은 두 모드 모두 색각 이상 검사를 통과했다.
