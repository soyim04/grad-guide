"""실험 2: 질문에서 대학·학번을 규칙으로 뽑아 Chroma 메타데이터 필터(where)를 만든다. 비용 0, LLM 안 씀.

- 대학: 별칭 사전(배재/배재대/배재대학교 등). 0개면 필터 없음, 1개면 일치, 여러 개면 합집합($in)
- 학번: `YYYY학번`, `YY학번`(2000+YY). 0개면 필터 없음.
  구간이 없는 청크(학번_시작=0, 학번_끝=9999)는 항상 통과, 구간이 있는 청크는 질문 학번 중 하나라도 구간 안이면 통과
- 사전 확인: `python src/query_filter.py` → 개발용 51문항 추출 결과를 라벨과 대조해 eval/results/<날짜>_e2_extraction.md에 저장
"""

import csv
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALIAS = {
    "배재": ["배재대학교", "배재대", "배재"],
    "충남": ["충남대학교", "충남대", "충남"],
    "한남": ["한남대학교", "한남대", "한남"],
    "한밭": ["한밭대학교", "한밭대", "한밭"],
    "목원": ["목원대학교", "목원대", "목원"],
}
YEAR4 = re.compile(r"(?<!\d)(\d{4})\s*학번")
YEAR2 = re.compile(r"(?<!\d)(\d{2})\s*학번")


def extract_universities(q):
    return [u for u, aliases in ALIAS.items() if any(a in q for a in aliases)]


def extract_years(q):
    ys = {int(m.group(1)) for m in YEAR4.finditer(q)}
    ys |= {2000 + int(m.group(1)) for m in YEAR2.finditer(q)}
    return sorted(ys)


def build_where(universities, years):
    parts = []
    if len(universities) == 1:
        parts.append({"대학": universities[0]})
    elif universities:
        parts.append({"대학": {"$in": universities}})
    if years:
        no_range = {"$and": [{"학번_시작": {"$eq": 0}}, {"학번_끝": {"$eq": 9999}}]}
        inside = [{"$and": [{"학번_시작": {"$lte": y}}, {"학번_끝": {"$gte": y}}]} for y in years]
        parts.append({"$or": [no_range] + inside})
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else {"$and": parts}


def where_for(question):
    return build_where(extract_universities(question), extract_years(question))


def expected(row):
    """라벨 기준 기대값: 대학이 '공통'이면 없음, X03만 질문에 이름이 나온 세 학교"""
    if row["id"] == "X03":
        us = ["충남", "한남", "한밭"]
    else:
        us = [] if row["대학"] == "공통" else [row["대학"]]
    ys = sorted({int(x) for x in re.findall(r"\d{4}", row["학번"] or "")})
    return sorted(us), ys


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rows = list(csv.DictReader((ROOT / "eval" / "questions_dev.csv").open(encoding="utf-8-sig")))
    lines = ["# 실험 2 추출 정확도 사전 확인 (개발용 51문항)", "",
             "규칙은 개발용 질문을 본 뒤 만들었으므로 일반화 증거가 아니다. 공정한 확인은 홀드아웃(8단계).", "",
             "| ID | 추출 대학 | 라벨 대학 | 추출 학번 | 라벨 학번 | 일치 |", "|---|---|---|---|---|---|"]
    ok = 0
    for r in rows:
        us, ys = sorted(extract_universities(r["질문"])), extract_years(r["질문"])
        eu, ey = expected(r)
        match = us == eu and ys == ey
        ok += match
        lines.append(f"| {r['id']} | {','.join(us) or '-'} | {','.join(eu) or '-'} | {','.join(map(str, ys)) or '-'} | {','.join(map(str, ey)) or '-'} | {'O' if match else 'X'} |")
    lines += ["", f"일치 {ok}/{len(rows)}"]
    out = ROOT / "eval" / "results" / f"{date.today().isoformat()}_e2_extraction.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[-3:]))
    print(f"저장: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
