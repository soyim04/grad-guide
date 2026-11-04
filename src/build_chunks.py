"""규정 원문(A)·교육과정/편람(B)을 조항 단위로 잘라 data/chunks.jsonl 로 저장한다 (5단계).

실행 (저장소 루트에서):
  .venv\\Scripts\\python.exe -I src\\build_chunks.py            # 청킹 + 파일 저장 + 통계·샘플
  .venv\\Scripts\\python.exe -I src\\build_chunks.py --no-write  # 저장 없이 점검만
  .venv\\Scripts\\python.exe -I src\\build_chunks.py --only 한밭   # 이름에 '한밭'이 들어간 문서만 (디버그)

규칙 요약 (CLAUDE.md 5단계 '판본 규칙'과 같다)
- 입력은 data/raw (비공개). 글자 추출은 pdfplumber (pypdfium2는 숫자·괄호가 줄 끝으로 밀려 쓰지 않는다).
- 한밭 학칙은 가로 2쪽 펼침면이라 쪽을 좌우로 잘라 왼쪽 → 오른쪽 순서로 읽고, 쪽 번호는 인쇄 쪽을 쓴다.
- 조(제N조(제목) 또는 삭제 형식) 단위 청크. 1,200자 초과 시 ① ② ③ 항 경계에서 나눈다. 부칙은 부칙 블록 단위, 별표·별지는 표 단위.
- 판본 규칙:
  * 학칙·규정(A): 그 해 시행 판본. 현행만 기본 색인(기본색인=true), 이전 판은 판본="구판", 판본연도 표시 (기본색인=false).
    폐지된 규정은 판본="폐지" 로 기본 색인에 포함(함정용).
  * 교육과정·편람(B): 입학년도별 문서. 모두 기본 색인. 판본 대신 적용 입학년도(학번_시작·학번_끝)를 붙인다.
    표에 적용 학번이 없으면 비우고 비고에 적는다.
- 청크 메타데이터: 대학, 규정명, 문서종류(규정|편람), 출처등급, 판본, 판본연도, 기본색인, 구분(본문|부칙|별표|삭제|표),
  장절, 조항, 부분(n/m), 쪽_PDF, 쪽_인쇄, 학번_시작, 학번_끝, 비고, 파일.
"""
import argparse
import collections
import json
import pathlib
import random
import re
import statistics
import sys

import pdfplumber

sys.stdout.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "chunks.jsonl"
LIMIT = 1200
SEED = 20261104

# ───────────────────────── 문서 목록 ─────────────────────────
# kind: reg(조문형 규정) | tbl(쪽·표 단위, B 문서)
# rng: (시작쪽, 끝쪽) PDF 쪽, None 이면 전체
DOCS = []


def reg(school, name, file, rng=None, spread=False, ver="현행", year=None, note="", grade="A", extra_annex=False):
    DOCS.append(dict(kind="reg", school=school, name=name, file=file, rng=rng, spread=spread, ver=ver, year=year,
                     note=note, grade=grade, extra_annex=extra_annex))


def tbl(school, name, file, pages, year_start=None, year_end=None, note="", section=None, detect_window=8):
    DOCS.append(dict(kind="tbl", school=school, name=name, file=file, pages=pages, ys=year_start, ye=year_end,
                     note=note, section=section, detect_window=detect_window))


# 배재 (A)
reg("배재", "배재대학교 학칙", "baejae/학칙_2-1-01_20260227.pdf", year=2026)
reg("배재", "배재대학교 학칙 시행세칙(Ⅰ)", "baejae/학칙시행세칙1_2-1-02_20250723.pdf", year=2025)
reg("배재", "배재대학교 학칙 시행세칙(Ⅱ)", "baejae/학칙시행세칙2_2-1-3_20250703.pdf", year=2025)
# 한남 (A)
reg("한남", "한남대학교 학칙", "hannam/학칙_2-1-2_20260512.pdf", year=2026)
reg("한남", "한남대학교 학칙 시행세칙", "hannam/학칙시행세칙_2-1-3.pdf", year=None)
# 한밭 (A)
reg("한밭", "국립한밭대학교 학칙", "hanbat/학칙_20261008개정.pdf", spread=True, year=2026, extra_annex=True)
reg("한밭", "국립한밭대학교 학사운영규정", "hanbat/학사운영규정_20260522개정.pdf", year=2026, extra_annex=True)
reg("한밭", "국립한밭대학교 융합다전공 운영지침", "hanbat/융합다전공운영지침_20260601개정.pdf", year=2026, extra_annex=True)
# 목원 (A, 폐지 1건)
reg("목원", "목원대학교 학칙", "mokwon/학칙_2-1-1_20261029.pdf", year=2026)
reg("목원", "목원대학교 학칙 시행세칙", "mokwon/학칙시행세칙_2-1-2.pdf", year=2026)
reg("목원", "목원대학교 복수전공에 관한 규정", "mokwon/복수전공에관한규정_2-2-26_20260603.pdf", year=2026)
reg("목원", "목원대학교 부전공 이수에 관한 규정", "mokwon/부전공이수에관한규정_2-2-5_20260603.pdf", year=2026)
reg("목원", "목원대학교 수강 신청 규정", "mokwon/수강신청규정_2-2-1_20260225.pdf", year=2026)
reg("목원", "목원대학교 전공 및 복수전공에 관한 시행세칙 (폐지)", "mokwon/전공및복수전공시행세칙_폐지20200609.pdf", ver="폐지", year=2020,
    note="2020.6.9 폐지된 구버전. 함정용으로만 색인")
