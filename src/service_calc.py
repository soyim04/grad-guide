"""7단계 서비스 계산 (순수 Python, LLM 없음): 남은 학점·학점 외 체크리스트·학사 선택 비교.

규칙은 모두 data/criteria.csv 행에서 읽는다(행에 없는 값은 만들지 않는다). 설계는 CLAUDE.md 7단계와 data/criteria_schema.md 규칙 8·11·12·13을 따른다.
- 영역별 계산(남은 학점)은 경영 계열 학과(BASE_DEPT)의 기본 이수 방식(단수, 충남 2026~는 심화단수, 배재 2025~는 융합과정)만 지원한다.
  판정 (2단계 드라이런, 25개 대학×학번 조합: T1 8 · T2 7 · T3 10)
    T1 영역 합이 졸업학점과 맞음 → 영역별 남은 학점
    T2 영역 합이 졸업학점보다 작음 → 영역별 + "규정 표에 영역이 지정되지 않은 학점 N", 하위 항목 합이 계와 다르면 "합이 안 맞는 영역 있음" 배지
    T3 교양이 % 표기이거나 교양·전공 행이 없음 → 계산 없이 기준표 행을 참고 표로 보여 준다(한남·한밭)
    T0 경영 계열 밖 학과 → 총 졸업학점까지만
- 학사 선택 비교는 E11 규칙 A(criteria_calc)를 학과를 넣은 질문 문장으로 호출한다(규칙을 새로 만들지 않는다).
- 사용자가 입력한 학점·입학 구분은 이 모듈이 저장하지 않는다(성적 저장 제외).
"""

import re

import criteria_calc
import criteria_lookup as L

BASE_DEPT = {"배재": "IT경영정보학과", "충남": "경영학부", "한남": "경영정보학과", "한밭": "융합경영학과", "목원": "경영학부"}
YEARS = [2022, 2023, 2024, 2025, 2026]
ENTRY_TYPES = ["신입", "편입", "재입학"]
TOP = ("교양", "전공", "일반선택", "대학특화", "공유혁신", "MSC교과", "교직필수")
KID_PREFIX = {
    "교양": ("교양필수", "교양핵심", "교양선택", "교양_"),
    "전공": ("전공필수", "전공선택", "전공기초", "전공핵심", "전공심화", "기본전공", "심화전공"),
    "공유혁신": ("공유혁신_",),
}
OVER_NOTE = "초과분 인정 여부는 학과 확인 필요"
UNASSIGNED_NOTE = "규정 표에 영역이 지정되지 않은 학점"


def _detail(item):
    return item in TOP or any(item.startswith(p) for ks in KID_PREFIX.values() for p in ks)


AREA_UNIVS = {"배재", "목원", "한남"}  # E23: 경영 계열 밖 학과도 영역별 기준 행(묶음 행)이 있는 대학


def default_method(univ, year, dept=None):
    """기본 이수 방식. 충남 2026~는 책자가 심화단수를 기본 유형으로 적는다(스키마 충남 매핑), 배재 2025~는 단수가 불가라 융합과정.
    E23: 배재 2025~에서 공유혁신과정이 없는 학과(별지3 공유혁신 칸 '-': 유아교육·간호·건축·글로벌자율융합·평생교육융합)는 표가 단수전공으로 적어 단수."""
    if univ == "충남" and year >= 2026:
        return "심화단수"
    if univ == "한남" and year <= 2022:  # E26: 2019~2022 한남 이수 선택지는 심화전공·다전공뿐(시행세칙 제12조 ④ 1호)이라 기본은 심화단수
        return "심화단수"
    if univ == "배재" and year >= 2025:
        if dept and dept != BASE_DEPT[univ] and not any(r["대학"] == univ and r["항목"] == "교양" and r["이수유형"] == "융합과정" and L.in_range(r, year) and dept in L.targets_of(r)
                                                      for r in L.CRITERIA)                 and any(r["대학"] == univ and r["항목"] == "교양" and r["이수유형"] == "단수" and L.in_range(r, year) and dept in L.targets_of(r) for r in L.CRITERIA):
            return "단수"
        return "융합과정"
    return "단수"


def _rank(r, dept):
    if dept and (r["대상"] == dept or dept in L.targets_of(r)):
        return 0
    if r["대상"] == "전체":
        return 2
    return 9


