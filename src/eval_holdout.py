"""8단계 홀드아웃 측정 (평가 스크립트, 서비스 코드·데이터는 건드리지 않는다. 동결 태그 freeze-20261112 이후 추가).

  python src/eval_holdout.py check        # 측정 전 해시 대조 (하나라도 다르면 멈춤)
  python src/eval_holdout.py prep         # luna용 접두 질문 CSV(B) 생성: id, 질문 열만
  python src/eval_holdout.py run-a        # 홀드아웃 A 13문항: dev와 같은 run_rag 경로(질문 문장 기반), 서비스 설정과 같은 옵션
  python src/eval_holdout.py run-b        # 홀드아웃 B 12문항: 서비스 경로 engine.answer(q, univ, year, dept) — 사이드바 정보를 넣는다
  python src/eval_holdout.py luna A|B     # luna 웹검색 켬 1회 (blank_test.py --web --input ...), B는 접두 질문
  python src/eval_holdout.py judge <a|b|luna-a|luna-b>   # judge-v2 판정(답변 파일은 날짜 기준 최신)

규칙
- 측정 결과를 보고 고치지 않는다. 한 번만 돌린다(결과 파일이 있으면 덮어쓰지 않고 멈춘다).
- B 접두 규칙(luna): "{학교}대 {학번}학번 {학과} 학생인데, {질문}", 학과가 '목록에 없는 학과'이면 학과 부분을 뺀다. 질문만 보내고 answer·key는 보내지 않는다.
- A와 B는 재는 경로가 다르다: A는 질문 문장 기반 run_rag(dev와 같은 경로), B는 사이드바 기반 engine.answer(서비스 화면과 같은 경로).
- B 판정관 어댑터: key → 핵심항목, answer → 정답, 채점유형은 모두 '항목', 질문 앞에 사이드바 정보를 붙여 판정관이 학번·학과를 알게 한다.
"""
import argparse
import csv
import hashlib
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import run_rag as R  # noqa: E402

A_CSV = ROOT / "eval" / "questions_holdout.csv"
B_CSV = ROOT / "eval" / "holdout_b.csv"
B_LUNA_IN = ROOT / "eval" / "holdout_b_luna_input.csv"
RES = ROOT / "eval" / "results"
EXPECT = {
    "A": (A_CSV, "199ed6ff14e628df4b62a12a2f55120caf3d588d118d76c2fe97c09381dd1c77"),
    "B": (B_CSV, "84e77afe285969e8a7c05d35efc26085f2b7c6711d70fa18da61ab048372c553"),
}
CRITERIA_PREFIX = "18093fa45e1dcba2"
TODAY = date.today().isoformat()
NO_DEPT = "목록에 없는 학과"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check():
    bad = []
    for k, (p, want) in EXPECT.items():
        got = sha(p)
        print(f"홀드아웃 {k}: {'일치' if got == want else '불일치'} {got[:16]}")
        if got != want:
            bad.append(k)
    c = sha(ROOT / "data" / "criteria.csv")[:16]
    print(f"criteria.csv: {'일치' if c == CRITERIA_PREFIX else '불일치'} {c}")
    if c != CRITERIA_PREFIX:
        bad.append("criteria")
    if bad:
        sys.exit(f"해시 불일치 {bad} — 측정하지 않고 멈춥니다")