# 충남 책자 속 학칙·학사운영규정·교양지침 (A). 2026만 현행, 2022·2025는 구판
for yr, hak, rule, guide, ver in [(2026, (10, 149), (150, 193), (199, 209), "현행"),
                                  (2025, (7, 142), (143, 187), None, "구판"),
                                  (2022, (10, 125), (126, 164), None, "구판")]:
    f = f"cnu/교육과정_{yr}.pdf"
    reg("충남", "충남대학교 학칙", f, rng=hak, ver=ver, year=yr, note=f"{yr} 교육과정 책자 수록본")
    reg("충남", "충남대학교 학사운영규정", f, rng=rule, ver=ver, year=yr, note=f"{yr} 교육과정 책자 수록본")
    if guide:
        reg("충남", "충남대학교 교양교육과정 편성·이수 및 운영 등에 관한 지침", f, rng=guide, ver=ver, year=yr,
            note=f"{yr} 교육과정 책자 수록본")

# 교육과정·편람 (B): 입학년도별 문서 → 전부 기본 색인, 학번 구간 부여
tbl("한남", "한남대학교 교육과정편람 2026 · 이수원칙", "hannam/교육과정편람_2026_이수원칙.pdf", pages=[3, 4, 5, 6],
    note="표에 '2023학년도 입학생 적용' 표기", section="이수원칙", detect_window=100)
tbl("한남", "한남대학교 교육과정편람 2026 · 경상대학 경영정보학과", "hannam/교육과정편람_2026_경상대학.pdf", pages=[58, 59, 60, 61],
    section="경영정보학과 교육과정", detect_window=100)
for yr, grad, plan in [(2022, 195, (380, 381)), (2024, 17, (174, 174)), (2025, 228, (397, 397)), (2026, 242, (423, 423))]:
    f = f"cnu/교육과정_{yr}.pdf"
    tbl("충남", f"충남대학교 교육과정 {yr} · [별표 1] 학과별 졸업이수학점 (경영학부 쪽)", f, pages=[grad], year_start=yr, year_end=yr,
        note=f"{yr} 책자 = {yr}학번 적용", section="졸업학점표")
    tbl("충남", f"충남대학교 교육과정 {yr} · 경영학부 교육과정 편성표", f, pages=list(range(plan[0], plan[1] + 1)),
        year_start=yr, year_end=yr, note=f"{yr} 책자 = {yr}학번 적용", section="경영학부 편성표")
for yr in (2022, 2023, 2024, 2025, 2026):
    tbl("한밭", f"한밭대학교 융합경영학과 교육과정 {yr}", f"hanbat/융합경영학과_교육과정_{yr}.pdf", pages=[1],
        year_start=yr, year_end=yr, note=f"{yr} 교육과정 = {yr}학번 적용", section="학과 교육과정", detect_window=0)
tbl("배재", "배재대학교 2026-1 강의시간편람 · 이수안내", "baejae/강의시간편람_2026-1.pdf", pages=list(range(10, 39)),
    note="학번별 졸업자격 기준(19~27쪽)은 시행세칙Ⅰ 별지3과 대학 단위 요약이라 부분 중복(2022~2028학번), 2005~2021학번은 별지3에 없음",
    section="이수안내", detect_window=30)

# ───────────────────────── 쪽 읽기 ─────────────────────────
NUM_ONLY = re.compile(r"^\s*[-–]?\s*(\d{1,4})\s*[-–]?\s*$")
DASH_PAGE = re.compile(r"^\s*[-–]\s*\d{1,3}\s*[-–]\s*$")
RULE_LINE = re.compile(r"^[━─=\-_·]{6,}\s*$")


def norm_line(s):
    return re.sub(r"\d+", "#", s.strip())


def page_lines(text):
    t = text.replace("\r", "").replace("●", " ")
    lines = [l.rstrip() for l in t.split("\n")]
    return [l for l in lines if l.strip()]


def twocol(pg):
    ws = pg.extract_words()
    if len(ws) < 40:
        return False
    mid = [x for x in ws if x["x0"] < pg.width * 0.5 < x["x1"]]
    L = [x for x in ws if x["x1"] <= pg.width * 0.5]
    R = [x for x in ws if x["x0"] >= pg.width * 0.5]
    return len(mid) <= 0.03 * len(ws) and len(L) > 0.3 * len(ws) and len(R) > 0.3 * len(ws)


def read_pages(pdf, nums, spread, auto_cols=False):
    out = []
    for n in nums:
        pg = pdf.pages[n - 1]
        if spread or (auto_cols and twocol(pg)):
            w, h = pg.width, pg.height
            for half, box in ((1, (0, 0, w / 2, h)), (2, (w / 2, 0, w, h))):
                out.append(dict(pdf=n, half=half, sp=bool(spread), lines=page_lines(pg.crop(box).extract_text() or "")))
        else:
            out.append(dict(pdf=n, half=0, sp=False, lines=page_lines(pg.extract_text() or "")))
    return out


