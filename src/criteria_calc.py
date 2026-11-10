"""실험 11: 계산·비교 질문을 코드가 기준표 값으로 계산한다. LLM은 계산 결과를 설명만 한다.

계산 규칙 (규칙 기반, 비용 0). 안 걸리면 (None, 사유)를 돌려주고 기존 경로(조회 → RAG)로 간다.
- 규칙 A 부전공 ↔ 복수·다전공 전공학점 비교
    대학 1개, 학번 정확히 1개(2022~2026), 질문에 '부전공' + (복수전공|다전공|제2전공) + 비교 단서(중에·비교·더 많/적·어느 쪽·이랑),
    '심화'·'교직'은 없을 때.
    부전공 합 = 부전공시_주전공_전공학점 + 부전공_이수학점, 복수·다전공 합 = 복수전공시_주전공_전공학점 + 복수전공_이수학점
- 규칙 B 학교 간 최저 평점 비교
    대학 2개 이상, '평점', '가장|제일 + 낮|높'. 평점_최저 값이 있는 학교만 순위를 매기고 확인불가·없음 학교는 순위에서 뺀다.
    값 있는 학교가 2개 미만이면 안 건다.
- 행 선택은 criteria_lookup(E8)과 같다: 학번 구간, 학과를 지목하면 그 대상 행, 지목했는데 맞는 행이 없으면 폴백, 아니면 대학 전체 행,
  교직 행 제외. 학과 한정 행뿐이면(배재 주전공 학점 행 등) 계산하지 않고 RAG로 보낸다(E8 결정, B01·B10과 같음).
- 항목마다 행이 정확히 1개여야 하고 값이 숫자여야 하며 상태가 확인불가·없음이면 안 건다.
"""

import re

import criteria_lookup as L
import query_filter as QF

CMP_RE = re.compile(r"중에|비교|더 (많|적)|어느 쪽|이랑")
MULTI_RE = re.compile(r"복수전공|다전공|제2전공")
DIRECTION_RE = re.compile(r"(가장|제일)\s*(낮|높)")
A_ITEMS = {
    "부전공": ("부전공시_주전공_전공학점", "부전공_이수학점"),
    "복수": ("복수전공시_주전공_전공학점", "복수전공_이수학점"),
}


def _cand_spec(univ, item, year, q):
    cand = [r for r in L.CRITERIA if r["대학"] == univ and r["항목"] == item and r["기준값여부"] == "기준"
            and (year is None or L.in_range(r, year)) and "교직" not in r["이수유형"]]
    spec = [r for r in cand if r["대상"] != "전체" and L.target_mentioned(r["대상"], q)]
    return cand, spec


def _pick_one(univ, item, year, q, bundle_spec=False):
    """항목 행 1개와 사유. 없거나 여러 개면 (None, 사유).
    bundle_spec: 묶음의 다른 항목에서 질문이 지목한 학과 행을 찾았으면 True. 이때 이 항목에 학과 행이 없으면 대학 전체 행을 쓴다
    (E16: 조회의 E12 규칙과 같다. 배재·충남은 주전공 학점만 학과 행이고 이수학점은 대학 전체 행이다)."""
    cand, spec = _cand_spec(univ, item, year, q)
    mentions = [m for m in L.MENTION_RE.findall(q) if m not in L.SCHOOL_WORDS and m != "일반학과"]
    if spec:
        rows = spec
    elif mentions and not bundle_spec:
        return None, f"질문의 {mentions}에 맞는 대상 행 없음"
    else:
        rows = [r for r in cand if r["대상"] == "전체"]
    if not rows:
        return None, f"{item} 행 없음(학과 한정 행뿐이거나 묶음 불완전)"
    if len(rows) != 1:
        return None, f"{item} 행이 {len(rows)}개"
    row = rows[0]
    if row["상태"] in ("확인불가", "없음") or not re.fullmatch(r"\d+(\.\d+)?", row["값"] or ""):
        return None, f"{row['행ID']} 값 없음·상태 {row['상태']}"
    return row, ""


def _num(row):
    return float(row["값"])


def _fmt(x):
    return f"{x:g}"


def _term(n, row, label):
    tag = "(잠정)" if row["상태"] == "잠정" else ""
    return f"{label} [{n}] {_fmt(_num(row))}학점{tag}"