def _best(univ, dept, year, pred, utype):
    """항목마다 가장 구체적인 대상 행(학과 > 전체, 규칙 8). 기준 행만."""
    best = {}
    for r in L.CRITERIA:
        if r["대학"] != univ or r["기준값여부"] != "기준" or not pred(r["항목"]) or not L.in_range(r, year) or r["이수유형"] != utype:
            continue
        k = _rank(r, dept)
        if k == 9:
            continue
        cur = best.get(r["항목"])
        if cur is None or k < cur[0]:
            best[r["항목"]] = (k, [r])
        elif k == cur[0]:
            cur[1].append(r)
    return [x for _, rs in best.values() for x in rs]


def _rng(r):
    """(최소, 최대) 학점. % 표기는 None. 이내는 (0, 값)"""
    if r["단위"] == "%":
        return None
    lo = float(r["값"]) if r["값"] else 0.0
    hi = float(r["값_최대"]) if r["값_최대"] else lo
    return (0.0, lo) if r["비교"] == "이내" else (lo, hi)


def fmt_value(r):
    if not r["값"]:
        return "(값 없음)"
    v = r["값"] + (f"~{r['값_최대']}" if r["값_최대"] else "")
    if r["단위"] == "%":
        return f"{v}% {r['비교']}".strip()
    return f"{v}{r['단위']} {r['비교']}".strip()


def fmt_basis(r):
    """영역 기준을 학생이 읽는 말로. %로 정해진 값은 무엇의 %인지 보이게 한다(예: 졸업학점의 25% 이상)"""
    if r["값"] and r["단위"] == "%":
        v = r["값"] + (f"~{r['값_최대']}" if r["값_최대"] else "")
        return f"졸업학점의 {v}% {r['비교']}".strip()
    return fmt_value(r)


def source_of(r):
    return {"id": r["행ID"], "source": r["출처조항"], "pages": r["출처쪽"], "file": r["출처파일"], "grade": r["출처등급"], "status": r["상태"]}


# ---------- 졸업학점 ----------

def grad_targets(univ):
    """졸업학점 기준 행이 있는 대상 이름(학과·계열·단과대학). '그 외 학과' 선택지"""
    names = {t for r in L.CRITERIA if r["대학"] == univ and r["항목"] == "졸업학점" and r["기준값여부"] == "기준" and r["대상"] != "전체" for t in L.targets_of(r)}
    if univ in AREA_UNIVS:  # E23: 묶음 행(영역별 기준)에 나열된 학과도 선택지에 넣는다
        names |= {t for r in L.CRITERIA if r["대학"] == univ and r["기준값여부"] == "기준" and _detail(r["항목"]) and r["대상"] != "전체" for t in L.targets_of(r)}
    return sorted(names)


def graduation_row(univ, dept, year, method=None):
    """총 졸업학점 행 하나(이수 방식 행 우선, 없으면 이수유형이 빈 공통 행: 규칙 11). 없거나 여러 개면 None"""
    method = method or default_method(univ, year, dept)
    for t in (method, ""):
        rows = _best(univ, dept, year, lambda i: i == "졸업학점", t)
        if len(rows) == 1:
            return rows[0]
    return None


# ---------- 영역별 계획 ----------

def _child_check(kids, parent_row):
    pv = _rng(parent_row)
    klo = sum(_rng(r)[0] for r in kids)
    khi = sum(_rng(r)[1] for r in kids)
    if klo == khi == pv[0] == pv[1]:
        return "일치", klo, khi
    if klo <= pv[0] <= khi:
        return "호환", klo, khi
    if khi < pv[0]:
        return "미달", klo, khi
    return "불일치", klo, khi