def detect_headers(pool):
    """쪽 머리글·바닥글: 위 3줄·아래 3줄 중 숫자를 #로 바꿨을 때 여러 쪽에 반복되는 줄."""
    cnt = collections.Counter()
    for p in pool:
        seen = set()
        for l in p["lines"][:3] + p["lines"][-3:]:
            k = norm_line(l)
            if len(l) <= 70 and k not in seen:
                seen.add(k)
                cnt[k] += 1
    numonly = sum(1 for p in pool if p["lines"] and (NUM_ONLY.match(p["lines"][0]) or NUM_ONLY.match(p["lines"][-1])))
    headers_numonly = numonly >= 0.5 * len(pool)
    thr = max(3, int(0.2 * len(pool)))
    # 쪽 번호가 들어 있는 줄(숫자 → #)만 머리글·바닥글로 본다. 표 머리글(숫자 없음)은 지우지 않는다.
    # 머리글은 글자가 있고 숫자 묶음이 적은 줄. 표의 행(숫자가 많은 줄)이나 "3-3-0" 같은 줄은 지우지 않는다.
    hs = {k for k, v in cnt.items()
          if v >= thr and re.search(r"[가-힣A-Za-z]{2,}", k) and len(k) <= 90
          and (1 <= k.count("#") <= 4 or re.search(r"#\s*/\s*#\s*$", k))}
    return hs, headers_numonly


def clean_pages(pages, headers, numonly=True):
    for p in pages:
        L = p["lines"]
        printed = None
        keep = []
        for i, l in enumerate(L):
            edge = i < 3 or i >= len(L) - 3
            if RULE_LINE.match(l):
                continue
            if edge and norm_line(l) in headers:
                m = (re.search(r"(?<![\d/])(\d{1,3})\s*/\s*\d{1,3}\s*$", l) or re.search(r"(?<!\d)(\d{1,3})\s*$", l)
                     or re.match(r"^\s*(\d{1,3})(?=\D|$)", l))
                if m:
                    printed = int(m.group(1))
                continue
            m = NUM_ONLY.match(l)
            if p["sp"] and DASH_PAGE.match(l):      # 펼침면(한밭 학칙)의 "- N -" 쪽번호 줄은 위치와 상관없이 지운다
                mm = re.search(r"\d+", l)
                if edge:
                    printed = int(mm.group(0))
                continue
            if edge and numonly and m and len(m.group(1)) <= 3:
                printed = int(m.group(1))
                continue
            keep.append(l)
        p["lines"] = keep
        p["print"] = printed
    # 한 쪽을 좌우 단으로 읽은 경우(펼침면이 아님) 인쇄 쪽 번호를 같은 쪽의 다른 반쪽에도 준다
    byp = {}
    for p in pages:
        if p["half"] and not p["sp"] and p["print"] is not None:
            byp[p["pdf"]] = p["print"]
    for p in pages:
        if p["half"] and not p["sp"] and p["print"] is None:
            p["print"] = byp.get(p["pdf"])
    return pages


def load_doc(d, extra_pool=None):
    path = RAW / d["file"]
    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
        if d["kind"] == "reg":
            a, b = d["rng"] if d["rng"] else (1, total)
            nums = list(range(a, b + 1))
            pages = read_pages(pdf, nums, d["spread"])
            pool = pages
        else:
            nums = d["pages"]
            ac = d["section"] == "경영학부 편성표"
            pages = read_pages(pdf, nums, False, ac)
            w = d["detect_window"]
            if w:
                lo, hi = max(1, min(nums) - w), min(total, max(nums) + w)
                pool = read_pages(pdf, [n for n in range(lo, hi + 1)], False, ac)
            else:
                pool = pages
        headers, numonly = detect_headers(pool)
    clean_pages(pages, headers, numonly)
    return pages


# ───────────────────────── 청킹 ─────────────────────────
HEAD = re.compile(r"^\s*제\s*(\d+)\s*조(?:\s*의\s*(\d+))?\s*(\([^)]{0,90}\)|삭\s*제|<\s*삭\s*제)")
CHAP = re.compile(r"^\s*제\s*\d+\s*(?:장|절)\s*\S.*$")
BUCHIK = re.compile(r"^\s*부\s*칙(?=\s|\(|<|\[|$)")
_LBL = r"(?:별표|별지|서식)\s*(?:제\s*)?[0-9ⅠⅡⅢⅣⅤ]+(?:\s*[-의]\s*[0-9]+)?\s*호?\s*(?:서식)?"
ANNEX = re.compile(
    r"^\s*(?:[\[\(<【]\s*" + _LBL + r"\s*[\]\)>】]|\[\s*(?:별표|별지)\s*\d+[^\]\n]*|"
    r"(?:별표|별지)\s*\d+(?:의\d+|-\d+)?\s*(?:$|[<(\[]|[가-힣]{2,}\s*(?:<|\(|$)))")