def _calc_a(q, univ, year):
    other = "다전공" if "다전공" in q else "복수전공"
    rows, sums, lines = [], {}, []
    bundle_spec = any(_cand_spec(univ, it, year, q)[1] for items in A_ITEMS.values() for it in items)
    for key, name in (("부전공", "부전공"), ("복수", other)):
        major_item, extra_item = A_ITEMS[key]
        picked = []
        for item in (major_item, extra_item):
            row, why = _pick_one(univ, item, year, q, bundle_spec)
            if row is None:
                return None, why
            picked.append(row)
        base = len(rows)
        rows += picked
        total = _num(picked[0]) + _num(picked[1])
        sums[name] = total
        lines.append(f"- {name} 전공학점 합: {_term(base + 1, picked[0], '주전공')} + {_term(base + 2, picked[1], name)} = {_fmt(total)}학점")
    (n1, v1), (n2, v2) = list(sums.items())
    diff = abs(v1 - v2)
    if diff == 0:
        concl = f"{n1}과 {n2}의 전공학점 합은 {_fmt(v1)}학점으로 같다."
    else:
        less, more = (n1, n2) if v1 < v2 else (n2, n1)
        concl = f"{less}이 {more}보다 {_fmt(diff)}학점 더 적다({more}이 {_fmt(diff)}학점 더 많다)."
    lines.append(f"- 차이: {_fmt(diff)}학점")
    lines.append(f"- 결론: {concl}")
    return {"kind": "A", "rows": rows, "text": "\n".join(lines), "values": sums}, ""


def _calc_b(q, univs):
    d = DIRECTION_RE.search(q)
    low = d.group(2) == "낮"
    rows, ranked, skipped, lines = [], {}, [], []
    for u in univs:
        cand = [r for r in L.CRITERIA if r["대학"] == u and r["항목"] == "평점_최저" and r["기준값여부"] == "기준"]
        if not cand:
            skipped.append((u, "기준표 행 없음"))
            continue
        for r in cand:
            rows.append(r)
        if len(cand) == 1 and cand[0]["상태"] not in ("확인불가", "없음") and re.fullmatch(r"\d+(\.\d+)?", cand[0]["값"] or ""):
            ranked[u] = (_num(cand[0]), len(rows))
        else:
            skipped.append((u, f"상태 {cand[0]['상태']}"))
    if len(ranked) < 2:
        return None, "평점 값이 있는 학교가 2개 미만"
    for u, (v, n) in ranked.items():
        lines.append(f"- {u}대 졸업 최저 평점: [{n}] {v:.2f}점")
    for u, why in skipped:
        lines.append(f"- {u}대: 값이 없어 순위에서 뺌({why})")
    best = min(v for v, _ in ranked.values()) if low else max(v for v, _ in ranked.values())
    names = "·".join(f"{u}대" for u, (v, _) in ranked.items() if v == best)
    lines.append(f"- 결론: 최저 평점이 가장 {'낮은' if low else '높은'} 학교는 {names}({best:.2f}점)이다.")
    return {"kind": "B", "rows": rows, "text": "\n".join(lines), "values": {u: v for u, (v, _) in ranked.items()}}, ""


def calc(question):
    """반환: (결과, 사유). 결과는 {kind, rows, text, values} 또는 None(계산 안 함 → 조회·RAG)"""
    univs = QF.extract_universities(question)
    years = QF.extract_years(question)
    if "부전공" in question and MULTI_RE.search(question) and CMP_RE.search(question) \
            and "심화" not in question and "교직" not in question:
        if len(univs) != 1:
            return None, "규칙 A: 대학이 0개 또는 여러 개"
        if len(years) != 1 or not 2022 <= years[0] <= 2026:
            return None, f"규칙 A: 학번 {years}"
        return _calc_a(question, univs[0], years[0])
    if len(univs) >= 2 and "평점" in question and DIRECTION_RE.search(question):
        return _calc_b(question, univs)
    return None, "계산·비교 규칙 아님"


def build_context(result):
    """LLM에 넘길 [계산 결과] 문자열, [기준표 조회 결과] 문자열, 번호→행ID 목록"""
    ids = [r["행ID"] for r in result["rows"]]
    rows_text = "\n".join(f"[{n}] {L.row_text(r)}" for n, r in enumerate(result["rows"], 1))
    return result["text"], rows_text, ids
