"""1회용 생성 스크립트(E26): 한남 전 학과 졸업학점·교양·전공 예외·공학인증 안내 묶음 행 HN-042~를 data/criteria.csv 끝에 붙인다.
이미 행이 있으면 중단한다(assert). 실패하면 sys.exit(1). --dry 이면 파일을 쓰지 않는다.
출처 PDF: data/raw/hannam/학칙_2-1-2_20260512.pdf 제41조 ①(9쪽)·별표1 학과(부)편제(43~46쪽),
          data/raw/hannam/학칙시행세칙_2-1-3.pdf 제6조 ①(4쪽)·제20조의2 ①(12쪽).
공학인증 프로그램 목록·학과 공지: data/raw/hannam/공학인증_프로그램목록_20261110.png, 정보통신공학과_공학인증공지_20260930.png.
값은 쪽 이미지 대조 후 확정(CLAUDE.md 7단계 E26). 2022·2023학번 학과 이름은 별표1이 2024~ 입학정원 열뿐이라 비고(변경사항)로 추정한 잠정값이다.
실행: .venv/Scripts/python.exe -X utf8 scripts/build_criteria_hn.py [--dry]"""
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
assert not any(r["대학"] == "한남" and r["행ID"] >= "HN-042" for r in rows), "이미 E26 행이 있음"
DATE = "2026-11-10"
F_RULE = "학칙_2-1-2_20260512.pdf"
F_BY = "학칙시행세칙_2-1-3.pdf"

# ---------- 학과 목록(별표1 2024~2026 입학정원 열의 이름 기준, 2027 신설·개편·자유전공학부·정원외 제외) ----------
HUM24 = ["국어국문·창작학과", "영어영문학과", "응용영어콘텐츠학과", "일어일문학과", "프랑스어문학과", "문헌정보학과", "사학과", "기독교학과",
         "경영학과", "회계학과", "무역물류학과", "경제학과", "중국경제통상학과", "호텔항공경영학과",
         "행정학과", "경찰학과", "정치·언론학과", "사회복지학과", "아동복지학과", "상담심리학과", "사회적경제기업학과", "법학부",
         "린튼글로벌스쿨", "빅데이터응용학과"]
SCI = ["수학과", "생명시스템과학과", "식품영양학과", "화학과"]
ENG24 = ["정보통신공학과", "전기전자공학과", "멀티미디어공학과", "건축공학과", "건설환경공학과", "기계공학과", "화학공학과", "신소재공학과",
         "컴퓨터공학과", "산업경영공학과", "AI융합학과", "바이오제약공학과"]
ART = ["융합디자인학과", "회화과", "패션디자인학과", "미디어영상학과", "스포츠과학과"]
EDU_OK = ["국어교육과", "영어교육과", "교육학과", "역사교육과"]
EDU_TENT = ["미술교육과", "수학교육과"]
COS = ["코스메틱사이언스학과"]
JA23 = {"일어일문학과": "외국어문학부 일어일문학전공", "프랑스어문학과": "외국어문학부 프랑스어문학전공"}
ENG_OLD = {"건축공학과": "토목·건축공학부 건축공학전공", "건설환경공학과": "토목·건축공학부 토목환경공학전공"}


def conv(lst, mp):
    return [mp.get(x, x) for x in lst]


def both(lst, mp):
    """이름이 바뀐 학과는 옛 이름과 지금 이름(2026 기준)을 둘 다 넣는다(E26 수정: 옛 학번이 지금 이름을 골라도 T0이 되지 않게). mp: 지금 이름 -> 옛 이름"""
    out = []
    for x in lst:
        out.append(x)
        if x in mp:
            out.append(mp[x])
    return out


HUM23 = both(HUM24, JA23)
HUM22 = both([x for x in HUM23 if x != "응용영어콘텐츠학과"], {"무역물류학과": "무역학과"})
ENG_OLDL = both(ENG24, ENG_OLD)
PERIODS = {  # 학번 -> (시작, 끝, 인문사회, 이학+공학+예체능, 상태)
    "2022": (2022, 2022, HUM22, SCI + ENG_OLDL + ART, "잠정"),
    "2023": (2023, 2023, HUM23, SCI + ENG_OLDL + ART, "잠정"),
    "2024": (2024, None, HUM24, SCI + ENG24 + ART, "확정"),
}
STABLE = ["건축학(5년제)", "간호학과", "사범대학", "인문사회계열", "이학·공학·예능·체능·간호계열"]
BASE = "경영정보학과"
NOTE_NAMES = ("별표1(PDF 43~45쪽)의 입학정원 열은 2024~2027뿐이라 2022·2023학번 학과 이름은 비고(변경사항)로 추정한 잠정값: "
              "2023 응용영어콘텐츠학과 신설(영어영문학과에서 분리), 2023 무역물류학과 명칭 변경((구)무역학과), 2022 호텔항공경영학과 명칭 변경((구)컨벤션호텔경영학과), "
              "2024 일어일문학·프랑스어문학 전공→학과 전환, 2024 건축공학·토목환경공학 전공→학과 전환(토목·건축공학부), 2022 경제학·중국경제통상 전공→학과(학부 폐지)")