# 별표 안에서 입학연도별 표·해설을 나누는 소제목 (목원 시행세칙 별표 4 등)
SUBHEAD = re.compile(r"^\s*(?:[ⅠⅡⅢⅣ]\.\s*)?(?:학부\(과\)별\s*이수학점\s*기준표|교육과정\s*이수\s*영역별)")
CIRC = re.compile(r"^\s*[①-⑳㉑-㉟]")
# 한밭 규정류: PDF 글자 추출에서 '별표'·'별지' 글자가 빠져 "[ 2] <2024...>", "( 35 ) <2024...>" 로 나오는 표제
EXTRA_ANNEX = re.compile(r"^\s*(?:\[\s*\d+\s*\]|\(\s*\d*\s*\))\s*<\s*(?:개정|신설|삭제)?\s*(?:19|20)\d\d")
DATE_RE = re.compile(r"((?:19|20)\d\d)\s*[.년]\s*(\d{1,2})\s*[.월]\s*(\d{1,2})")


def clean_title(s):
    return re.sub(r"\s+", " ", s).strip()


def split_para(lines, limit):
    """한 덩어리 줄 목록을 limit 이하로 나눈다: ① ② ③ 항 경계 → 안 되면 줄 경계."""
    paras, cur = [], []
    for ln in lines:
        if CIRC.match(ln[0]) and cur:
            paras.append(cur)
            cur = []
        cur.append(ln)
    if cur:
        paras.append(cur)
    chunks, acc = [], []
    size = lambda ls: sum(len(x[0]) + 1 for x in ls)
    for pr in paras:
        if size(acc) + size(pr) <= limit:
            acc += pr
            continue
        if acc:
            chunks.append(acc)
            acc = []
        if size(pr) <= limit:
            acc = list(pr)
        else:  # 한 항이 너무 길면 줄 경계로
            piece = []
            for ln in pr:
                if size(piece) + len(ln[0]) + 1 > limit and piece:
                    chunks.append(piece)
                    piece = []
                piece.append(ln)
            if piece:
                acc = piece
    if acc:
        chunks.append(acc)
    return chunks


def lines_of(pages):
    out = []
    for p in pages:
        for l in p["lines"]:
            out.append((l, p["pdf"], p["print"]))
    return out


def years_in(text):
    ys = [int(y) for y in re.findall(r"(20\d\d)\s*학년도\s*입학", text)]
    ys += [int(y) for y in re.findall(r"(20\d\d)\s*학년도\s*입학자", text)]
    return sorted(set(ys))


class Maker:
    def __init__(self, d):
        self.d = d
        self.items = []

    def add(self, 구분, 조항, lines, 장절="", ys=None, ye=None, note="", rep=None):
        d = self.d
        if not lines:
            return
        # 표는 나뉜 뒷부분에도 머리 줄을 다시 붙인다 (별표·서식: 표제 2줄, 열 머리글이 있는 표: 3줄)
        nrep = rep if rep is not None else (2 if 구분 in ("별표", "서식") else 0)
        head3 = lines[:nrep]
        hlen = sum(len(x[0]) + 1 for x in head3)
        while hlen > 360 and len(head3) > 1:
            head3 = head3[:-1]
            hlen = sum(len(x[0]) + 1 for x in head3)
        body_parts = split_para(lines, LIMIT - hlen if nrep else LIMIT)
        n = len(body_parts)
        for i, part in enumerate(body_parts, 1):
            if nrep and i > 1:
                part = head3 + part
            text = "\n".join(x[0] for x in part).strip()
            if not text:
                continue
            pdfp = [x[1] for x in part]
            prt = [x[2] for x in part if x[2] is not None]
            self.items.append(dict(
                대학=d["school"], 규정명=d["name"], 문서종류="규정" if d["kind"] == "reg" else "편람",
                출처등급="A" if d["kind"] == "reg" else "B",
                판본=d.get("ver", "") if d["kind"] == "reg" else "", 판본연도=d.get("year") if d["kind"] == "reg" else None,
                구분=구분, 장절=장절, 조항=조항, 부분=f"{i}/{n}" if n > 1 else "",
                쪽_PDF=[min(pdfp), max(pdfp)], 쪽_인쇄=[min(prt), max(prt)] if prt else None,
                학번_시작=ys, 학번_끝=ye, 비고=note, 파일=d["file"], text=text))