def area_plan(univ, dept, year):
    """영역별 계획. 반환 dict: tier, grad(행), method, areas[], unassigned, badges[], notes[], ref_rows[]"""
    method = default_method(univ, year, dept)
    grad = graduation_row(univ, dept, year, method)
    plan = {"univ": univ, "dept": dept, "year": year, "method": method, "grad": grad, "areas": [], "unassigned": None,
            "badges": [], "notes": [], "ref_rows": [], "tier": "T0"}
    if grad is None:
        plan["notes"].append("이 대학·학번·학과의 총 졸업학점 기준을 기준표에서 찾지 못했어요(확인 불가).")
        return plan
    if dept is None or (dept != BASE_DEPT[univ] and univ not in AREA_UNIVS):
        plan["notes"].append("영역별 기준은 경영 계열 학과만 기준표에 있어서, 이 학과는 총 졸업학점까지만 계산해요.")
        return plan
    det = []
    for r in L.CRITERIA:  # 참고 표: 모든 이수 방식의 영역 행
        if r["대학"] == univ and r["기준값여부"] == "기준" and _detail(r["항목"]) and L.in_range(r, year) and _rank(r, dept) < 9 and r["상태"] != "불가":
            det.append(r)
    plan["ref_rows"] = det
    rows = _best(univ, dept, year, _detail, method)
    tops = {r["항목"]: r for r in rows if r["항목"] in TOP and r["상태"] != "불가"}
    if not tops and dept != BASE_DEPT[univ]:  # E23: 영역별 묶음 행이 없는 학과(별지3 표에 없는 학과 등)는 총 졸업학점까지
        plan["notes"].append("영역별 기준은 경영 계열 학과만 기준표에 있어서, 이 학과는 총 졸업학점까지만 계산해요.")
        return plan
    g = float(grad["값"])
    lo = hi = 0.0
    pct = False
    for name in TOP:
        if name not in tops:
            continue
        row = tops[name]
        v = _rng(row)
        if v is None:
            pct = True
            plan["areas"].append({"name": name, "row": row, "min": None, "max": None, "op": row["비교"], "children": [], "check": None})
            continue
        lo += v[0]
        hi += v[1]
        kids = [r for r in rows if r["항목"] not in TOP and any(r["항목"].startswith(p) for p in KID_PREFIX.get(name, ()))]
        check = _child_check(kids, row) if kids and not all(k["조건"].startswith("전공 중") for k in kids) else None  # E24: 괄호 전공필수는 전공의 일부라 합 검사 안 함
        plan["areas"].append({"name": name, "row": row, "min": v[0], "max": v[1], "op": row["비교"], "children": kids,
                              "check": check})
    if pct:
        plan["tier"] = "T3"
        plan["notes"].append("교양이 졸업학점 대비 %로 표기돼 있고 학점 환산(올림 등) 규정을 확인하지 못해 영역별 계산은 하지 않아요. 기준표만 참고로 보여 드려요.")
        return plan
    if "교양" not in tops or "전공" not in tops:
        plan["tier"] = "T3"
        plan["notes"].append("이 학과의 기본 이수 방식에는 교양·전공 영역 기준이 함께 있지 않아 영역별 계산은 하지 않아요. 기준표만 참고로 보여 드려요.")
        return plan
    if lo <= g <= hi:
        plan["tier"] = "T1"
    elif lo < g:
        plan["tier"] = "T2"
        plan["unassigned"] = g - lo
    else:
        plan["tier"] = "T3"
        plan["notes"].append(f"영역 기준 합({lo:g})이 졸업학점({g:g})보다 커서 영역별 계산은 하지 않아요.")
        return plan
    for a in plan["areas"]:
        c = a["check"]
        if c and c[0] in ("미달", "불일치"):
            plan["badges"].append(f"합이 안 맞는 영역 있음: {a['name']} 하위 항목 합 {c[1]:g}학점이 계 {a['min']:g}학점과 달라요")
    return plan


def remaining(plan, done, total_done=None, child_done=None):
    """남은 학점. done: {영역: 이수 학점}. total_done이 None이면 영역 입력의 합.
    영역별 남은 학점과 총 남은 학점은 따로 계산한다(초과분이 다른 영역을 대신하는지는 규정 표에 없다)."""
    out_areas = []
    for a in plan["areas"]:
        if a["min"] is None:
            continue
        d = float(done.get(a["name"], 0) or 0)
        lo, hi, op = a["min"], a["max"], a["op"]
        rem = 0.0 if op == "이내" else max(0.0, lo - d)
        over = max(0.0, d - hi)
        note = ""
        if over > 0:
            note = f"기준을 {over:g}학점 넘겨 이수했어요. " + ("한도(이내)를 넘은 학점은 졸업학점으로 인정되지 않을 수 있어요. " if op == "이내" else "") + OVER_NOTE
        kids = []
        for r in a["children"]:
            kd = float((child_done or {}).get(r["항목"], 0) or 0)
            kv = _rng(r)
            kids.append({"name": r["항목"], "row": r, "done": kd, "min": kv[0], "max": kv[1], "op": r["비교"],
                         "remaining": 0.0 if r["비교"] == "이내" else max(0.0, kv[0] - kd), "over": max(0.0, kd - kv[1])})
        out_areas.append({"name": a["name"], "row": a["row"], "min": lo, "max": hi, "op": op, "done": d, "remaining": rem, "over": over,
                          "note": note, "kids": kids})
    g = float(plan["grad"]["값"])
    sum_done = float(total_done) if total_done is not None else sum(x["done"] for x in out_areas)
    return {"areas": out_areas, "grad": g, "total_done": sum_done, "total_remaining": max(0.0, g - sum_done),
            "area_remaining_sum": sum(x["remaining"] for x in out_areas), "unassigned": plan["unassigned"]}