NOTE_RENAME = "이름이 바뀐 학과는 옛 이름과 지금 이름(2026 기준)을 둘 다 대상에 넣었다(옛 학번이 지금 이름을 골라도 같은 기준). "
NOTE_BUNDLE = NOTE_RENAME + "여러 학과가 같은 값을 쓰는 묶음 행이라 학과 하나하나로 읽는다(규칙 16). 학부 아래 세부 전공(법학부 법학전공·법무법학전공, 린튼글로벌스쿨 전공 등)은 학부 이름으로 적는다. "
NOTE_EXCL = "경영정보학과(HN-005·006)·간호학과(HN-007)·건축학(5년제)(HN-004)는 기존 졸업학점 행이 따로 있어 묶음에 넣지 않았다. 2027 신설·개편 학과·자유전공학부·정원외 학과는 제외"

new = []


def add(year0, year1, targets, item, value=None, vmax=None, op="이상", utype="", cond="", orig="", unit="학점", fil=F_RULE, clause="", page="", grade="A",
        basis="기준", status="확정", note="", unit_kind="학과"):
    new.append(dict(y0=year0, y1=year1, targets=targets, item=item, value=value, vmax=vmax, op=op, utype=utype, cond=cond, orig=orig, unit=unit, fil=fil,
                    clause=clause, page=page, grade=grade, basis=basis, status=status, note=note, unit_kind=unit_kind))


CL41 = "학칙 제41조 ① 졸업학점 기준표 (개정 2024.02.26., \"2019학년도 이후\" 행); 학칙 별표1 학과(부)편제"
PG41 = "9(9); 43(43); 44(44); 45(45)"

for key, (y0, y1, hum, sci_eng_art, st) in PERIODS.items():
    nm = NOTE_NAMES + "." if st == "잠정" else "학과 이름은 별표1 2024~2026 입학정원 열 기준."
    base = NOTE_BUNDLE + NOTE_EXCL + ". " + nm
    add(y0, y1, hum, "졸업학점", "120", clause=CL41, page=PG41, status=st, orig="인문사회", note="인문사회계열 120(별표1 문과·경상·사회과학·린튼글로벌스쿨·빅데이터응용). " + base)
    add(y0, y1, sci_eng_art, "졸업학점", "128", clause=CL41, page=PG41, status=st, orig="이학·공학·예능·체능·간호", note="이학·공학·예체능 계열 128. " + base)
    if key == "2024":
        add(y0, y1, EDU_OK, "졸업학점", "127", clause=CL41 + "; 사범대학 행", page=PG41, orig="사범", note="사범대학 127. " + base)
        add(y0, y1, EDU_TENT, "졸업학점", "127", clause=CL41 + "; 사범대학 행", page=PG41, status="잠정", orig="사범",
            note="별표1은 미술교육과=예능·수학교육과=이학 계열로 적었으나 졸업학점은 사범대학 127을 적용(학칙 제41조 사범 행). 계열 칸과 달라 잠정. " + base)
        add(y0, y1, COS, "졸업학점", "128", clause=CL41, page=PG41, status="잠정", orig="이학·공학·예능·체능·간호",
            note="별표1에서 코스메틱사이언스학과의 계열 칸이 비어 있어 128로 잠정(정원외 외국인 전담학과). " + base)
    else:
        add(y0, y1, EDU_OK + EDU_TENT, "졸업학점", "127", clause=CL41 + "; 사범대학 행", page=PG41, status="잠정", orig="사범",
            note="사범대학 127(미술교육·수학교육은 별표1 계열 칸과 달라 잠정). " + base)

# ---- 교양 (시행세칙 제6조 ①) ----
CL6 = "학칙 시행세칙 제6조 ① 입학연도별 교양교육과정 편성표 (개정 2024.02.13.)"
ALL24 = HUM24 + SCI + ENG24 + ART + EDU_OK + EDU_TENT + COS
ALL23 = HUM23 + SCI + ENG_OLDL + ART + EDU_OK + EDU_TENT + COS
ALL22 = HUM22 + SCI + ENG_OLDL + ART + EDU_OK + EDU_TENT + COS
add(2022, 2022, [BASE] + STABLE, "교양", "29", utype="심화단수", fil=F_BY, clause=CL6, page="4(4)", orig="교양필수",
    note="소양교육 6 + 기초교육 15 + 균형교양 8. 2019~2022 기본 이수 방식(심화단수)용. 경영정보학과는 HN-010(단수)과 값이 같다")