def chunk_reg(d, pages):
    mk = Maker(d)
    L = lines_of(pages)
    isann = lambda t: ANNEX.match(t) or (d.get("extra_annex") and EXTRA_ANNEX.match(t))
    mode = "front"
    chap = ""
    last = (0, 0)
    cur = None            # 현재 조: dict(label, lines, chap)
    arts = []             # 본문 조 목록
    buchik = []           # 부칙 블록 [label, lines]
    annex = []            # 별표 [title, lines]
    front_chars = 0
    front_lines = []

    def close_art():
        nonlocal cur
        if cur:
            arts.append(cur)
            cur = None

    for ln in L:
        s = ln[0]
        if mode in ("front", "body"):
            if BUCHIK.match(s) and mode == "body":
                close_art()
                mode = "buchik"
                buchik.append([clean_title(s), [ln]])
                continue
            if isann(s) and mode == "body":
                close_art()
                mode = "annex"
                annex.append([clean_title(s)[:90], [ln]])
                continue
            m = HEAD.match(s)
            if m:
                n, sub = int(m.group(1)), int(m.group(2) or 0)
                ok = (n, sub) > last and (n - last[0] <= 40)
                if ok:
                    close_art()
                    last = (n, sub)
                    title = clean_title(m.group(3))
                    is_del = bool(re.match(r"<?\s*삭\s*제", title))
                    label = f"제{n}조" + (f"의{sub}" if sub else "") + ("" if is_del else title)
                    cur = dict(label=label, lines=[ln], chap=chap, num=(n, sub), deleted=is_del)
                    mode = "body"
                    continue
            if CHAP.match(s) and mode == "body" and not HEAD.match(s):
                close_art()
                chap = clean_title(s)[:50]
                continue
            if mode == "front":
                front_chars += len(s)
                front_lines.append(s)
                continue
            cur["lines"].append(ln) if cur else None
        elif mode == "buchik":
            if isann(s):
                mode = "annex"
                annex.append([clean_title(s)[:90], [ln]])
            elif BUCHIK.match(s):
                buchik.append([clean_title(s), [ln]])
            else:
                buchik[-1][1].append(ln)
        else:  # annex
            if isann(s):
                annex.append([clean_title(s)[:90], [ln]])
            elif SUBHEAD.match(s) and len(annex[-1][1]) > 3 and not SUBHEAD.match(annex[-1][1][0][0]):
                parent = annex[-1][0].split(" / ")[0][:40]
                annex.append([f"{parent} / {clean_title(s)[:50]}", [ln]])
            elif SUBHEAD.match(s) and len(annex[-1][1]) > 3:
                parent = annex[-1][0].split(" / ")[0][:40]
                annex.append([f"{parent} / {clean_title(s)[:50]}", [ln]])
            else:
                annex[-1][1].append(ln)
    close_art()

    if d.get("year") is None:      # 파일명에 날짜가 없는 규정: 마지막 부칙 날짜의 연도를 판본연도로 쓴다
        ys_ = [int(m.group(1)) for lab, _ in buchik for m in [DATE_RE.search(lab)] if m]
        if ys_:
            d["year"] = max(ys_)
            d["note"] = (d["note"] + " " if d["note"] else "") + "판본연도는 마지막 부칙 날짜 기준"
    # 본문: 삭제 조는 연속 구간을 하나로
    i = 0
    while i < len(arts):
        a = arts[i]
        deleted = a["deleted"] or (len(" ".join(x[0] for x in a["lines"])) <= 60 and "삭제" in a["lines"][0][0])
        if deleted:
            j = i
            while j + 1 < len(arts):
                b = arts[j + 1]
                bd = b["deleted"] or (len(" ".join(x[0] for x in b["lines"])) <= 60 and "삭제" in b["lines"][0][0])
                if bd:
                    j += 1
                else:
                    break
            lines = [x for k in range(i, j + 1) for x in arts[k]["lines"]]
            lab = a["label"] if i == j else f"{a['label']}~{arts[j]['label'].split('(')[0]} (삭제)"
            mk.add("삭제", lab, lines, a["chap"])
            i = j + 1
            continue
        mk.add("본문", a["label"], a["lines"], a["chap"])
        i += 1

    # 부칙: 너무 짧은 블록은 다음 블록과 합친다
    merged = []
    for lab, lines in buchik:
        size = sum(len(x[0]) for x in lines)
        if merged and sum(len(x[0]) for x in merged[-1][1]) < 150 and \
                sum(len(x[0]) for x in merged[-1][1]) + size <= LIMIT:
            merged[-1][1].extend(lines)
            merged[-1][2] = lab
        else:
            merged.append([lab, list(lines), lab])
    for lab, lines, last_lab in merged:
        title = lab if lab == last_lab else f"{lab} ~ {last_lab}"
        if not re.search(r"\d", title):            # '부 칙'만 있으면 본문 속 첫 날짜를 붙여 구분한다
            m = DATE_RE.search("\n".join(x[0] for x in lines))
            if m:
                title += f" [{m.group(1)}.{int(m.group(2))}.{int(m.group(3))}]"
        mk.add("부칙", clean_title(title)[:170], lines)

    # 별표·별지·서식. 입학연도별 표는 소제목 줄(첫 3줄)에서 학번을 읽고, 해설(Ⅱ.)은 앞 표의 학번을 이어받는다.
    carry = None
    for title, lines in annex:
        if len(lines) > 1 and not re.search(r"[가-힣]{3,}", re.sub(r"개정|신설|삭제", "", title)):
            title = clean_title(title + " " + lines[1][0])[:90]
        ys = ye = None
        yrs = years_in("\n".join(x[0] for x in lines[:3]))
        if len(yrs) == 1:
            ys = ye = carry = yrs[0]
        elif re.search(r"교육과정\s*이수\s*영역별", title) and carry:
            ys = ye = carry
        else:
            carry = None
        body = " ".join(x[0] for x in lines)
        kind = "별표"
        if "서식" in title[:40] or title.lstrip().startswith("【"):
            kind = "서식"
        elif len(body) <= 70 and "삭제" in body:
            kind = "삭제"
        mk.add(kind, title, lines, ys=ys, ye=ye)
    return mk.items, dict(front_chars=front_chars, last=last, n_art=len(arts), n_buchik=len(buchik), n_annex=len(annex),
                          front=" / ".join(front_lines)[:140] if front_chars > 500 else "")