# ---------- 학점 외 체크리스트 ----------

def _entry_word(entry):
    return {"편입": "편입", "재입학": "재입학"}.get(entry)


def _entry_applies(cond, entry):
    """조건 칸의 입학 구분 표기: '편입학자·재입학자 제외'면 그 구분은 해당 없음, '편입학생'(제외 없음)이면 편입만 해당"""
    words = [w for w in ("편입", "재입학") if w in cond]
    if not words:
        return True
    if "제외" in cond:
        return _entry_word(entry) not in words
    return _entry_word(entry) in words


def _teacher_applies(cond, teacher):
    """사범·교직 표기: '(사범대학·교직이수자 제외)'면 일반학과, '사범대학 소속 또는 교직이수자'면 사범·교직 이수자"""
    if re.search(r"(사범|교직)[^,]*제외", cond):
        return not teacher
    if re.search(r"사범|교직", cond):
        return bool(teacher)
    return True


def _pick_rows(univ, dept, year, item):
    rows = [r for r in L.CRITERIA if r["대학"] == univ and r["기준값여부"] == "기준" and r["항목"] == item and L.in_range(r, year) and _rank(r, dept) < 9]
    dept_rows = [r for r in rows if r["대상"] == dept or (dept and dept in L.targets_of(r))]
    return dept_rows or rows  # 규칙 8: 학과 행이 있으면 대학 행을 덮어쓴다


def has_teacher_rows(univ):
    return any(r["대학"] == univ and r["항목"] == "체험교과목_이수" for r in L.CRITERIA)


_REF_PAREN = re.compile(r"\s*[\(（][^()（）]*(?:제\s*\d+\s*조|개정|신설|부칙|\d{4}\.\s?\d)[^()（）]*[\)）]")


def plain_text(text):
    """체크리스트 본문은 쉬운 말 한 문장만: 조항·개정 이력·부칙이 든 괄호를 뺀다(바깥 괄호 안에 괄호가 든 경우까지 되풀이). 반환: (본문, 뺀 문구들)
    뺀 문구는 `근거 보기`로 보내고, 조항명은 출처 줄이 한 번 보여 준다."""
    removed = []
    while True:
        m = _REF_PAREN.search(text)
        if not m:
            break
        removed.append(m.group(0).strip())
        text = text[:m.start()] + text[m.end():]
    return text.strip(), removed


