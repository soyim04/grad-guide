"""배재대 개설 과목 안내(7단계 확장): 분반 분류·요일 파싱·제한 문구 판정·영역별 목록. LLM은 쓰지 않는다.

가공본(data/courses_baejae_2026-2.json)은 build_courses.py가 만들고 커밋하지 않는다. 화면(ui_pages.py)과 점검(check_service.py)이 이 파일의 규칙을 같이 쓴다.
수강 가능 여부는 판정하지 않는다: 강한 제한 문구가 있으면 "수강 제한 있음" 배지만 달고 비고 원문은 그대로 보여 준다.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = "courses_baejae_2026-2.json"
DATA_NOTE = "2026-2학기 포털 자료 기준(2026-11-09 내려받음), 정원·수강인원은 그 시점 값"
FOOTER = "2026-2학기 포털 자료 기준(11월 9일 내려받음)이에요. 정원과 수강 인원은 그 시점 값이라 지금과 다를 수 있어요."
GRADE_LINE = "교양·공유혁신은 학년 자료가 없어요."  # 대상 학년은 전공(IT경영정보)만 포털 학년 필터 자료로 연결했다(E18c)
GRADES = ["1학년", "2학년", "3학년", "4학년"]

# ---------- 분류 ----------
# 교필선 비고 앞 괄호 → (영역 키, 하위)
ELECTIVE_AREAS = {
    "글로벌-언어영역": ("교양_글로벌언어", ""),
    "글로벌-세계시민영역": ("교양_글로벌세계시민", ""),
    "글쓰기와토론영역": ("교양_글쓰기와토론", ""),
    "미래와기술영역": ("교양_미래와기술", ""),
    "균형학문-사회와문화영역": ("교양_균형학문", "사회와문화"),
    "균형학문-자연과과학영역": ("교양_균형학문", "자연과과학"),
    "균형학문-인문과예술영역": ("교양_균형학문", "인문과예술"),
}
AREA_LABEL = {
    "전공": "전공 (IT경영정보학과)",
    "교양필수": "교양필수",
    "교양_글로벌언어": "글로벌-언어",
    "교양_글로벌세계시민": "글로벌-세계시민",
    "교양_글쓰기와토론": "글쓰기와토론",
    "교양_미래와기술": "미래와기술",
    "교양_균형학문": "균형학문",
    "교양_비전설계": "비전설계",
    "공유혁신": "공유혁신",
    "교선": "교선 전체",
    "교양_영역미표시": "교필선 (영역 표시 없음)",
    "공유혁신_기타": "융합전공·마이크로디그리 (영역 미분류)",
    "타학과전공": "다른 학과 전공 (공유대학 가상)",
}
# 학번 범위별로 보여 줄 영역(화면 순서). 비전설계는 2022~2024학번에는 교양 영역, 2025학번부터는 공유혁신 안에 있다(criteria BJ-016·BJ-035).
AREAS_OLD = ["전공", "교양필수", "교양_글로벌언어", "교양_글로벌세계시민", "교양_글쓰기와토론", "교양_미래와기술", "교양_균형학문", "교양_비전설계", "교선", "교양_영역미표시", "공유혁신_기타"]  # 2022~2024
AREAS_NEW = ["전공", "공유혁신", "교양필수", "교양_글로벌언어", "교양_글로벌세계시민", "교양_글쓰기와토론", "교양_미래와기술", "교양_균형학문", "교선", "교양_영역미표시", "공유혁신_기타"]  # 2025~
# 내부 분류 키 → 화면 영역 키(학번 범위별)
INNOV_PARTS_NEW = ("혁신교육과미래설계", "전공융합설계", "비전설계")  # 2025~ 공유혁신 안의 하위
OTHER_VIEW = "타학과전공"
DAYS = "월화수목금토일"


def classify(rec):
    """분반 한 줄 → {영역, 하위}. 영역은 내부 분류 키(전공·교양필수·교양_*·교선·교양_영역미표시·타학과전공·공유혁신_*)"""
    f, memo, name = rec["파일"], rec["비고"], rec["과목명"]
    if f == "IT경영정보":
        return {"영역": "전공", "하위": rec["이수구분"]}
    if f == "공유대학가상":
        return {"영역": "타학과전공", "하위": rec["이수구분"]}
    if f == "교필":
        return {"영역": "교양필수", "하위": ""}
    if f == "교선":
        return {"영역": "교선", "하위": ""}
    if f == "교필선":
        m = re.match(r"\s*[\(（]([^)）]*)[\)）]", memo)
        key = ELECTIVE_AREAS.get(m.group(1)) if m else None
        if key:
            return {"영역": key[0], "하위": key[1]}
        return {"영역": "교양_영역미표시", "하위": ""}
    assert f == "공유혁신", f
    if name == "혁신교육과미래설계":
        return {"영역": "공유혁신_혁신교육과미래설계", "하위": "전필"}
    if "비전설계-진로" in memo or "교양 비전설계 영역" in memo:
        return {"영역": "공유혁신_비전설계", "하위": "진로·취창업"}
    if "비전설계-자기설계" in memo:
        return {"영역": "공유혁신_비전설계", "하위": "자기설계"}
    if "전공융합설계" in memo:
        return {"영역": "공유혁신_전공융합설계", "하위": ""}
    return {"영역": "공유혁신_미분류", "하위": ""}


# ---------- 대상 학년(전공만) ----------
def build_grade_map(per_grade, base):
    """학년별 전공 파일(포털 학년 필터) → {과목코드: 대상 학년}. 과목코드로 학년을 추측하지 않는다.
    per_grade: {"1학년": [(코드, 과목명, 이수구분), ...], ...}, base: 기존 IT경영정보 파일의 [(코드, 과목명, 이수구분), ...].
    과목코드 집합이 다르거나, 한 과목이 두 학년에 있거나, 이름·이수구분이 다르면 ValueError."""
    gm, info = {}, {}
    for g, rows in per_grade.items():
        for code, name, kind in rows:
            if code in gm:
                raise ValueError(f"과목코드 {code}가 {gm[code]}와 {g}에 모두 있어요")
            gm[code], info[code] = g, (name, kind)
    bc = {code: (name, kind) for code, name, kind in base}
    if set(gm) != set(bc):
        raise ValueError(f"학년 파일과 기존 IT경영정보 파일의 과목코드가 달라요: 학년에만 {sorted(set(gm) - set(bc))}, 기존에만 {sorted(set(bc) - set(gm))}")
    diff = [code for code in bc if bc[code] != info[code]]
    if diff:
        raise ValueError(f"과목명·이수구분이 다른 과목코드: {diff}")
    return gm


# ---------- 요일 ----------
def time_kind(s):
    """시간 문자열 → ('요일', [요일...]) / ('미정', []) / ('실패', []).
    예: "A117 [월(5, 6)]", "MC208 [화(C), 목(D)]". 대괄호 안 `요일(` 패턴을 모두 모은다. 빈 칸·"(?)"는 시간 미정."""
    s = (s or "").strip()
    days = []
    for br in re.findall(r"\[([^\]]*)\]", s):
        for d in re.findall(r"([월화수목금토일])\s*\(", br):
            if d not in days:
                days.append(d)
    if days:
        return "요일", days
    if s in ("", "(?)", "?") or re.fullmatch(r"\(\?\)", s):
        return "미정", []
    return "실패", []


def parse_days(s):
    return time_kind(s)[1]


# ---------- 제한 문구 ----------
# 강한 제한 문구만 배지를 단다(전용·수강불가·수강금지·수강제한·○○ 외 수강·학년 제한). "타전공 수강 가능"·"3학년 수강 가능" 같은 허용 문구는 배지 대상이 아니다.
STRONG_RE = re.compile(r"전용|수강\s?불가|수강\s?금지|수강\s?제한|\S\s*외\s*수강|학년\s*제한|제한\s*과목|\S만\s*수강|참여학과")


def is_strong_limit(memo):
    return bool(STRONG_RE.search(memo or ""))


# ---------- 읽기·묶기 ----------
_cache = {}


def load(path=None):
    p = Path(path) if path else ROOT / "data" / DATA_FILE
    if p not in _cache:
        _cache[p] = json.loads(p.read_text(encoding="utf-8"))["분반"] if p.exists() else None
    return _cache[p]


def available():
    return load() is not None


def view_areas(year):
    """학번에 맞는 화면 영역 키 목록. 2022~2024는 비전설계가 교양, 2025~는 공유혁신 안(범위 밖 학번은 2025~ 목록으로 두지 않고 빈 목록)"""
    if not isinstance(year, int):
        return []
    if 2022 <= year <= 2024:
        return list(AREAS_OLD)
    if year >= 2025:
        return list(AREAS_NEW)
    return []


def sections_in(secs, year, view):
    """화면 영역 하나에 속하는 분반들(학번 범위 반영)"""
    if view == "공유혁신_기타":
        return [s for s in secs if s["영역"] == "공유혁신_미분류"]
    if view == "교양_비전설계":
        return [s for s in secs if s["영역"] == "공유혁신_비전설계"]
    if view == "공유혁신":
        return [s for s in secs if s["영역"].startswith("공유혁신_") and s["영역"].split("_", 1)[1] in INNOV_PARTS_NEW]
    return [s for s in secs if s["영역"] == view]


def group_courses(secs):
    """분반 → 과목코드 단위로 묶기(코드 첫 등장 순서, 이름순 정렬). 반환: [{code, name, kind, credit, sub, sections[]}]"""
    by = {}
    for s in secs:
        c = by.setdefault(s["과목코드"], {"code": s["과목코드"], "name": s["과목명"], "kind": s["이수구분"], "credit": s["학점"], "sub": s["하위"], "grade": s.get("대상학년", ""), "sections": []})
        c["sections"].append(s)
    return sorted(by.values(), key=lambda c: (c["name"], c["code"]))


def filter_sections(course, days):
    """요일을 고르면 그 요일 수업이 있는 분반만(시간 미정 분반은 '시간 미정'을 같이 골랐을 때만)"""
    if not days:
        return course["sections"]
    out = []
    for s in course["sections"]:
        sd = set(s["요일"])
        if (sd & set(d for d in days if d in DAYS)) or (not sd and "시간 미정" in days):
            out.append(s)
    return out


def remaining_count(secs):
    return sum(1 for s in secs if s.get("제한"))


# ---------- 보고 ----------
def report(sections):
    from collections import Counter
    print("\n## 파일별 분반·과목")
    for f in ["IT경영정보", "공유혁신", "공유대학가상", "교필", "교필선", "교선"]:
        ss = [s for s in sections if s["파일"] == f]
        print(f"  {f}: 분반 {len(ss)} · 과목 {len({s['과목코드'] for s in ss})}")
    print("\n## 영역·하위별 (과목 수 / 분반 수)")
    cnt = {}
    for s in sections:
        cnt.setdefault((s["영역"], s["하위"]), []).append(s)
    for (a, sub), ss in sorted(cnt.items()):
        print(f"  {a} / {sub or '-'}: 과목 {len({x['과목코드'] for x in ss})} · 분반 {len(ss)}")
    print("\n## 공유혁신 미분류 비고(앞 70자)")
    for s in [s for s in sections if s["영역"] == "공유혁신_미분류"]:
        print(f"  {s['과목코드']} {s['과목명']} {s['분반']} | {s['비고'][:70]}")
    print("\n## 전공 대상 학년(과목 수)")
    from collections import Counter as _C
    gc = _C(s["대상학년"] for s in sections if s["영역"] == "전공")
    print("  ", {g: len({s["과목코드"] for s in sections if s["영역"] == "전공" and s["대상학년"] == g}) for g in GRADES}, "· 학년 없음 전공 분반", gc.get("", 0))
    print("\n## 시간 파싱")
    kinds = Counter(time_kind(s["시간"])[0] for s in sections)
    print("  ", dict(kinds))
    for s in [s for s in sections if time_kind(s["시간"])[0] == "실패"][:15]:
        print(f"  실패: {s['과목명']} {s['분반']} | {s['시간'][:60]}")
    print("  미정 예:", Counter(s["시간"] for s in sections if time_kind(s["시간"])[0] == "미정").most_common(3))
    print("  요일 분포(분반):", dict(Counter(d for s in sections for d in s["요일"])))
    print("\n## 수강 제한 배지(강한 문구)")
    withmemo = [s for s in sections if s["비고"]]
    lim = [s for s in sections if s["제한"]]
    print(f"  전체 {len(sections)}분반 중 배지 {len(lim)} ({len(lim) / len(sections):.0%}), 비고 있는 {len(withmemo)}분반 중 {len(lim) / max(1, len(withmemo)):.0%}")
    for f in ["IT경영정보", "공유혁신", "공유대학가상", "교필", "교필선", "교선"]:
        ss = [s for s in sections if s["파일"] == f]
        print(f"  {f}: 배지 {sum(1 for s in ss if s['제한'])}/{len(ss)}")
    print("  매칭된 문구:", Counter(m.group(0).strip() for s in lim for m in [STRONG_RE.search(s["비고"])]).most_common(12))
    print("  배지 안 붙었지만 '수강'이 든 비고(앞 60자, 문구별 1건):")
    seen = set()
    for s in withmemo:
        if not s["제한"] and "수강" in s["비고"]:
            k = re.sub(r"[\d()]", "", s["비고"])[:30]
            if k not in seen:
                seen.add(k)
                print(f"    - {s['과목명']} | {s['비고'][:60]}")