add(2022, 2022, ALL22, "교양", "29", utype="심화단수", fil=F_BY, clause=CL6, page="4(4)", status="잠정", orig="교양필수",
    note="소양교육 6 + 기초교육 15 + 균형교양 8. " + NOTE_BUNDLE + NOTE_NAMES)
add(2023, 2023, STABLE, "교양", "30", utype="단수", fil=F_BY, clause=CL6, page="4(4)", orig="교양필수",
    note="기초교육 9 + 통합적소양교육 4 + 균형교양 17. 계열교양 0~15는 별도(참고 행)")
add(2023, 2023, ALL23, "교양", "30", utype="단수", fil=F_BY, clause=CL6, page="4(4)", status="잠정", orig="교양필수",
    note="기초교육 9 + 통합적소양교육 4 + 균형교양 17. " + NOTE_BUNDLE + NOTE_NAMES)
add(2024, None, ALL24 + STABLE, "교양", "30", utype="단수", fil=F_BY, clause=CL6, page="4(4)", orig="교양필수",
    note="기초교육 9 + 통합적소양교육 4 + 균형교양 17. " + NOTE_BUNDLE + "경영정보학과는 HN-009가 따로 있다")
add(2023, None, ["전체"], "계열교양", "0", "15", op="범위", fil=F_BY, clause=CL6, page="4(4)", basis="참고", status="잠정", unit_kind="대학", orig="계열교양",
    note="2023학번~ 교양 30학점 외에 계열교양 0~15학점이 있다고 정리했으나 졸업학점·영역 계산에는 넣지 않는 참고 행(학과별 0~15, 학과 확인)")

# ---- 전공 예외(시행세칙 제20조의2 ① 1·2호) ----
CL20 = "학칙 시행세칙 제20조의2 ① "
add(2019, 2022, ["건축학(5년제)"], "전공", "108", utype="심화단수", fil=F_BY, clause=CL20 + "1호 (개정 2024.02.13.)", page="12(12)", note="건축학(5년제) 전공 108 이상. 2019~2022 기본 이수 방식(심화단수)")
add(2023, None, ["건축학(5년제)"], "전공", "108", utype="단수", fil=F_BY, clause=CL20 + "1호 (개정 2024.02.13.)", page="12(12)", note="건축학(5년제) 전공 108 이상(융합교육과정 규정 없이 단일 기준). 2023학번~는 대학 공통 단수 전공 불가(HN-014)를 이 행이 덮어쓴다(규칙 8)")
add(2019, 2022, ["간호학과"], "전공", "89", utype="심화단수", fil=F_BY, clause=CL20 + "2호 가목 (개정 2024.02.13., 2024.09.10., 2025.05.27.)", page="12(12)", note="2022학년도 이전 입학생·2024년 이전 편입생 89학점 이상")
add(2023, None, ["간호학과"], "전공", "87", utype="단수", fil=F_BY, clause=CL20 + "2호 나목 (개정 2024.02.13., 2024.09.10., 2025.05.27.)", page="12(12)", note="2023학년도 이후 입학생·2025년 이후 편입생 87학점 이상. 대학 공통 단수 전공 불가(HN-014)를 이 행이 덮어쓴다(규칙 8)")

# ---- 공학교육인증 안내 (시행세칙 제20조의2 ① 3호 + 학과 공지) ----
ENGCERT24 = ["전기전자공학과", "정보통신공학과", "건축공학과", "기계공학과", "건설환경공학과"]
ENGCERT_OLD = both(ENGCERT24, ENG_OLD)
PROG = ("인증 프로그램 이름(이미지 공학인증_프로그램목록_20261110): 전자공학심화·정보통신공학심화·건축공학심화·기계공학심화·건설시스템공학심화 프로그램. "
        "별표1 학과 매칭: 정보통신·기계는 이름이 같고, 건축공학은 건축공학과(2024~, 2022·2023은 토목·건축공학부 건축공학전공), "
        "전자공학심화→전기전자공학과(잠정 해석: 별표1에 전자공학과 없음), 건설시스템공학심화→건설환경공학과(잠정 해석: 이름이 다르고 2022·2023은 토목·건축공학부 토목환경공학전공). 매칭은 학과 확인")