def checklist(univ, year, dept, entry="신입", teacher=False, transfer_grade=None):
    """학점 외 요건. criteria.csv에 있는 행만 쓴다. 항목: {title, kind(요건|없음|확인불가|해당없음), text, status, src}
    본문(text)에는 조항·개정 이력·부칙을 넣지 않는다(출처 줄과 근거 보기가 보여 준다). add()가 일반 규칙으로 한 번 더 걸러 낸다."""
    items = []

    def add(title, kind, text, r, extra=""):
        text, removed = plain_text(text)
        items.append({"title": title, "kind": kind, "text": text, "status": r["상태"] if r else "", "src": source_of(r) if r else None, "extra": " ".join(x for x in [extra] + removed if x)})

    for r in _pick_rows(univ, dept, year, "평점_최저"):
        if r["상태"] == "없음":
            add("졸업 평점", "없음", "졸업 평점 기준은 없어요. 학과에 한 번 확인하세요.", r)
        elif r["상태"] == "확인불가" or not r["값"]:
            add("졸업 평점", "확인불가", "졸업 최저 평점을 규정에서 확인하지 못했어요(확인 불가).", r)
        else:
            add("졸업 평점", "요건", f"졸업하려면 전체 평점평균 {float(r['값']):.2f}점 이상이 필요해요.", r, r["비고"] if "의예과" in r["비고"] else "")
    for r in _pick_rows(univ, dept, year, "공학인증_안내"):  # E26: 한남 공학교육인증 운영학과 안내(상태 잠정, 본문은 조건 칸)
        add("공학교육인증", "안내", r["조건"], r)
    seen = set()
    for r in _pick_rows(univ, dept, year, "비교과_이수"):
        cond = r["조건"]
        if r["상태"] == "없음":
            add("비교과", "없음", f"{r['대상']}은 비교과 이수 요건이 없어요.", r)
        elif _entry_applies(cond, entry):
            if r["행ID"] not in seen:
                seen.add(r["행ID"])
                add("비교과", "요건", f"비교과를 {r['값']}{r['단위']} 이수해야 해요." + (f" (조건: {cond})" if cond else ""), r)
        else:
            add("비교과", "해당없음", f"입학 구분 '{entry}'은 이 요건에서 제외돼요. (조건: {cond})", r)
    for r in L.CRITERIA:
        if r["대학"] == univ and r["기준값여부"] == "기준" and "이수 필수" in r["조건"] and L.in_range(r, year) and _rank(r, dept) < 9:
            seg = [s.strip() for s in r["조건"].split(";") if "이수 필수" in s][-1]
            add("0학점 이수 필수", "요건", f"{seg} — 학점은 {r['값']}학점이라 남은 학점에는 더하지 않지만, 이수해야 하는 필수 항목이에요.", r)
    for r in _pick_rows(univ, dept, year, "체험교과목_이수"):
        cond = r["조건"]
        if not _teacher_applies(cond, teacher):
            continue
        if r["상태"] == "없음":
            add("체험교과목", "없음", "일반학과는 체험교과목 요건이 없어요.", r)
        elif _entry_applies(cond, entry):
            add("체험교과목", "요건", f"체험교과목을 {r['값']}{r['단위']} 이수해야 해요. (조건: {cond})", r)
        else:
            add("체험교과목", "해당없음", f"입학 구분 '{entry}'은 이 요건에서 제외돼요. (조건: {cond})", r)
    if entry == "편입":  # E15: 편입 요건(항목 `편입_이수요건`, 배재 일반편입). 2학년 편입 전용 행은 2학년을 고른 때만
        tg = transfer_grade or TRANSFER_DEFAULT_GRADE
        found = False
        for r in L.CRITERIA:
            if r["대학"] != univ or r["항목"] != "편입_이수요건" or r["기준값여부"] != "기준" or not L.in_range(r, year):
                continue
            cond = r["조건"]
            if cond.startswith("2학년") and tg != "2학년":
                continue
            found = True
            text = cond.split(": ", 1)[-1]
            kind = "안내" if "면제" in text and "예외" not in text else "요건"
            extra = "학칙·세칙이 아니라 강의시간편람(B등급)에 있는 내용이에요." if r["출처등급"] == "B" else ""
            add(r["항목원어"] or "편입 이수 요건", kind, text + ("." if not text.endswith(".") else ""), r, extra)
        if found:
            add("학사편입", "안내", "여기 내용은 일반편입 기준이에요. 학사편입은 규정이 달라 학과에 확인하세요.", None)
    return items


# ---------- 학사 선택 비교 ----------

SIDES = (("부전공", "부전공시_주전공_전공학점", "부전공_이수학점"), ("복수", "복수전공시_주전공_전공학점", "복수전공_이수학점"))


def compare_question(univ, year, dept):
    term = "다전공" if univ in ("배재", "한남") else "복수전공"
    head = f"{univ}대 {year}학번" + (f" {dept}" if dept else "")
    return f"{head} 학생은 부전공이랑 {term} 중에 전공학점이 더 적게 드는 건 뭐야?"


