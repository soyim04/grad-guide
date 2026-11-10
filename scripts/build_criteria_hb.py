"""1회용 생성 스크립트(E25): 한밭 전 학과 전공·대학특화·교양 묶음 행과 편입_이수요건 행 HB-025~를 data/criteria.csv 끝에 붙인다.
이미 행이 있으면 중단한다(assert). 실패하면 sys.exit(1). --dry 이면 파일을 쓰지 않는다.
출처 PDF: data/raw/hanbat/학칙_20261008개정.pdf 별표1(인쇄 50쪽, PDF 25쪽)·별표1의2(인쇄 51~52쪽, PDF 26쪽 2024~2027 입학정원),
          data/raw/hanbat/학사운영규정_20260522개정.pdf 제10조 ②·제12조 ②~④ 표(PDF 3~4쪽)·부칙(PDF 21·24쪽).
값은 쪽 이미지 대조 후 확정(CLAUDE.md 7단계 E25). 학과→계열은 규정에 명시 표가 없어 단과대학 기준 잠정, 2022·2023학번 학과 명단은 2024학번 명단을 잠정 사용.
실행: .venv/Scripts/python.exe -X utf8 scripts/build_criteria_hb.py [--dry]"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "data" / "criteria.csv"
DRY = "--dry" in sys.argv
raw = open(P, encoding="utf-8-sig", newline="").read()
EOL = "\r\n" if raw.count("\r\n") >= raw.count("\n") / 2 else "\n"
rows = list(csv.DictReader(open(P, encoding="utf-8-sig", newline="")))
fields = list(rows[0])
assert not any(r["대학"] == "한밭" and r["행ID"] >= "HB-025" for r in rows), "이미 E25 행이 있음"
DATE = "2026-11-10"
F_REG = "학사운영규정_20260522개정.pdf"
F_CH = "학칙_20261008개정.pdf"

# ---------- 학과 목록(별표1·1의2, 입학정원이 있는 학과, 2024~2026 열) ----------
ENG_BASE = ["기계공학과", "산업경영공학과", "신소재공학과", "창의융합학과", "화학생명공학과", "모바일융합공학과", "반도체시스템공학과", "인공지능소프트웨어학과",
            "전기공학과", "전자공학과", "정보통신공학과", "지능미디어공학과", "컴퓨터공학과", "건설환경공학과", "건축공학과", "도시공학과"]
FAC = ["설비공학과", "건축설비시스템공학과"]  # 설비공학과(2024~2025 입학정원) → 건축설비시스템공학과(2026~): 이름 변경으로 해석(잠정)
ENG_PRE = ENG_BASE + ["설비공학과", "건축설비시스템공학과"]  # 2022·2023: 2024 명단 + 이름 변경 학과는 옛·지금 이름 둘 다
ENG_2425 = ENG_BASE + ["설비공학과", "건축설비시스템공학과"]
ENG_26 = ENG_BASE + ["건축설비시스템공학과", "우주국방첨단융합학과", "빅데이터헬스케어융합학과"]
DES = ["산업디자인학과", "시각·영상디자인학과"]
HUM = ["공공행정학과", "영어영문학과", "일본어과", "중국어과"]
BIZ = ["경제학과", "회계세무학과"]  # 융합경영학과는 기존 행(HB-005~010)
ARC = "건축학과(5년제)"

NOTE_MAP = ("학과→계열은 규정에 명시 표가 없어 단과대학 기준으로 묶은 잠정 값(공학계=공과대학·정보기술대학·건설환경디자인대학 공학 학과, 인문계=인문사회대학, 경상계=경상대학, "
            "디자인계=산업디자인학과·시각·영상디자인학과: 별표1의2 주석 \"예체능계열(산업디자인학과, 시각·영상디자인학과)\"). ")
NOTE_EXCL = ("제외: 2025~ 학부 단위 입학(자율전공학부·공학건설학부·정보기술AI융합학부·인문사회경상학부), 성인전담학과(★), 국제학부(정원외, HB-003·004), 2027 AI융합대학 개편분, 학과 없는 학부. "
             "학번별로 그 해 입학정원이 있는 학과만 넣었다(2026학번: 건축설비시스템·우주국방첨단융합·빅데이터헬스케어융합, 2024~2025: 설비공학과). ")
NOTE_PRE = "2022·2023학번 학과 명단은 별표1의2가 2024학년도부터라 2024학번 명단을 잠정 사용(설비공학과·건축설비시스템공학과는 이름 변경으로 해석해 둘 다). "
NOTE_WEB = "융합경영학과는 기존 행(HB-005~010)이 있고 별표1의2에 2024 51·2025 50·2026 50·2027 53으로 있어 개편 없음(성인전담 창업경영학과가 융합경영학과로 합쳐짐, 부칙 2024.4.18.). 2026 졸업요건 웹페이지에서 빠진 것은 웹 쪽 누락. "
CL12 = "학사운영규정 제12조 ④ 표"
CLT = "; 부칙(규정 제1079호, 2022.1.6.) 제12조 ④ 개정규정 2019학년도 신입생부터"
CLS = "; 부칙(규정 제1178호, 2026.5.22.) 제3조: 대학특화 최저 이수학점은 2023학년도 신입생부터"
PG_MAJOR = "4(4); 21(21); 25(25); 26(26)"

new = []


def add(y0, y1, targets, item, value=None, vmax=None, op="이상", unit="학점", cond="", orig="", clause="", page="", status="잠정", note="", utype="단수", fil=F_REG, unit_kind="학과"):
    new.append(dict(y0=y0, y1=y1, targets=targets, item=item, value=value, vmax=vmax, op=op, unit=unit, cond=cond, orig=orig, clause=clause, page=page,
                    status=status, note=note, utype=utype, fil=fil, unit_kind=unit_kind))


def bundle(label, periods, base_name, major_cl, ts):
    """periods: [(y0, y1, 학과목록, 잠정사유 note)]. ts: 대학특화 학점"""
    for y0, y1, lst, pnote in periods:
        nm = NOTE_MAP + NOTE_EXCL + NOTE_WEB + pnote
        add(y0, y1, lst, "전공", "72", clause=CL12 + CLT, page=PG_MAJOR, cond="기본전공+심화전공 합", orig="전공과정 최저 이수학점", note=f"{label}. 전공 72 = 기본+심화(다만 건축학과 106·성인전담 81·국제학부 66은 별도). " + nm, fil=F_REG + "; " + F_CH)
        add(y0, y1, lst, "기본전공", "36", "51", op="범위", clause=CL12 + CLT, page=PG_MAJOR, orig="기본전공", note=f"{label}. " + nm, fil=F_REG + "; " + F_CH)
        add(y0, y1, lst, "심화전공", "21", "36", op="범위", clause=CL12 + CLT, page=PG_MAJOR, orig="심화전공", note=f"{label}. " + nm, fil=F_REG + "; " + F_CH)
        add(y0, y1, lst, "교양", "25", unit="%", cond="졸업필요학점 대비", clause="학사운영규정 제12조 ② (개정 2017.5.30.)", page="3(3)", orig="교양과정",
            note=f"{label}. 값 25는 졸업학점 대비 비율(130이면 32.5학점). 영역별 최소 학점은 규정에 없음. " + nm)
        t0 = max(y0, 2023)
        if y1 is None or y1 >= 2023:
            add(t0, y1, lst, "대학특화", str(ts), clause=CL12 + CLS, page="4(4); 24(24)", orig="대학특화과정", note=f"{label}. 2022학번 이하는 대학특화 값이 개정 전이라 행을 만들지 않았다(융합경영학과만 웹페이지 기준 HB-007). " + nm)


def three(label, lst_pre, lst_2425, lst_26, ts):
    bundle(label, [(2022, 2023, lst_pre, NOTE_PRE), (2024, 2025, lst_2425, ""), (2026, None, lst_26, "")], None, None, ts)


three("공학계", ENG_PRE, ENG_2425, ENG_26, 11)
for lbl, lst, ts in (("디자인계", DES, 8), ("인문계", HUM, 4), ("경상계", BIZ, 5)):
    bundle(lbl, [(2022, 2023, lst, NOTE_PRE), (2024, None, lst, "")], None, None, ts)

# ---- 건축학과(5년제): 제12조 ④ 표의 건축학과 행(대학특화 11·기본 65·심화 41), 교양 33(제12조 ③ 1호, 2026학번~) ----
NA = "건축학과(5년제)는 계열이 아니라 표의 별도 행이다. "
add(2019, None, [ARC], "전공", "106", cond="기본전공+심화전공 합", clause=CL12 + " 건축학과; 제12조 ④ 본문(건축학과는 106학점)" + CLT, page=PG_MAJOR, orig="전공과정 최저 이수학점",
    note=NA + "기본 65 + 심화 41 = 106. 적용 시작 학번을 부칙에서 확인하지 못해 제12조 ④ 개정이 2019학번부터인 점에 맞춰 2019~로 둔 잠정 값", fil=F_REG + "; " + F_CH)
add(2019, None, [ARC], "기본전공", "65", clause=CL12 + " 건축학과" + CLT, page=PG_MAJOR, orig="기본전공", status="잠정", op="이상", note=NA + "적용 시작 학번 미확인(2019~ 잠정)", fil=F_REG + "; " + F_CH)
add(2019, None, [ARC], "심화전공", "41", clause=CL12 + " 건축학과" + CLT, page=PG_MAJOR, orig="심화전공", status="잠정", op="이상", note=NA + "적용 시작 학번 미확인(2019~ 잠정)", fil=F_REG + "; " + F_CH)
add(2023, None, [ARC], "대학특화", "11", clause=CL12 + " 건축학과" + CLS, page="4(4); 24(24)", orig="대학특화과정", status="확정", note=NA + "2023학번~(부칙 제3조)")
add(2019, 2025, [ARC], "교양", "25", unit="%", cond="졸업필요학점 대비", clause="학사운영규정 제12조 ② (개정 2017.5.30.)", page="3(3)", orig="교양과정", status="확정",
    note=NA + "2025학번 이하는 일반 규정(졸업학점 160의 25% = 40학점). 건축 33학점은 2026학번부터(부칙 제2조)")
add(2026, None, [ARC], "교양", "33", cond="", clause="학사운영규정 제12조 ③ 1호 (신설 2026.5.22.); 부칙(규정 제1178호, 2026.5.22.) 제2조", page="3(3); 24(24)", orig="교양과정", status="확정",
    note=NA + "2026학년도 건축학과 신입생부터 적용(부칙 제2조)")

# ---- 편입_이수요건(한밭 대학 전체, 학사편입은 규정에 따로 없음) ----
add(None, None, ["전체"], "편입_이수요건", cond="편입학생: 편입학한 학과의 심화전공을 이수해야 함", orig="편입 심화전공 이수", utype="", unit="", op="",
    clause="학사운영규정 제10조(편입학) ② (신설 2019.3.18.)", page="3(3)", status="확정", unit_kind="대학", note="편입학생 학번은 편입학 학년도에 정상적으로 진급한 학생과 같은 학년 학번(제10조 ①). 제11조는 2024.12.13. 삭제")
add(None, None, ["전체"], "편입_이수요건", cond="편입학생: 전공과정은 기본전공과 심화전공 중 학과에서 인정하는 교과목 학점을 합해 50학점 이상 이수해야 함", orig="편입 전공 50학점", utype="", unit="", op="",
    clause="학사운영규정 제12조 ④ 단서 (개정 2019.3.18., 2026.5.22.)", page="4(4)", status="확정", unit_kind="대학", note="대학특화과정 교과목은 학과별로 정함")
add(None, None, ["전체"], "편입_이수요건", cond="편입학생: 교양은 핵심교양과 일반교양 영역에서 10학점 이내로 이수할 수 있음", orig="편입 교양 10학점 이내", utype="", unit="", op="",
    clause="학사운영규정 제12조 ② 단서 (신설 2019.3.18.)", page="3(3)", status="확정", unit_kind="대학", note="성인전담학과 편입생은 영역 구분 없이 10학점 이내(제12조 ③ 3호, 제외 대상)")

# ---------- 행 만들기 ----------
nid = 25
out = []
for o in new:
    r = {k: "" for k in fields}
    r["행ID"] = f"HB-{nid:03d}"
    nid += 1
    r["대학"] = "한밭"
    r["입학년도_시작"] = "" if o["y0"] is None else str(o["y0"])
    r["입학년도_끝"] = "" if o["y1"] is None else str(o["y1"])
    r["대상단위"] = o["unit_kind"]
    r["대상"] = ",".join(o["targets"])
    r["이수유형"] = o["utype"]
    r["항목"] = o["item"]
    r["값"] = o["value"] or ""
    r["값_최대"] = o["vmax"] or ""
    r["비교"] = o["op"]
    r["단위"] = o["unit"]
    r["조건"] = o["cond"]
    r["항목원어"] = o["orig"]
    r["출처파일"] = o["fil"]
    r["출처조항"] = o["clause"]
    r["출처쪽"] = o["page"]
    r["출처등급"] = "A"
    r["기준값여부"] = "기준"
    r["상태"] = o["status"]
    r["확인일"] = DATE
    r["비고"] = o["note"]
    out.append(r)


def targets(r):
    return [t.strip() for t in r["대상"].split(",") if t.strip()]


seen = defaultdict(list)
for r in rows + out:
    if r["대학"] != "한밭" or r["항목"] == "편입_이수요건":
        continue
    lo = int(r["입학년도_시작"] or 0)
    hi = int(r["입학년도_끝"] or 9999)
    for t in targets(r):
        for y in range(2022, 2027):
            if lo <= y <= hi:
                seen[(t, y, r["이수유형"], r["항목"], r["구분"], r["조건"])].append(r["행ID"])
bad = {k: v for k, v in seen.items() if len(v) > 1 and any(i >= "HB-025" for i in v)}
if bad:
    for k, v in list(bad.items())[:20]:
        print("중복", k, v)
    sys.exit(1)
print("새 행", len(out), out[0]["행ID"], out[-1]["행ID"], "학과 이름 수", len({t for r in out for t in targets(r) if t != "전체"}))
if DRY:
    sys.exit(0)
with open(P, "a", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields, lineterminator=EOL)
    for r in out:
        w.writerow(r)
print("appended")
