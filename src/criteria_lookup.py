"""실험 8: 숫자 질문을 data/criteria.csv 조회로 처리한다. 계산(합·차·비교)은 하지 않고 LLM은 조회한 행을 설명만 한다.

조회 규칙 (규칙 기반, 비용 0)
- 대학이 1개로 뽑혀야 하고(query_filter), 학번이 있으면 모두 2022~2026학번이어야 한다. 아니면 조회 안 함 → RAG
- 질문에 숫자 의도("몇 학점", "이수학점", "몇 점", "한 학기 최대" 등)와 항목 키워드가 함께 있어야 한다
    졸업학점 / 평점_최저 / 수강상한_학기 / 부전공(이수학점 + 부전공시 주전공 학점) / 복수전공(이수학점 + 복수전공시 주전공 학점)
- 계산·비교 단서("비교", "중에", "더 적", "심화" 등)가 있으면 조회 안 함 → RAG
- 행은 기준값여부=기준만, 학번 구간에 맞는 것. 학번이 여러 개면 학번마다 조회. 학번이 없으면 구간과 무관하게 모두
- 학과를 지목하면 그 대상 행(대상 이름의 단어 단위 일치, E22b: 글자 경계 규칙 `target_mentioned`), 아니면 대학 전체 행. 지목한 학과에 맞는 행이 없으면 조회 안 함 → RAG
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

COMPARE_RE = re.compile(r"비교(?!과)|중에|이랑 .*(중|더)|더 (많|적)|어느 쪽|심화")  # E13: "비교과"의 "비교"는 비교 질문이 아니다
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


_PARTICLE = r"(?:이랑|에서|으로|[은는이가을를의도에와과로만랑])?"


def targets_of(row_or_target):
    """행 대상 문자열을 학과 이름 목록으로. E23: 묶음 행은 대상에 학과 이름을 쉼표로 나열한다(예: '생명공학과,식품영양학과'). 공백은 이름 안에 든 것으로 본다"""
    t = row_or_target["대상"] if isinstance(row_or_target, dict) else row_or_target
    return [x.strip() for x in t.split(",") if x.strip()]


def target_mentioned(target, question):
    """질문이 행의 대상 이름을 말했는가(E22b). 글자 경계에서만 걸린다: 앞은 한글이 아니고, 뒤는 한글이 아니되 조사·접미어(학과·학부·전공·과)는 허용.
    비교 이름은 괄호를 뺀 전체 이름, 접미어를 뗀 이름(2자 이상), '이학·공학…계열'은 부분+'계열'. 옛 규칙(norm 부분 문자열)은
    '교육'이 '기계금속공학교육과' 안에 걸리고 '의'·'약'·'및' 같은 한 글자가 아무 질문에나 걸렸다."""
    q = re.sub(r"\([^)]*\)", "", question)
    pats = []
    for t in (w for name in targets_of(target) for w in name.split()):
        stem = norm(t)
        if not stem:
            continue
        full = re.sub(r"\([^)]*\)", "", t).strip()
        if len(full) >= 2:
            pats.append(re.escape(full))
        if len(stem) >= 2:
            pats.append(re.escape(stem) + r"(?:학과|학부|전공|과)?")
        if full.endswith("계열") and "·" in full:
            pats += [re.escape(p) + "계열" for p in full[:-2].split("·") if p]
    return any(re.search(rf"(?<![가-힣])(?:{p}){_PARTICLE}(?![가-힣])", q) for p in pats)


def items_for(q):
    # E12: 재수강·재이수의 "수강"은 수강상한 의도가 아니라 이 두 낱말을 지우고 본다.
    # "수강…할 수/신청"은 학점·상한 단서가 같이 있을 때만 수강상한이다(수강신청 일정 같은 질문은 RAG).
    q2 = re.sub(r"재수강|재이수", "", q)
    if re.search(r"한 학기.*(최대|몇 학점)", q2) or (re.search(r"수강.*(할 수|신청)", q2) and re.search(r"학점|최대|상한|한도|제한", q2)):
        return ["수강상한_학기"]
    if "평점" in q and re.search(r"몇 점|이상|\d\.\d", q):
        return ["평점_최저"]
    if re.search(r"복수전공|다전공|제2전공", q) and re.search(r"몇 학점|이수학점", q):
        return BUNDLE["복수전공"]
    if "부전공" in q and re.search(r"몇 학점|이수학점", q):
        return BUNDLE["부전공"]
    if "졸업" in q and re.search(r"몇 학점|졸업학점", q) and "말고" not in q and "한 학기" not in q:
        return ["졸업학점"]
    if "비교과" in q and re.search(r"몇|얼마|시간|유닛|이수", q):  # E13
        return ["비교과_이수"]
    if re.search(r"공학\s?(교육)?\s?인증", q):  # E27: 공학인증 안내 행(한남 공학교육인증 운영학과). 학과 행이 없으면 아래에서 RAG로 간다
        return ["공학인증_안내"]
    return None


# E25b: 편입_이수요건 조회는 그 학교의 편입 행이 다루는 주제가 질문에 있을 때만 간다(학교 무관 일반 규칙).
# 주제어 후보는 이 상수 한 곳에 두고, 학교별로 그 학교 편입 행의 조건·항목원어에 실제로 나오는 낱말만 쓴다
# (배재: 교양필수·전공필수·면제·아펜젤러·채플 / 한밭: 전공·심화전공·교양·학점). 행에 없는 주제(채플·봉사·졸업시험 등)는 RAG로 간다.
# "학점"을 묻는 질문은 그 학교 편입 행에 학점이 적혀 있을 때만(한밭 50학점·10학점) 이수요건이고, 배재처럼 행에 학점이 없으면 편입 학점 기준(제64조 ⑤)이라 RAG(서비스 점검 #11)다.
TRANSFER_TOPIC_WORDS = ("전공", "심화전공", "기본전공", "교양", "핵심교양", "일반교양", "대학특화", "필수", "면제", "채플", "아펜젤러", "기독교정신", "인성", "학점", "비교과", "봉사", "졸업시험")


def transfer_topics(univ):
    text = " ".join(r["조건"] + " " + r["항목원어"] for r in CRITERIA if r["대학"] == univ and r["항목"] == "편입_이수요건" and r["기준값여부"] == "기준")
    return {w for w in TRANSFER_TOPIC_WORDS if w in text}


def transfer_route(univ, q):
    if "편입" not in q:
        return False
    topics = transfer_topics(univ)
    if "학점" in q and "학점" not in topics:
        return False
    return any(w in q for w in topics if w != "학점")


def extra_area_items(q):
    """E27b: 질문이 졸업학점·교양·전공 가운데 둘 이상을 한꺼번에 물으면 그 항목 전부(질문에 나온 순서가 아닌 고정 순서). 하나뿐이면 빈 목록.
    복수전공·다전공·제2전공·부전공의 "전공"은 영역 낱말이 아니므로 지우고 본다."""
    q2 = re.sub(r"복수전공|다전공|제2전공|부전공|연계전공|융합전공", "", q)
    found = []
    if re.search(r"졸업\s?학점|졸업.*학점", q2):
        found.append("졸업학점")
    if "교양" in q2:
        found.append("교양")
    if "전공" in q2:
        found.append("전공")
    return found if len(found) >= 2 and "학점" in q2 else []


def in_range(row, year):
    start = int(row["입학년도_시작"]) if row["입학년도_시작"] else -1
    end = int(row["입학년도_끝"]) if row["입학년도_끝"] else 9999
    return start <= year <= end


def dept_in_criteria(univ, q):
    """질문이 말한 학과가 이 대학 기준표의 학과·묶음 행 대상에 이름이 나오는가(E27)"""
    return any(r["대학"] == univ and r["기준값여부"] == "기준" and r["대상"] != "전체" and any(target_mentioned(t, q) for t in targets_of(r)) for r in CRITERIA)


# E27: 학과를 말하고 영역별·졸업요건·전공/교양 기준을 묻는 질문은 그 학과·학번의 졸업학점·교양·전공·대학특화 행을 조회한다(RAG는 표 열을 잃어 계열별 숫자를 뒤섞을 수 있다).
# 정규식은 "졸업 평점 기준"·"수강 기준"처럼 다른 주제의 "기준"을 가져가지 않게 영역 낱말에 붙은 요건·기준만 본다. 학교 행이 없는 항목은 건너뛴다.
AREA_ASK_RE = re.compile(r"영역별|(?:졸업|전공|교양|대학특화)\s?(?:요건|기준)")
AREA_ITEMS = ["졸업학점", "교양", "전공", "기본전공", "심화전공", "대학특화"]


def lookup(question):
    """반환: (결과, 사유). 결과는 {학번 또는 None: [criteria 행]} 또는 None(조회 안 함 → RAG)"""
    univ = query_filter.extract_universities(question)
    if len(univ) != 1:
        return None, "대학이 0개 또는 여러 개"
    years = query_filter.extract_years(question)
    if any(y < 2022 or y > 2026 for y in years):
        return None, "범위 밖 학번"
    items = items_for(question)
    if transfer_route(univ[0], question):  # E25b: 편입 행이 다루는 주제(전공·교양·필수·면제 등)가 질문에 있으면 편입_이수요건
        items = ["편입_이수요건"]
    optional = False
    multi = extra_area_items(question) if items == ["졸업학점"] or not items else []
    opt_items = set()
    if multi:  # E27b: 졸업학점·교양·전공 중 둘 이상을 묻는 질문은 모두 조회. 행이 없는 항목은 건너뛴다(기존 졸업학점 단독 조회가 새로 RAG로 가지 않게)
        items = multi
        opt_items = set(multi) - {"졸업학점"} if "졸업학점" in multi else set(multi)
        if "졸업학점" not in multi:
            optional = True
    if not items and AREA_ASK_RE.search(question) and dept_in_criteria(univ[0], question):
        items, optional = AREA_ITEMS, True
    if not items:
        return None, "숫자 항목 아님"
    if COMPARE_RE.search(question):
        return None, "계산·비교"
    mentions = [m for m in MENTION_RE.findall(question) if m not in SCHOOL_WORDS and m != "일반학과"]
    out = {}
    for year in years or [None]:
        rows, any_spec = [], False
        for item in items:
            cand = [r for r in CRITERIA if r["대학"] == univ[0] and r["항목"] == item and r["기준값여부"] == "기준"]
            if year:
                cand = [r for r in cand if in_range(r, year)]
            if item in sum(BUNDLE.values(), []) and "교직" not in question:
                cand = [r for r in cand if "교직" not in r["이수유형"]]
            spec = [r for r in cand if r["대상"] != "전체" and target_mentioned(r["대상"], question)]
            if spec:
                cand, any_spec = spec, True
            else:
                cand = [r for r in cand if r["대상"] == "전체"]
                if mentions and not cand and not optional and item not in opt_items:
                    return None, f"질문의 {mentions}에 맞는 대상 행 없음"
            if not cand:
                if optional or item in opt_items:
                    continue
                return None, f"{item} 행 없음(묶음 불완전)"
            rows += cand
        # 학과를 지목했는데 묶음 어디에서도 그 학과 행을 못 찾았으면 RAG로 보낸다(E8).
        # 한 항목이라도 찾았으면 나머지 항목은 전체 행을 쓴다(E12: 충남 경영학부 복수전공은 주전공 학점만 학과 행, 이수학점은 2026학번부터 학과 행).
        # E27: 학과 행이 어느 항목에도 없어도 그 학과가 이 대학 기준표에 이름이 나오는 학과(다른 항목의 학과·묶음 행)면 전체 행으로 채워 조회한다
        # (졸업학점은 대학 전체 행, 전공·교양은 학과 묶음 행인 경우 등). 기준표 어디에도 없는 이름은 E8대로 RAG로 보낸다.
        if optional and not rows:
            return None, "영역 행 없음"
        if mentions and not any_spec and not dept_in_criteria(univ[0], question):
            return None, f"질문의 {mentions}에 맞는 대상 행 없음"
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