def _one(univ, dept, year, item):
    """항목 행 하나(학과 > 전체, 규칙 8). 교직 이수유형·'비교 제외' 행(규칙 10)·불가 행은 선택지에서 뺀다. 반환: (행 또는 None, 사유)"""
    rows = [r for r in L.CRITERIA if r["대학"] == univ and r["기준값여부"] == "기준" and r["항목"] == item and L.in_range(r, year)
            and "교직" not in r["이수유형"] and not r["조건"].startswith("비교 제외") and r["상태"] != "불가" and _rank(r, dept) < 9]
    if not rows:
        return None, "기준표에 해당 행이 없어요"
    k = min(_rank(r, dept) for r in rows)
    rows = [r for r in rows if _rank(r, dept) == k]
    if len(rows) != 1:
        return None, f"행이 {len(rows)}개라 하나로 정할 수 없어요"
    r = rows[0]
    if r["상태"] in ("확인불가", "없음") or not re.fullmatch(r"\d+(\.\d+)?", r["값"] or ""):
        return None, f"{r['행ID']}의 값을 확인할 수 없어요(상태 {r['상태']})"
    return r, ""


def compare(univ, year, dept):
    """부전공 ↔ 복수·다전공 전공학점 비교(전공학점 합 = 주전공 요구 학점 + 이수 학점). 행은 스키마 규칙 8로 항목마다 고른다.
    주전공 학점 행이 없으면 그 쪽 합은 계산하지 않고 '확인 불가'로 둔다(학과 확인 필요). 반환 dict(ok, table[], diff, less, ...)"""
    table, reasons = [], []
    for key, major_item, extra_item in SIDES:
        name = "부전공" if key == "부전공" else ("다전공" if univ in ("배재", "한남") else "복수전공")
        major, why_major = _one(univ, dept, year, major_item)
        extra, why_extra = _one(univ, dept, year, extra_item)
        total = float(major["값"]) + float(extra["값"]) if major and extra else None
        for why, label in ((why_major, f"{name}의 주전공 요구 학점"), (why_extra, f"{name}의 이수 학점")):
            if why:
                reasons.append(f"{label}: {why}")
        table.append({"name": name, "major": major, "extra": extra, "total": total})
    if not any(t["extra"] for t in table):
        return {"ok": False, "why": "; ".join(reasons), "question": compare_question(univ, year, dept)}
    full = all(t["total"] is not None for t in table)
    less = diff = None
    if full:
        a, b = table
        diff = abs(a["total"] - b["total"])
        less = None if diff == 0 else (a["name"] if a["total"] < b["total"] else b["name"])
    rows = [r for t in table for r in (t["major"], t["extra"]) if r]
    # 범위로 정해진 값(값_최대 있음)은 가장 작은 값으로 더했다. 합이 최저값 기준임을 화면에 알린다(E20 데이터 보완, 한밭 융합경영학과 HB-011·HB-023)
    floor_note = ("범위로 정해진 값은 가장 작은 값(최저값) 기준으로 더했어요. 학과 확인 필요."
                  if any(r["값_최대"] for r in rows) else "")
    return {"ok": True, "full": full, "floor_note": floor_note, "table": table, "diff": diff, "less": less, "reasons": reasons, "rows": rows,
            "notes": [r["비고"] for r in rows if "선택 불가" in r["비고"]],
            "question": compare_question(univ, year, dept), "department_hint": dept}


def explain_question(univ, year, dept):
    """LLM 설명(E11 계산 경로)을 쓸 수 있는 질문 문장. 학과를 넣은 문장이 안 되면 학과 없이, 둘 다 안 되면 None"""
    for d in ((dept, None) if dept else (None,)):
        q = compare_question(univ, year, d)
        if criteria_calc.calc(q)[0] is not None:
            return q
    return None


def remaining_major(total_major, done_major):
    return max(0.0, float(total_major) - float(done_major))


