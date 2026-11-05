"""실험 8: 숫자 질문을 data/criteria.csv 조회로 처리한다. 계산(합·차·비교)은 하지 않고 LLM은 조회한 행을 설명만 한다.

조회 규칙 (규칙 기반, 비용 0)
- 대학이 1개로 뽑혀야 하고(query_filter), 학번이 있으면 모두 2022~2026학번이어야 한다. 아니면 조회 안 함 → RAG
- 질문에 숫자 의도("몇 학점", "이수학점", "몇 점", "한 학기 최대" 등)와 항목 키워드가 함께 있어야 한다
    졸업학점 / 평점_최저 / 수강상한_학기 / 부전공(이수학점 + 부전공시 주전공 학점) / 복수전공(이수학점 + 복수전공시 주전공 학점)
- 계산·비교 단서("비교", "중에", "더 적", "심화" 등)가 있으면 조회 안 함 → RAG
- 행은 기준값여부=기준만, 학번 구간에 맞는 것. 학번이 여러 개면 학번마다 조회. 학번이 없으면 구간과 무관하게 모두
- 학과를 지목하면 그 대상 행(대상 이름의 단어 단위 일치), 아니면 대학 전체 행. 지목한 학과에 맞는 행이 없으면 조회 안 함 → RAG
- 묶음(부전공·복수전공)의 한쪽 항목에 행이 없으면 조회 안 함 → RAG
- 이수유형이 교직·심화인 행은 질문에 '교직'이 없으면 뺀다
LLM에는 값·출처뿐 아니라 그 행의 조건·비고·상태도 함께 넘긴다 (관리용 메모 '평가셋 …' 문장은 뺀다).
"""

import csv
import re
from pathlib import Path

import query_filter

ROOT = Path(__file__).resolve().parent.parent
CRITERIA = list(csv.DictReader((ROOT / "data" / "criteria.csv").open(encoding="utf-8-sig")))
BY_ID = {r["행ID"]: r for r in CRITERIA}

COMPARE_RE = re.compile(r"비교|중에|이랑 .*(중|더)|더 (많|적)|어느 쪽|심화")
MENTION_RE = re.compile(r"([가-힣]{2,}(?:학과|학부|대학)|건축학|간호|사범)")
SCHOOL_WORDS = {u + s for u in ("배재", "충남", "한남", "한밭", "목원") for s in ("대", "대학교")}
BUNDLE = {
    "부전공": ["부전공_이수학점", "부전공시_주전공_전공학점"],
    "복수전공": ["복수전공_이수학점", "복수전공시_주전공_전공학점"],
}


def norm(s):
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"\s|·", "", s)
    return re.sub(r"(학과|학부|전공)$", "", s)


def items_for(q):
    if re.search(r"한 학기.*(최대|몇 학점)|수강.*(할 수|신청)", q):
        return ["수강상한_학기"]
    if "평점" in q and re.search(r"몇 점|이상|\d\.\d", q):
        return ["평점_최저"]
    if re.search(r"복수전공|다전공|제2전공", q) and re.search(r"몇 학점|이수학점", q):
        return BUNDLE["복수전공"]
    if "부전공" in q and re.search(r"몇 학점|이수학점", q):
        return BUNDLE["부전공"]
    if "졸업" in q and re.search(r"몇 학점|졸업학점", q) and "말고" not in q and "한 학기" not in q:
        return ["졸업학점"]
    return None


def in_range(row, year):
    start = int(row["입학년도_시작"]) if row["입학년도_시작"] else -1
    end = int(row["입학년도_끝"]) if row["입학년도_끝"] else 9999
    return start <= year <= end


def lookup(question):
    """반환: (결과, 사유). 결과는 {학번 또는 None: [criteria 행]} 또는 None(조회 안 함 → RAG)"""
    univ = query_filter.extract_universities(question)
    if len(univ) != 1:
        return None, "대학이 0개 또는 여러 개"
    years = query_filter.extract_years(question)
    if any(y < 2022 or y > 2026 for y in years):
        return None, "범위 밖 학번"
    items = items_for(question)
    if not items:
        return None, "숫자 항목 아님"
    if COMPARE_RE.search(question):
        return None, "계산·비교"
    mentions = [m for m in MENTION_RE.findall(question) if m not in SCHOOL_WORDS and m != "일반학과"]
    out = {}
    for year in years or [None]:
        rows = []
        for item in items:
            cand = [r for r in CRITERIA if r["대학"] == univ[0] and r["항목"] == item and r["기준값여부"] == "기준"]
            if year:
                cand = [r for r in cand if in_range(r, year)]
            if item in sum(BUNDLE.values(), []) and "교직" not in question:
                cand = [r for r in cand if "교직" not in r["이수유형"]]
            spec = [r for r in cand if r["대상"] != "전체" and any(norm(t) and norm(t) in norm(question) for t in r["대상"].split())]
            if spec:
                cand = spec
            elif mentions:
                return None, f"질문의 {mentions}에 맞는 대상 행 없음"
            else:
                cand = [r for r in cand if r["대상"] == "전체"]
            if not cand:
                return None, f"{item} 행 없음(묶음 불완전)"
            rows += cand
        out[year] = rows
    return out, ""


def clean_note(note):
    note = re.sub(r"평가셋 [A-Z0-9·,\s]+[.。]?", "", note).strip()
    return note[:600]


def row_text(row):
    value = f"{row['값']}{row['단위']} {row['비교']}".strip() if row["값"] else "(값 없음)"
    if row["값_최대"]:
        value = f"{row['값']}~{row['값_최대']}{row['단위']}"
    span = f"{row['입학년도_시작'] or '제한 없음'} ~ {row['입학년도_끝'] or '현행'}"
    parts = [f"행ID {row['행ID']}", f"{row['대학']} / 대상: {row['대상']}({row['대상단위']})", f"입학년도 {span}",
             f"구분 {row['구분'] or '-'} / 이수유형 {row['이수유형'] or '-'}", f"항목: {row['항목']}", f"값: {value}",
             f"상태: {row['상태']}"]
    if row["조건"]:
        parts.append(f"조건: {row['조건']}")
    note = clean_note(row["비고"])
    if note:
        parts.append(f"비고: {note}")
    parts.append(f"출처: {row['출처조항']}, 쪽 {row['출처쪽']} ({row['출처파일']}, 등급 {row['출처등급']})")
    return " | ".join(parts)


def build_context(result):
    """LLM에 넘길 근거 문자열과 번호→행ID 목록"""
    lines, ids = [], []
    for year, rows in result.items():
        if year:
            lines.append(f"## {year}학번")
        for row in rows:
            ids.append(row["행ID"])
            lines.append(f"[{len(ids)}] {row_text(row)}")
    return "\n".join(lines), ids