def _cell(c):
    return (c or "").replace("\n", "").strip()


def chunk_gradtable(d, pages, mk):
    """충남 [별표 1] 졸업이수학점표: 대학명·학과명·세부전공 칸이 병합돼 첫 행에만 있다.
    빈 칸은 바로 위 값을 이어받고(대학이 바뀌면 학과 초기화), 학과별로 청크를 나눠 머리말에 대학·판·학과를 넣는다."""
    for p in pages:
        with pdfplumber.open(RAW / d["file"]) as pdf:
            pg = pdf.pages[p["pdf"] - 1]
            tb = max(pg.find_tables(), key=lambda t: len(t.rows))
            rows = [list(r) for r in tb.extract()]
            # 표가 쪽 아래에서 끊겨 닫는 선이 없으면 마지막 병합 칸(대학명·학과명)이 칸으로 잡히지 않고 글자만 남는다.
            # 어떤 칸에도 들어가지 않은 글자(고아 글자)를 줄 높이로 찾아 빈 칸에 채운다.
            boxes = tb.cells
            inside = lambda w, b: b[0] - 1 <= w["x0"] and w["x1"] <= b[2] + 1 and b[1] - 1 <= w["top"] and w["bottom"] <= b[3] + 1
            hdr_cells = tb.rows[0].cells
            gj = next(j for j, c in enumerate(rows[0]) if _cell(c).replace(" ", "") == "구분")
            orphans = {}
            for w in pg.extract_words():
                if w["top"] < tb.bbox[1] or w["bottom"] > tb.bbox[3] + 40 or any(inside(w, b) for b in boxes):
                    continue
                for j in range(gj):
                    cb = hdr_cells[j]
                    if cb and cb[0] - 1 <= w["x0"] and w["x1"] <= cb[2] + 1:
                        mid = (w["top"] + w["bottom"]) / 2
                        ri = next((i for i, r in enumerate(tb.rows) if r.bbox[1] <= mid <= r.bbox[3]), None)
                        if ri is not None:
                            orphans.setdefault((ri, j), []).append(w["text"])
            for j in range(gj):                      # 같은 칸의 아래 줄 조각("공학과")은 앞 조각에 붙인다
                ris = sorted(ri for (ri, jj) in orphans if jj == j)
                anchor = last = None                 # 이어 붙일 첫 줄 행, 직전 줄 행
                for ri in ris:
                    txt = "".join(orphans[(ri, j)])
                    if j == 1 and anchor is not None and last == ri - 1 and not re.search(r"(과|부|학|계열|전공)$", rows[anchor][j]):
                        rows[anchor][j] += txt
                        last = ri
                        continue
                    if not _cell(rows[ri][j]):
                        rows[ri][j] = txt
                    anchor = last = ri
        gi = next(j for j, c in enumerate(rows[0]) if _cell(c).replace(" ", "") == "구분")
        first = next(i for i in range(1, len(rows)) if _cell(rows[i][gi]))
        hdr = []
        for r in rows[:first]:
            cells = [_cell(c) for c in r[gi + 1:]]
            if any(cells):
                hdr.append("열: " + "|".join(cells))
        col = dept = sub = None
        groups, cur = [], None
        for r in rows[first:]:
            parts0 = [x.strip() for x in (r[0] or "").split("\n") if x.strip()]
            c0 = parts0[0] if parts0 and len(set(parts0)) == 1 else "".join(parts0)   # '경상대학\n경상대학' 겹침 정리
            c1 = _cell(r[1])
            c2 = _cell(r[2]) if gi == 3 else ""
            if c0:                                  # 새 대학
                col = c0
                dept = c1 or "(대학 공통)"
                sub = c2 or None
            elif c1:                                # 새 학과
                dept, sub = c1, c2 or None
            elif c2:
                sub = c2
            if col is None:
                col, dept = "(앞 쪽에서 이어짐)", "(학과명이 앞 쪽에 있음)"
            key = (col, dept)
            if cur is None or cur["key"] != key:
                cur = dict(key=key, rows=[])
                groups.append(cur)
            label = dept + (f" {sub}" if sub else "")
            vals = "|".join(_cell(c) for c in r[gi + 1:])
            cur["rows"].append((f"{label} {_cell(r[gi])} {vals}", p["pdf"], p["print"]))
        for g in groups:
            col, dept = g["key"]
            lines = [(h, p["pdf"], p["print"]) for h in hdr] + g["rows"]
            mk.add("표", f"졸업학점표 | {col} {dept}", lines, ys=d["ys"], ye=d["ye"],
                   note=d["note"] + (" / 대학명·학과명이 쪽 앞에서 이어진 행(병합 셀)" if col.startswith("(앞") else ""), rep=len(hdr))
    return mk.items