# ---------- 편입생 학번 안내 (사이드바) ----------
# 2026-11-09 조사(eval/experiments.md E14 기록). 자동 변환은 하지 않는다: 규정이 편입 연도를 입학 연도보다 2년 늦게 병기한 것은
# 3학년 편입 기준으로 읽는 해석이라 2학년 편입 등에는 맞지 않을 수 있다.
TRANSFER_NOTE = {
    "배재": {"text": "편입생은 2년 앞 학번을 고르세요. (예: 2025년 편입 → 2023학번)",
             "basis": ["3학년 편입 기준이에요. 그 외 학년은 학과에 확인하세요.",
                       "배재대학교 학칙 시행세칙(Ⅰ) 제17조 ⑦: \"2024학년도 이전 입학생, 2026년 이전 편입생\" / \"2025학년도 이후 입학생, 2027년 이후 편입생\" (편입 연도 = 입학 연도 + 2)",
                       "배재대학교 학칙 시행세칙(Ⅰ) 제63조 ②: 일반편입학은 \"3학년, 4학년에 편입학을 허가할 수 있다\"(2학년 편입은 제64조 ① 표에만 있음)",
                       "배재대학교 학칙 시행세칙(Ⅰ) 제64조 ④: 편입학생의 교육과정 이수는 편입학한 학년의 학부(과) 교육과정을 적용함을 원칙으로 한다",
                       "규정에 3학년 편입이라고 적힌 것은 아니에요. 편입 연도와 입학 연도가 2년 차이로 병기된 것을 3학년 편입 기준으로 읽은 해석이에요."]},
    "한남": {"text": "편입생은 2년 앞 학번을 고르세요. (예: 2025년 편입 → 2023학번)",
             "basis": ["3학년 편입 기준이에요. 그 외 학년은 학과에 확인하세요.",
                       "한남대학교 학칙 시행세칙 제12조: \"2019~2022학년도 입학생, 2021~2024년 편입생\" / \"2023학년도 이후 입학생, 2025년 이후 편입생\" (편입 연도 = 입학 연도 + 2)",
                       "한남대학교 학칙 시행세칙 제20조의2: 전공 이수방법도 같은 방식으로 \"2023학년도 이후 입학생, 2025년 이후 편입생\"을 구분",
                       "규정에 3학년 편입이라고 적힌 것은 아니에요. 편입 연도와 입학 연도가 2년 차이로 병기된 것을 3학년 편입 기준으로 읽은 해석이에요."]},
}
TRANSFER_NOTE["한밭"] = {"text": "편입생은 2년 앞 학번을 고르세요. (예: 2025년 편입 → 2023학번)",
                       "basis": ["3학년 편입 기준이에요. 그 외 학년은 학과에 확인하세요.",
                                 "근거는 규정 원문이 아니라 한밭대 졸업요건 웹페이지(출처 등급 C) 1쪽이에요: \"편입생은 입학년도 3학년 적용 규정 및 기준을 따름\"",
                                 "같은 웹페이지의 졸업요건 표: \"2019학년도 이후 신입생(2021학년도 이후 편입생)\" (편입 연도 = 입학 연도 + 2)",
                                 "학칙·학사운영규정 원문에서는 편입 학번 기준을 찾지 못했어요. 웹페이지 안내라서 학과에 확인하세요."]}
TRANSFER_CHECK_LINE = "편입생은 적용 학번을 학과에서 확인하세요."  # 규정에서 못 찾은 대학(충남·목원): 사이드바 한 줄만, 근거 접기 없음


def transfer_note(univ):
    """입학 구분이 편입일 때 사이드바에 보여 줄 안내: {text, basis[]} (basis는 근거 접기용, 없으면 [])
    배재·한남은 규정 근거(편입 연도 = 입학 연도 + 2)가 있어 2년 앞 학번 안내와 근거, 그 밖은 학과 확인 한 줄."""
    return TRANSFER_NOTE.get(univ) or {"text": TRANSFER_CHECK_LINE, "basis": []}


# ---------- 배재 일반편입 (E15, 세칙Ⅰ 제64조) ----------
TRANSFER_GRADES = ["2학년", "3학년", "4학년"]
TRANSFER_DEFAULT_GRADE = "3학년"  # 화면은 3학년 기준 고정(선택 칸 없음). 2·4학년 행은 기준표에만 남겨 둔다
TRANSFER_MAJOR_NOTE = ("편입 전공 기준(제64조 ⑤)으로 계산했어요. 전적대학에서 인정받은 전공 학점도 포함해서 넣으세요. "
                       "교양·일반선택은 편입 인정학점이 영역으로 구분되지 않아 참고용이에요.")


def uses_transfer_grade(univ):
    """편입 학년을 고르게 할 대학(편입 전공 행이 있는 대학)"""
    return any(r["대학"] == univ and r["항목"].startswith("편입_전공_") for r in L.CRITERIA)