def read(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write(path, rows, fields=None):
    fields = fields or list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def no_overwrite(path):
    if Path(path).exists():
        sys.exit(f"이미 있는 결과 파일이라 덮어쓰지 않고 멈춥니다: {Path(path).name}")


def prefix(r):
    d = "" if r["dept"].startswith(NO_DEPT) else r["dept"] + " "
    return f"{r['univ']}대 {r['year']}학번 {d}학생인데, "


def prep():
    rows = [{"id": r["id"], "질문": prefix(r) + r["question"]} for r in read(B_CSV)]
    no_overwrite(B_LUNA_IN)
    write(B_LUNA_IN, rows, ["id", "질문"])
    print(f"저장: {B_LUNA_IN.relative_to(ROOT)} ({len(rows)}문항, id·질문 열만)")


def b_judge_input():
    """B를 dev 평가셋 형식으로 바꾼 판정관 어댑터 (key→핵심항목, answer→정답)"""
    out = []
    for r in read(B_CSV):
        ctx = f"[사이드바: {r['univ']}대 {r['year']}학번 · 학과 {r['dept']} · {r['admission']}] "
        out.append({"id": r["id"], "질문": ctx + r["question"], "대학": r["univ"], "학번": r["year"], "유형": "서술", "채점유형": "항목",
                    "빈손여부": "", "정답": r["answer"], "핵심항목": r["key"], "오답신호": "", "근거": r["source"]})
    p = RES / "holdout_b_judge_input.csv"
    write(p, out)
    return p


def run_a():
    check()
    path = RES / f"{TODAY}_holdout-a_service-path_{R.MODEL}.csv"
    no_overwrite(path)
    R.DEV_CSV = A_CSV  # run_rag.cmd_answer가 읽는 평가셋을 홀드아웃 A로 바꾼다(코드는 그대로, dev와 같은 경로)
    R.result_base = lambda smoke, tag="": path.with_suffix("")
    args = SimpleNamespace(chunks="", collection="", ids="", limit=0, tag="", filter=True, expand=True, lookup=True, calc=True,
                           prompt="v2", lookup_prompt="v3", lexical=True)
    R.cmd_answer(args)


def run_b():
    check()
    import engine as E
    path = RES / f"{TODAY}_holdout-b_engine-answer_{R.MODEL}.csv"
    no_overwrite(path)
    eng = E.Engine()
    captured = []
    orig = eng.pl.answer_one

    def cap(*a, **k):
        res = orig(*a, **k)
        captured.append(res.row)
        return res

    eng.pl.answer_one = cap
    rows = []
    for r in read(B_CSV):
        dept = None if r["dept"].startswith(NO_DEPT) else r["dept"]
        out = eng.answer(r["question"], r["univ"], int(r["year"]), dept)
        row = dict(captured[-1])
        if out["answer"] != E.split_answer(row["답변"])[0]:  # 한국어 재생성 실패로 대체 문구가 나간 경우 판정관에는 그 문구를 보낸다
            row["답변"] = out["answer"]
        row["id"] = r["id"]
        row["질문"] = r["question"]
        row.update({"경로": out["route"], "배지": " | ".join(b["text"] for b in out["badges"]), "사용한질문": out["question_used"],
                    "학과붙임": out["used_dept"], "계산결과": out["calc_text"], "시도횟수": out["answer_tries"], "비용USD": f"{out['cost_usd']:.6f}"})
        rows.append(row)
        print(f"  {r['id']} 경로 {out['route']} 시도 {out['answer_tries']} ${out['cost_usd']:.5f}", flush=True)
    write(path, rows)
    print(f"저장: {path.relative_to(ROOT)} 합계 ${sum(float(x['비용USD']) for x in rows):.5f}")


def luna(which):
    check()
    if which == "B":
        inp, out = B_LUNA_IN, RES / f"{TODAY}_holdout-b_luna-web_{R.MODEL}.csv"
        if not inp.exists():
            sys.exit("먼저 prep을 실행하세요")
    else:  # A는 질문 문장에 학교·학번이 이미 들어 있어 접두를 붙이지 않는다. id·질문 열만 임시 파일로 뽑는다
        inp = ROOT / "eval" / "results" / "_holdout_a_luna_input.tmp.csv"
        write(inp, [{"id": r["id"], "질문": r["질문"]} for r in read(A_CSV)], ["id", "질문"])
        out = RES / f"{TODAY}_holdout-a_luna-web_{R.MODEL}.csv"
    no_overwrite(out)
    try:
        subprocess.run([sys.executable, str(ROOT / "src" / "blank_test.py"), "--web", "--input", str(inp), "--out", str(out)], check=True)
    finally:
        if which == "A" and inp.exists():
            inp.unlink()


def newest(pattern):
    fs = sorted(RES.glob(pattern))
    if not fs:
        sys.exit(f"파일 없음: {pattern}")
    return fs[-1]


def judge(which):
    check()
    if which == "a":
        R.DEV_CSV, ans = A_CSV, newest(f"*_holdout-a_service-path_{R.MODEL}.csv")
    elif which == "b":
        R.DEV_CSV, ans = b_judge_input(), newest(f"*_holdout-b_engine-answer_{R.MODEL}.csv")
    else:  # luna-a / luna-b: 인용 근거가 없으므로 인용 열을 비운 판정 입력 파일을 만든다
        side = which.split("-")[1]
        R.DEV_CSV = A_CSV if side == "a" else b_judge_input()
        raw = newest(f"*_holdout-{side}_luna-web_{R.MODEL}.csv")
        ans = raw.with_name(raw.stem + "_judgein.csv")
        no_overwrite(ans)
        write(ans, [{"id": r["id"], "질문": r["질문"], "답변": r["답변"], "인용": "", "인용청크": "", "검색근거표시": "", "적중후보": ""} for r in read(raw)])
    R.find_answer_file = lambda smoke, tag="": ans
    R.cmd_judge(SimpleNamespace(smoke=False, tag="holdout", chunks="", out_suffix=""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "prep", "run-a", "run-b", "luna", "judge"])
    ap.add_argument("arg", nargs="?")
    a = ap.parse_args()
    {"check": check, "prep": prep, "run-a": run_a, "run-b": run_b}.get(a.cmd, lambda: None)() if a.cmd not in ("luna", "judge") else \
        (luna(a.arg.upper()) if a.cmd == "luna" else judge(a.arg.lower()))