def chunk_tbl(d, pages):
    mk = Maker(d)
    sec = d["section"]
    ys, ye = d["ys"], d["ye"]
    note = d["note"]
    if sec == "경영학부 편성표":          # ■경영학부 ~ 다음 ■ 학과 제목 직전까지
        L = lines_of(pages)
        start = next((i for i, x in enumerate(L) if "■" in x[0] and "경영학부" in x[0]), None)
        if start is None:
            start = next((i for i, x in enumerate(L) if "경영학부" in x[0]), 0)
        end = len(L)
        for i in range(start + 1, len(L)):
            if "■" in L[i][0] and "경영학부" not in L[i][0]:
                end = i
                break
        # 2022년 책자 등 ■ 제목이 줄 중간에 있는 경우: 제목 줄 앞부분만
        L2 = L[start:end]
        mk.add("표", f"{sec}", L2, ys=ys, ye=ye, note=note, rep=3)
        return mk.items, {}
    if sec == "이수원칙":                 # 쪽마다 '(N학년도입학생적용)' 표기를 이어받는다
        cur_y = None
        for p in pages:
            txt = "\n".join(p["lines"])
            m = re.findall(r"(20\d\d)\s*학년도\s*입학생\s*적용", txt)
            if m:
                cur_y = int(m[0])
            # 'N학년도 입학생 적용' = N학번부터. 끝은 비운다 (criteria HN-006과 같은 해석)
            mk.add("표", f"{sec} (PDF {p['pdf']}쪽)", lines_of([p]), ys=cur_y, ye=None,
                   note=note + ", 학번_끝 비움(2023학번~)" if cur_y else "적용 학번 표기 없음")
        return mk.items, {}
    if sec == "졸업학점표":               # 표 구조로 읽어 병합 셀(대학·학과·세부전공)을 아래 행에 이어 붙인다
        return chunk_gradtable(d, pages, mk), {}
    for p in pages:
        txt = "\n".join(p["lines"])
        y0, y1, nt = ys, ye, note
        if d["file"].startswith("baejae"):
            rr = re.findall(r"(20\d\d)\s*[~\-]\s*(20\d\d)\s*학번", txt)
            single = re.findall(r"(?<![~\d])(20\d\d)\s*학번", txt)
            if rr:
                y0 = min(int(a) for a, _ in rr)
                y1 = max(int(b) for _, b in rr)
                if len({r for r in rr}) > 1:
                    nt = (note + " / " if note else "") + "한 쪽에 여러 학번 구간 혼재"
            elif single and not rr:
                y0 = min(int(x) for x in single)
                y1 = max(int(x) for x in single)
        if d["file"].startswith("hannam") and ys is None:
            nt = "적용 학번 표기 없음 (2026 편람)"
        mk.add("표", f"{sec} (PDF {p['pdf']}쪽)", lines_of([p]), ys=y0, ye=y1, note=nt,
               rep=3 if sec in ("졸업학점표", "학과 교육과정") else 0)
    return mk.items, {}


# ───────────────────────── 메인 ─────────────────────────
def finalize(items, d, idx):
    d_year = d.get("year")
    for i, it in enumerate(items, 1):
        if d["kind"] == "reg":
            it["기본색인"] = d["ver"] in ("현행", "폐지")
            if d["note"] and not it["비고"]:
                it["비고"] = d["note"]
        else:
            it["기본색인"] = True
        if it["구분"] == "서식":                 # 서식은 표시를 남기고 기본 색인에서는 뺀다
            it["기본색인"] = False
        tag = pathlib.Path(d["file"]).stem
        it["id"] = f"{idx:02d}-{i:04d}"
        head = f"[{it['대학']} | {it['규정명']}" + (f" ({it['판본']}{it['판본연도'] or ''})" if it["판본"] == "구판" else "") + \
               f" | {it['조항']}" + (f" ({it['부분']})" if it["부분"] else "") + "]"
        it["embed_text"] = head + "\n" + it["text"]
        it["글자수"] = len(it["text"])
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--only", default=None)
    ap.add_argument("--samples", type=int, default=20)
    ap.add_argument("--show", default=None, help="이 문자열이 조항·규정명에 들어간 청크를 전부 출력")
    a = ap.parse_args()

    allc, info = [], {}
    for idx, d in enumerate(DOCS, 1):
        key = f"{d['school']} {d['name']}" + (f" [{d['rng'][0]}-{d['rng'][1]}]" if d["kind"] == "reg" and d["rng"] else "")
        if a.only and a.only not in key and a.only not in d["file"]:
            continue
        pages = load_doc(d)
        items, st = chunk_reg(d, pages) if d["kind"] == "reg" else chunk_tbl(d, pages)
        items = finalize(items, d, idx)
        allc += items
        info[key + (f" ({d.get('ver','')}{d.get('year') or ''})" if d["kind"] == "reg" else "")] = (len(pages), len(items), st)
        print(f"· {key}: {len(pages)}쪽 → {len(items)}청크 {st if st else ''}", flush=True)

    if not a.no_write and not a.only:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT, "w", encoding="utf-8", newline="\n") as f:
            for c in allc:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        print(f"저장: {OUT} ({len(allc)}청크)")
    report(allc, a)