def transfer_major_row(univ, dept, year, grade):
    """편입 전공 기준 행(2·3학년 45, 4학년 24). 없으면 None"""
    item = "편입_전공_4학년" if grade == "4학년" else "편입_전공_2~3학년"
    rows = [r for r in L.CRITERIA if r["대학"] == univ and r["항목"] == item and r["기준값여부"] == "기준" and L.in_range(r, year) and _rank(r, dept) < 9]
    rows.sort(key=lambda r: _rank(r, dept))
    return rows[0] if rows else None


def apply_transfer(plan, grade):
    """영역별 계획의 전공 기준을 편입 행으로 바꾼 사본을 돌려준다(전필·전선 세부 항목과 표 불일치 안내는 편입에 적용되지 않아 뺀다).
    영역별 계산을 하지 않는 계획(T3·T0)이거나 편입 행이 없으면 원본 그대로."""
    if plan["tier"] not in ("T1", "T2") or not plan["grad"]:
        return plan
    row = transfer_major_row(plan["univ"], plan["dept"], plan["year"], grade)
    if row is None:
        return plan
    lo, hi = _rng(row)
    new = dict(plan)
    new["areas"] = [dict(a, row=row, min=lo, max=hi, op=row["비교"], children=[], check=None) if a["name"] == "전공" else dict(a) for a in plan["areas"]]
    new["unassigned"] = None
    new["badges"] = []
    new["notes"] = [TRANSFER_MAJOR_NOTE]
    new["transfer"] = {"grade": grade, "row": row}
    return new


def transfer_cap_row(univ, grade, grad_value):
    """전적대학 인정학점 상한 행(졸업학점 열 × 편입 학년). 130·127 칸만 기준표에 있다. 없으면 None"""
    cond = f"졸업학점 {int(float(grad_value))}"
    for r in L.CRITERIA:
        if r["대학"] == univ and r["항목"] == f"편입_인정학점_상한_{grade}" and r["조건"] == cond and r["기준값여부"] == "기준":
            return r
    return None


def transfer_cap_text(univ, grade, grad_value):
    r = transfer_cap_row(univ, grade, grad_value)
    if r is None:
        return None
    return f"전적대학에서 인정받을 수 있는 학점은 최대 {r['값']}학점이에요(졸업학점 {int(float(grad_value))}, {grade} 편입, {r['출처조항'].split(' (')[0]})."


# ---------- 규정 안내 탭: "확인 불가" 답에 붙이는 체크리스트 안내 ----------
# 규칙(2026-11-09 승인): 호출하는 쪽이 "확인 불가" 배지가 있을 때만 쓴다. 질문 속 낱말이 체크리스트 항목의 제목 낱말이나 항목 본문의
# 긴 고유 낱말(6자 이상)과 겹칠 때 그 항목을 돌려준다. "졸업·이수·필수·학점" 같은 일반 낱말은 제외한다.
# 알려진 한계: "학점 말고 졸업하려면 뭐가 더 필요해?" 같은 문장 의도는 보지 않는다(개발용 문항 맞춤이 되므로 추가하지 않기로 함).
HINT_GENERIC = {"졸업", "이수", "필수", "학점", "요건", "항목", "필요", "프로그램", "일반학과", "학과", "학생", "대학", "졸업요건", "이수해야", "해야"}
_JOSA = re.compile(r"(은|는|이|가|을|를|에|에서|도|의|와|과|로|으로|인가|인지|이나|나)$")


def _hint_words(text):
    out = set()
    for w in re.findall(r"[가-힣]{2,}", text):
        out.add(_JOSA.sub("", w) if len(w) > 3 else w)
    return out


def _hint_keys(item):
    keys = {w for w in _hint_words(item["title"]) if w not in HINT_GENERIC}
    keys |= {w for w in _hint_words(item["text"]) if len(w) >= 6 and w not in HINT_GENERIC}
    return keys


def checklist_hint(question, univ, year, dept, entry="신입", teacher=False):
    """질문과 관련 있어 보이는 체크리스트 항목 제목 목록(중복 없음, 없으면 [])"""
    if not isinstance(year, int):
        return []
    compact = re.sub(r"\s", "", question)
    titles = []
    for it in checklist(univ, year, dept, entry, teacher):
        if it["kind"] not in ("요건", "없음"):
            continue
        if any(k in compact for k in _hint_keys(it)) and it["title"] not in titles:
            titles.append(it["title"])
    return titles
