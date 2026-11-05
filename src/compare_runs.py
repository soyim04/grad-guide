"""같은 입력으로 여러 번 돌린 결과를 비교한다 (실험 0: 기준선 잡음 측정). API 호출 없음.

  - 답변 파일끼리: 검색된 top-5가 같은지, 답변 잡음(같은 입력인데 판정이 바뀌는 문항)
  - 판정만 다시 한 파일: 판정관 잡음(같은 답변인데 판정이 바뀌는 문항)
  - 판정관 판정은 사전 채점이라, 사람 최종 판정이 있는 기준선과도 같이 본다

사용법
    .venv\\Scripts\\python.exe src\\compare_runs.py
출력: 표준 출력 + eval/results/<날짜>_e0_noise.md
"""

import csv
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "eval" / "results"
STEM = f"{date.today().isoformat()}_dev_base-rag_gpt-6-luna"

# (이름, 답변 파일, 채점 파일). 채점 파일의 사람 판정(최종판정)은 기준선에만 있다.
RUNS = [
    ("기준선 답변·판정관1", f"{STEM}.csv", f"{STEM}_grade-v2.csv"),
    ("기준선 답변·판정관2", f"{STEM}.csv", f"{STEM}_grade-v2_e0-judge2.csv"),
    ("답변 재실행 run2", f"{STEM}_e0-run2.csv", f"{STEM}_e0-run2_grade-v2.csv"),
    ("답변 재실행 run3", f"{STEM}_e0-run3.csv", f"{STEM}_e0-run3_grade-v2.csv"),
]


def load(name):
    with (RES / name).open(encoding="utf-8-sig", newline="") as f:
        return {r["id"]: r for r in csv.DictReader(f)}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    runs = [(n, load(a), load(g)) for n, a, g in RUNS if (RES / a).exists() and (RES / g).exists()]
    human = {i: r["최종판정"] for i, r in load(RUNS[0][2]).items()}
    ids = list(human)
    lines = ["# 실험 0 — 기준선 잡음 측정", ""]

    lines += ["## 1. 판정 분포 (판정관 판정, 사전 채점)", "| 실행 | 정답 | 부분 | 오답 | 확인불가 | 정답+부분 |", "|---|---|---|---|---|---|"]
    for n, _, g in runs:
        c = Counter(r["판정관_판정"] for r in g.values())
        lines.append(f"| {n} | {c['정답']} | {c['부분']} | {c['오답']} | {c['확인불가']} | {c['정답'] + c['부분']} |")
    c = Counter(human.values())
    lines.append(f"| (참고) 기준선 사람 최종 | {c['정답']} | {c['부분']} | {c['오답']} | {c['확인불가']} | {c['정답'] + c['부분']} |")

    base_ans = runs[0][1]
    lines += ["", "## 2. 검색 결과 (top-5) 재현", ""]
    for n, a, _ in runs[1:]:
        same = sum(set(a[i]["검색청크"].split(";")) == set(base_ans[i]["검색청크"].split(";")) for i in ids)
        lines.append(f"- {n}: 기준선과 top-5 집합이 같은 문항 {same}/{len(ids)}")

    def flips(sel):
        """sel: 비교할 실행 이름들. 판정관 판정이 하나라도 다른 문항."""
        use = [r for r in runs if r[0] in sel]
        out = []
        for i in ids:
            v = [g[i]["판정관_판정"] for _, _, g in use]
            if len(set(v)) > 1:
                out.append((i, v))
        return use, out

    lines += ["", "## 3. 잡음 (같은 입력인데 판정관 판정이 바뀐 문항)"]
    rows = [
        ("판정관 잡음: 같은 답변을 두 번 판정", ["기준선 답변·판정관1", "기준선 답변·판정관2"]),
        ("답변 잡음 포함: 기준선·run2·run3 (각각 새 답변 + 새 판정)", ["기준선 답변·판정관1", "답변 재실행 run2", "답변 재실행 run3"]),
    ]
    for title, sel in rows:
        use, out = flips(sel)
        if len(use) < len(sel):
            continue
        lines += ["", f"### {title}", f"- 판정이 바뀐 문항 {len(out)}/{len(ids)}"]
        for i, v in out:
            lines.append(f"  - {i} (사람 {human[i]}): " + " / ".join(v))
        k = [sum(g[i]["판정관_판정"] == "정답" for i in ids) for _, _, g in use]
        lines.append(f"- 정답 수: {k} (최대-최소 {max(k) - min(k)}), 정답+부분: "
                     f"{[sum(g[i]['판정관_판정'] in ('정답', '부분') for i in ids) for _, _, g in use]}")

    # 답변 텍스트 자체가 바뀌었는지
    lines += ["", "## 4. 답변 텍스트가 기준선과 다른 문항"]
    for n, a, _ in runs[2:]:
        diff = [i for i in ids if a[i]["답변"].strip() != base_ans[i]["답변"].strip()]
        lines.append(f"- {n}: {len(diff)}/{len(ids)}")
    text = "\n".join(lines) + "\n"
    out = RES / f"{date.today().isoformat()}_e0_noise.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"저장: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