def report(allc, a):
    print("\n════ 통계 ════")
    print("전체", len(allc), "청크 / 기본 색인", sum(c["기본색인"] for c in allc), "/ 구판", sum(not c["기본색인"] for c in allc))
    t = collections.Counter((c["대학"], c["출처등급"], c["구분"]) for c in allc if c["기본색인"])
    print("기본 색인: 대학 x 등급 x 구분")
    for k, v in sorted(t.items()):
        print("  ", k, v)
    print("구판(충남):", collections.Counter((c["규정명"], c["판본연도"]) for c in allc if not c["기본색인"]))
    L = [c["글자수"] for c in allc if c["기본색인"]]
    qs = statistics.quantiles(L, n=20)
    print(f"기본 색인 글자수: 최소 {min(L)} · 중앙 {int(statistics.median(L))} · 평균 {int(statistics.mean(L))} · p95 {int(qs[-1])} · 최대 {max(L)}")
    print("  1200자 초과:", sum(x > LIMIT for x in L), "/ 50자 미만:", sum(x < 50 for x in L), "/ 분할된 청크:", sum(1 for c in allc if c["부분"]))
    ids = [c["id"] for c in allc]
    print("id 중복:", len(ids) - len(set(ids)), "/ 빈 본문:", sum(1 for c in allc if not c["text"].strip()))
    # 본문 조 번호 연속성
    print("\n본문 조 번호 점검 (규정 파일별, 삭제 포함)")
    by = collections.defaultdict(list)
    for c in allc:
        if c["구분"] in ("본문", "삭제"):
            by[(c["규정명"], c["판본연도"], c["파일"])].append(c)
    for k, cs in by.items():
        nums = set()
        for c in cs:
            for m in re.finditer(r"제(\d+)조(?:의(\d+))?", c["조항"]):
                nums.add(int(m.group(1)))
            if "~" in c["조항"]:
                m = re.findall(r"제(\d+)조", c["조항"])
                if len(m) >= 2:
                    nums.update(range(int(m[0]), int(m[-1]) + 1))
        mx = max(nums) if nums else 0
        miss = [i for i in range(1, mx + 1) if i not in nums]
        print(f"  {k[0]} ({k[1]}): 조 청크 {len(cs)}개, 최대 제{mx}조, 번호 빠짐 {miss[:10]}")
    if a.show:
        print("\n════ --show ════")
        for c in allc:
            if a.show in c["조항"] or a.show in c["규정명"]:
                print(json.dumps({k: v for k, v in c.items() if k not in ("embed_text",)}, ensure_ascii=False)[:900])
    # 샘플
    rnd = random.Random(SEED)
    pool = [c for c in allc if c["기본색인"]]
    pick = []

    def take(cond, n, label):
        cand = [c for c in pool if cond(c) and c not in pick]
        rnd.shuffle(cand)
        for c in cand[:n]:
            pick.append(c)
            c["_s"] = label

    take(lambda c: c["구분"] == "별표", 4, "표(별표·별지)")
    take(lambda c: c["구분"] == "부칙", 3, "부칙")
    take(lambda c: c["출처등급"] == "B" and c["대학"] == "한남", 1, "B 편람(한남 이수원칙·경상대학)")
    take(lambda c: c["출처등급"] == "B" and c["대학"] == "배재", 1, "B 편람(배재)")
    take(lambda c: c["출처등급"] == "B" and c["대학"] == "충남", 2, "B 판별 교육과정(충남)")
    take(lambda c: c["출처등급"] == "B" and c["대학"] == "한밭", 1, "B 판별 교육과정(한밭)")
    take(lambda c: c["구분"] == "삭제", 1, "삭제 묶음")
    take(lambda c: c["규정명"] == "국립한밭대학교 학칙" and c["구분"] == "본문", 1, "한밭 학칙(펼침면 분할)")
    take(lambda c: c["부분"] != "" and c["구분"] == "본문", 2, "항 분할")
    take(lambda c: c["구분"] == "본문" and c["부분"] == "", max(0, a.samples - len(pick)), "본문")
    print(f"\n════ 샘플 {len(pick)}건 (시드 {SEED}) ════")
    for c in pick:
        pr = f", 인쇄 {c['쪽_인쇄'][0]}" + (f"~{c['쪽_인쇄'][1]}" if c["쪽_인쇄"][1] != c["쪽_인쇄"][0] else "") if c["쪽_인쇄"] else ""
        yr = f" | 학번 {c['학번_시작']}~{c['학번_끝']}" if c["학번_시작"] else ""
        print(f"\n[{c['_s']}] {c['id']} | {c['대학']} | {c['규정명']} ({c['판본'] or c['출처등급']}) | {c['구분']} | {c['조항'][:50]} {c['부분']} | PDF {c['쪽_PDF'][0]}{pr}{yr} | {c['글자수']}자")
        print("   " + c["text"][:230].replace("\n", " ⏎ "))


if __name__ == "__main__":
    main()