TXT22 = "공학교육인증 심화 프로그램은 2027년 2월 졸업생까지만 이수 가능해요(학과 공지). 해당하면 학과에 확인하세요."
TXT23 = ("이 학과는 공학교육인증 프로그램을 운영해요. 시행세칙에는 공학교육인증 운영학과 전공 60학점(MSC 포함)이 남아 있지만 학과 공지는 2023학번 이후 해당 없다고 해요. "
         "그래서 일반 학과 기준으로 안내하니 해당하면 학과에 확인하세요.")
NOTE_ENG22 = "2022학번은 공학인증 운영학과·일반 학과 모두 전공 66이라 학점 값은 동일. 시행세칙 제20조의2 ① 3호 · 공지 근거: 정보통신공학과 공지(2026-09-30, 학과 홈페이지 C등급), 나머지 4개 학과 공지는 미확인. "
add(2022, 2022, ENGCERT_OLD, "공학인증_안내", cond=TXT22, utype="", fil=F_BY + "; 정보통신공학과_공학인증공지_20260930.png", clause=CL20 + "3호 (개정 2024.02.13.); 학과 공지", page="12(12)", grade="C", status="잠정", orig="공학교육인증제 운영학과", unit="", op="",
    note=NOTE_ENG22 + PROG + ". " + NOTE_NAMES)
add(2023, 2023, ENGCERT_OLD, "공학인증_안내", cond=TXT23, utype="", fil=F_BY + "; 정보통신공학과_공학인증공지_20260930.png", clause=CL20 + "3호 (개정 2024.02.13.); 학과 공지", page="12(12)", grade="C", status="잠정", orig="공학교육인증제 운영학과", unit="", op="",
    note="세칙에는 2023~ 60학점이 남아 있으나 공지는 '2023학번 이후 해당 없음'이라 일반 학과 기준(융합교육과정)을 적용하고 공학인증 적용 여부는 학과 확인(두 출처 모두 기재). " + PROG + ". " + NOTE_NAMES)
add(2024, None, ENGCERT24, "공학인증_안내", cond=TXT23, utype="", fil=F_BY + "; 정보통신공학과_공학인증공지_20260930.png", clause=CL20 + "3호 (개정 2024.02.13.); 학과 공지", page="12(12)", grade="C", status="잠정", orig="공학교육인증제 운영학과", unit="", op="",
    note="세칙에는 2023~ 60학점이 남아 있으나 공지는 '2023학번 이후 해당 없음'이라 일반 학과 기준(융합교육과정)을 적용하고 공학인증 적용 여부는 학과 확인(두 출처 모두 기재). " + PROG)

# ---------- 행 만들기 ----------
nid = 42
out = []
for o in new:
    r = {k: "" for k in fields}
    r["행ID"] = f"HN-{nid:03d}"
    nid += 1
    r["대학"] = "한남"
    r["입학년도_시작"] = str(o["y0"])
    r["입학년도_끝"] = "" if o["y1"] is None else str(o["y1"])
    r["대상단위"] = o["unit_kind"]
    r["대상"] = "전체" if o["targets"] == ["전체"] else ",".join(o["targets"])
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
    r["출처등급"] = o["grade"]
    r["기준값여부"] = o["basis"]
    r["상태"] = o["status"]
    r["확인일"] = DATE
    r["비고"] = o["note"]
    out.append(r)


def targets(r):
    return [t.strip() for t in r["대상"].split(",") if t.strip()]


seen = defaultdict(list)
for r in rows + out:
    if r["대학"] != "한남":
        continue
    lo = int(r["입학년도_시작"] or 0)
    hi = int(r["입학년도_끝"] or 9999)
    for t in targets(r):
        for y in range(2022, 2027):
            if lo <= y <= hi:
                seen[(t, y, r["이수유형"], r["항목"], r["구분"], r["조건"] if r["항목"] not in ("공학인증_안내",) else "")].append(r["행ID"])
bad = {k: v for k, v in seen.items() if len(v) > 1 and any(i >= "HN-042" for i in v) and k[3] != "졸업학점" or
       (len(v) > 1 and any(i >= "HN-042" for i in v) and k[3] == "졸업학점")}
if bad:
    for k, v in list(bad.items())[:20]:
        print("중복", k, v)
    sys.exit(1)
print("새 행", len(out), out[0]["행ID"], out[-1]["행ID"], "학과 이름 수", len({t for r in out for t in targets(r)}))
if DRY:
    sys.exit(0)
with open(P, "a", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields, lineterminator=EOL)
    for r in out:
        w.writerow(r)
print("appended")
