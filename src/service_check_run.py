"""서비스 답변 점검(평가셋 dev/holdout과 별개). 새 화면과 같은 경로(사이드바 값 → 질문 접두 → Engine.answer)로 질문을 한 번 실행해 CSV로 저장한다.
이 결과를 보고 특정 질문 맞춤으로 고치지 않는다(고칠 땐 일반 규칙만). 기대 답은 사람이 따로 채점한다.

실행: .venv\\Scripts\\python.exe src\\service_check_run.py   (API 비용 약 $0.01)
"""

import csv
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

import engine  # noqa: E402
import service_calc as S  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = engine.OUT_OF_RANGE
# (대학, 학번, 학과(None이면 경영 계열 기본 학과), 입학 구분, 질문)
CASES = [
    ("충남", 2023, None, "신입", "졸업 평점 몇 이상이야?"),
    ("한밭", 2024, None, "신입", "비교과 몇 유닛 들어야 돼?"),
    ("배재", 2023, None, "신입", "졸업하려면 몇 학점?"),
    ("배재", 2025, None, "신입", "졸업하려면 몇 학점?"),
    ("배재", 2023, None, "신입", "부전공은 몇 학점 이수해야 해?"),
    ("충남", 2024, None, "신입", "복수전공 몇 학점이야?"),
    ("배재", 2023, None, "신입", "부전공이랑 다전공 중 뭐가 전공학점이 적어?"),
    ("충남", 2024, None, "신입", "재수강은 어떻게 해?"),
    ("목원", 2022, None, "신입", "비교과 몇 시간 들어야 해?"),
    ("한남", 2023, None, "신입", "졸업 평점 기준 있어?"),
    ("배재", 2023, None, "편입", "편입생은 전공 몇 학점 들어야 해?"),
    ("배재", OUT, None, "신입", "2019학번 졸업학점 알려줘"),
    ("한밭", 2024, None, "신입", "수강신청은 언제부터 해?"),
]


def main():
    eng = engine.Engine()
    rows, total = [], 0.0
    for i, (univ, year, dept, entry, q) in enumerate(CASES, 1):
        dept = dept or S.BASE_DEPT[univ]
        out = eng.answer(q, univ, year, dept)
        cards = " | ".join("[{}] {}".format(",".join(map(str, s["nums"])), s["id"] if s["kind"] == "기준표" else f"{s['title']} {s['article']}") for s in out["sources"])
        badges = " | ".join(f"{b['kind']}: {b['text']}" for b in out["badges"])
        hint = []
        if isinstance(year, int) and any(b["kind"] == "확인불가" for b in out["badges"]):  # 화면과 같은 규칙: 확인 불가 배지가 있을 때만
            hint = S.checklist_hint(q, univ, year, dept, entry, False)
        total += out["cost_usd"]
        rows.append({"번호": i, "대학": univ, "학번": year, "학과": dept, "입학구분": entry, "질문": q, "경로": out["route"], "답변": out["answer"],
                     "근거카드": cards, "배지": badges, "체크리스트안내": " · ".join(hint), "실제질문": out["question_used"],
                     "비용_usd": f"{out['cost_usd']:.5f}", "응답_ms": out["latency_ms"]})
        print(f"{i:>2} {univ} {year} [{out['route']}] {q} -> {len(out['answer'])}자 ${out['cost_usd']:.5f}")
    path = ROOT / "eval" / "results" / f"service_check_{date.today():%Y%m%d}.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"저장: {path} · 총 비용 ${total:.4f}")


main()
