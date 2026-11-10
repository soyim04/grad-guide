"""1회용 생성 스크립트(E27c): 목원 별표 4 2022·2023 학과 묶음에 졸업학점 행을 같은 묶음 단위로 붙인다(MW-347~). E27b(2024~2026)와 같은 방식.
이유: 학과 묶음 행에 졸업학점이 없어 MW-002의 '아래 예외 대상 제외'를 모델이 학과 예외로 읽었다(서비스 점검 #18).
값은 사용자가 원문 이미지(78~79·82~83쪽 합계 칸)로 대조: 2022 기본 132(건축학(5년)전공 165·정보통신공학과 140·사범 140), 2023 기본 126(건축학(5년)전공 160·사범 134). 예외값은 기존 행과 값만 대조.
이미 있으면 중단(assert), 실패하면 sys.exit(1). --dry 이면 쓰지 않는다. 2024~2026은 build_criteria_mw_grad.py(E27b).
실행: .venv/Scripts/python.exe -X utf8 scripts/build_criteria_mw_grad2.py [--dry]"""
import csv
import sys
from pathlib import Path
from collections import defaultdict

P = Path(__file__).resolve().parent.parent / "data" / "criteria.csv"
DRY = "--dry" in sys.argv
raw = open(P, encoding="utf-8-sig", newline="").read()
EOL = "\r\n" if raw.count("\r\n") >= raw.count("\n") / 2 else "\n"
rows = list(csv.DictReader(open(P, encoding="utf-8-sig", newline="")))
fields = list(rows[0])
assert not any(r["행ID"] == "MW-347" for r in rows), "이미 E27c 행이 있음"
BASE = {2022: 132, 2023: 126}
TEACH = ("사범대학", "국어교육과", "영어교육과", "음악교육과", "미술교육과", "유아교육과", "수학교육과")
EXPECT = {2022: {"건축학부 건축학(5년)전공": 165, "정보통신공학과": 140, **{t: 140 for t in TEACH}},
          2023: {"건축학부 건축학(5년)전공": 160, **{t: 134 for t in TEACH}}}  # 기존 행이 있어야 하며 값만 대조


def span(r):
    return int(r["입학년도_시작"] or 0), int(r["입학년도_끝"] or 9999)


def covered(dept, y):
    return [r for r in rows if r["대학"] == "목원" and r["항목"] == "졸업학점" and r["대상단위"] != "대학" and dept in r["대상"].split(",")
            and span(r)[0] <= y <= span(r)[1]]


new = []
nid = 347
for r in rows:
    if not (r["대학"] == "목원" and r["대상단위"] == "학과" and r["항목"] == "교양" and r["행ID"] >= "MW-069"):
        continue
    y = int(r["입학년도_시작"])
    if y not in (2022, 2023):
        continue
    ds = r["대상"].split(",")
    for d, v in EXPECT[y].items():  # 예외값 대조(기존 행)
        if d in ds:
            ex = covered(d, y)
            assert ex and all(int(e["값"]) == v for e in ex), f"{d} {y} 기존 졸업학점 행이 없거나 값이 다름: {[e['행ID'] + e['값'] for e in ex]}"
    gd = [d for d in ds if not covered(d, y)]
    if not gd:
        continue
    nr = {k: "" for k in fields}
    nr.update({"행ID": f"MW-{nid:03d}", "대학": "목원", "입학년도_시작": str(y), "입학년도_끝": "" if y == 2026 else str(y), "대상단위": "학과",
               "대상": ",".join(gd), "항목": "졸업학점", "값": str(BASE[y]), "비교": "이상", "단위": "학점", "항목원어": "합계",
               "출처파일": "학칙시행세칙_2-1-2.pdf", "출처조항": f"학칙 시행세칙 별표 4 ({y}학년도 입학자부터)", "출처쪽": r["출처쪽"],
               "출처등급": "A", "기준값여부": "기준", "상태": "확정", "확인일": "2026-11-10",
               "비고": "E27b: 같은 묶음(교양 행과 같은 대상)의 졸업학점. 표의 합계 칸 기본값(2022=132·2023=126, 사용자가 원문 쪽 이미지로 대조). 학과 묶음에 졸업학점이 없어 MW-002 '아래 예외 대상 제외'를 학과 예외로 읽는 오답이 나서 추가(서비스 점검 #18, E27b와 같은 방식으로 2022·2023 확장 E27c). 여러 학과가 같은 값을 쓰는 병합 칸이라 학과 하나하나로 읽는다(규칙 16)"})
    nid += 1
    new.append(nr)

# 중복·완전성 검사
allr = rows + new
seen = defaultdict(list)
for r in allr:
    if r["대학"] == "목원" and r["항목"] == "졸업학점" and r["대상단위"] != "대학":
        for t in r["대상"].split(","):
            for y in range(2022, 2027):
                if span(r)[0] <= y <= span(r)[1]:
                    seen[(t, y)].append(r["행ID"])
dup = {k: v for k, v in seen.items() if len(v) > 1 and any(i >= "MW-347" for i in v)}
assert not dup, dup
depts = {t for r in allr if r["대학"] == "목원" and r["대상단위"] == "학과" and r["항목"] == "교양" for t in r["대상"].split(",")}
lack = sorted((t, y) for r in allr if r["대학"] == "목원" and r["대상단위"] == "학과" and r["항목"] == "교양" for t in r["대상"].split(",")
              for y in (2022, 2023) if span(r)[0] <= y <= span(r)[1] and not seen.get((t, y)) and t != "사범대학")
print("새 행", len(new), new[0]["행ID"] if new else "-", new[-1]["행ID"] if new else "-")
print("2022·2023 졸업학점 행이 없는 (학과, 학번):", lack)
if lack:
    sys.exit(1)
if DRY:
    sys.exit(0)
with open(P, "a", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields, lineterminator=EOL)
    for r in new:
        w.writerow(r)
print("appended")
