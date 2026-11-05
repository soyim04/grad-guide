"""검색 지표 비교 (6단계 실험용): 기준선 컬렉션과 실험 컬렉션에서 같은 질문 임베딩으로 검색해 비교한다.

  - 입력: 개발용 51문항(eval/questions_dev.csv)과 정답 청크(eval/gold_chunks.json). 홀드아웃은 열지 않는다.
  - 질문 임베딩은 한 번만 만들어 두 컬렉션에 같이 쓴다 (임베딩 API 미세 차이가 비교에 섞이지 않게)
  - 지표: 정답 청크 순위(top-300), 검색 적중(Y/부분/대체/N/해당없음), 정답 청크 ≥1개 적중, 혼입률(대학·학번), top-5 변화
  - 적중 정의는 eval/grading_rubric.md (정답 청크 그룹을 모두 top-5에 가지면 Y, 일부면 부분, 정답 청크 없이 대체 근거만이면 대체)

사용법
    .venv\\Scripts\\python.exe src\\eval_retrieval.py --collection exp1a-text-embedding-3-small --tag exp1a [--chunks data/chunks_exp1a.jsonl]
출력: eval/results/<날짜>_<tag>_retrieval.csv (문항별 전→후), <날짜>_<tag>_retrieval.md (요약)
"""

import argparse
import csv
import importlib.util
import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import chromadb
from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
_spec = importlib.util.spec_from_file_location("run_rag", ROOT / "src" / "run_rag.py")
run_rag = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_rag)
import query_filter  # noqa: E402

BASE_COLLECTION = "base-text-embedding-3-small"
DEPTH = 300


def label(top5, groups, alt, na):
    if na:
        return "해당없음"
    hit = [any(x in top5 for x in g) for g in groups]
    if all(hit):
        return "Y"
    if any(hit):
        return "부분"
    return "대체" if any(x in top5 for x in alt) else "N"


def best_ranks(order, groups):
    out = []
    for g in groups:
        rk = [order.index(x) + 1 for x in g if x in order]
        out.append(min(rk) if rk else None)
    return out


def parent(cid):
    """조각 ID(부모ID.n)는 부모 ID로 본다 (E5a: 자식 중 하나라도 top-5면 부모 적중). 기준선 ID에는 '.'이 없다."""
    return cid.split(".")[0]


def search(col, vec, dev_row, where=None):
    r = col.query(query_embeddings=[vec], n_results=DEPTH, where=where, include=["metadatas", "documents"])
    order, metas, docs = r["ids"][0], r["metadatas"][0], r["documents"][0]
    return order, run_rag.mixed_flags(dev_row, metas[:run_rag.K]), [len(d) for d in docs[:run_rag.K]]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--collection", required=True)
    ap.add_argument("--baseline", default=BASE_COLLECTION)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--filter", action="store_true", help="후 컬렉션 검색에 질문에서 뽑은 대학·학번 필터를 건다 (실험 2)")
    ap.add_argument("--chunks", default="", help="실험 청크 파일 (본문이 바뀐 청크를 표시하는 데 씀)")
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")

    dev = run_rag.load_csv(run_rag.DEV_CSV)
    gold = json.loads((ROOT / "eval" / "gold_chunks.json").read_text(encoding="utf-8"))["문항"]
    db = chromadb.PersistentClient(path=str(ROOT / "chroma_db"))
    cols = {"전": db.get_collection(args.baseline), "후": db.get_collection(args.collection)}

    changed = set()
    if args.chunks:
        base_txt = {c["id"]: c["text"] for c in map(json.loads, run_rag.CHUNKS.open(encoding="utf-8"))}
        for c in map(json.loads, Path(args.chunks).open(encoding="utf-8")):
            if base_txt.get(c["id"]) != c["text"]:
                changed.add(c["id"])
            if "부모id" in c:  # 나뉜 부모의 정답 청크 표시용
                changed.add(c["부모id"])

    emb = OpenAI().embeddings.create(model=run_rag.EMBED_MODEL, input=[r["질문"] for r in dev])
    vecs = [d.embedding for d in sorted(emb.data, key=lambda d: d.index)]
    tokens = emb.usage.total_tokens

    rows = []
    for q, vec in zip(dev, vecs):
        g = gold[q["id"]]
        row = {"id": q["id"], "대학": q["대학"], "학번": q["학번"], "채점유형": q["채점유형"]}
        res = {}
        where = query_filter.where_for(q["질문"]) if args.filter else None
        row["필터"] = json.dumps(where, ensure_ascii=False) if where else ""
        for k, col in cols.items():
            order_raw, mix, lens = search(col, vec, q, where if k == "후" else None)
            order = [parent(x) for x in order_raw]  # 정답 청크 순위·적중은 부모 ID 기준 (순위는 첫 조각 위치)
            top5 = order[:run_rag.K]
            res[k] = (order, order_raw[:run_rag.K], mix)
            ranks = best_ranks(order, g["groups"])
            row[f"top5_{k}"] = ";".join(order_raw[:run_rag.K])
            row[f"top5글자수_{k}"] = sum(lens) / len(lens)
            row[f"top5부모수_{k}"] = len(set(top5))
            row[f"정답청크순위_{k}"] = ";".join("-" if x is None else str(x) for x in ranks)
            row[f"적중_{k}"] = label(top5, g["groups"], g["alt"], g["해당없음"])
            row[f"혼입_{k}"] = f"{mix['합계혼입']}/{mix['합계대상']}"
            row[f"혼입대학_{k}"] = f"{mix['대학혼입']}/{mix['대학대상']}"
            row[f"혼입학번_{k}"] = f"{mix['학번혼입']}/{mix['학번대상']}"
        row["top5_바뀜"] = "Y" if row["top5_전"] != row["top5_후"] else "N"
        row["top5에_바뀐청크"] = "Y" if changed & set(res["후"][1]) else "N"
        row["정답청크_바뀜"] = "Y" if changed & {x for grp in g["groups"] for x in grp} else "N"
        rows.append(row)

    date_s = date.today().isoformat()
    csv_path = ROOT / "eval" / "results" / f"{date_s}_{args.tag}_retrieval.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    def counts(side):
        return Counter(r[f"적중_{side}"] for r in rows)

    def sums(side, key):
        m = d = 0
        for r in rows:
            a, b = r[f"{key}_{side}"].split("/")
            m, d = m + int(a), d + int(b)
        return f"{m}/{d}"

    cb, ca = counts("전"), counts("후")
    use = [r for r in rows if r["적중_전"] != "해당없음"]

    def any1(side):
        return sum(1 for r in use if (r[f"적중_{side}"] in ("Y", "부분")))

    L = [f"# 검색 지표 비교 — {args.tag} ({date_s})", "",
         f"- 컬렉션 전 `{args.baseline}` → 후 `{args.collection}`, 같은 질문 임베딩 사용, 깊이 top-{DEPTH}, k={run_rag.K}",
         f"- 바뀐 청크(본문 기준) {len(changed)}개" if args.chunks else "", "",
         "| 지표 | 전 | 후 |", "|---|---|---|"]
    for k in ("Y", "부분", "대체", "N", "해당없음"):
        L.append(f"| 검색 적중 {k} | {cb[k]} | {ca[k]} |")
    L.append(f"| 정답 청크 ≥1개 top-5 (Y+부분 / {len(use)}문항) | {any1('전')} | {any1('후')} |")
    L.append(f"| 혼입률 합계 | {sums('전', '혼입')} | {sums('후', '혼입')} |")
    L.append(f"| 혼입률 대학 | {sums('전', '혼입대학')} | {sums('후', '혼입대학')} |")
    L.append(f"| 혼입률 학번 | {sums('전', '혼입학번')} | {sums('후', '혼입학번')} |")

    def avg(side, key):
        return sum(r[f"{key}_{side}"] for r in rows) / len(rows)
    L.append(f"| top-5 평균 글자 수 | {avg('전', 'top5글자수'):.0f} | {avg('후', 'top5글자수'):.0f} |")
    L.append(f"| top-5 안 서로 다른 부모 수(평균) | {avg('전', 'top5부모수'):.2f} | {avg('후', 'top5부모수'):.2f} |")
    order_rank = {"해당없음": 0, "N": 0, "대체": 1, "부분": 2, "Y": 3}
    better = [r["id"] for r in rows if r["적중_전"] != "해당없음" and order_rank[r["적중_후"]] > order_rank[r["적중_전"]]]
    worse = [r["id"] for r in rows if r["적중_전"] != "해당없음" and order_rank[r["적중_후"]] < order_rank[r["적중_전"]]]
    L += ["", f"- 적중 좋아진 문항 {len(better)}: {', '.join(better)}", f"- 적중 나빠진 문항 {len(worse)}: {', '.join(worse)}"]
    nb = sum(r["top5_바뀜"] == "Y" for r in rows)
    L += ["", f"- top-5가 바뀐 문항 {nb}/{len(rows)} (이월 불가, 답변을 다시 돌려야 하는 문항)",
          f"- top-5에 바뀐 청크가 들어 있는 문항 {sum(r['top5에_바뀐청크'] == 'Y' for r in rows)}",
          f"- 정답 청크 자체가 바뀐 문항 {sum(r['정답청크_바뀜'] == 'Y' for r in rows)}"]
    moved = [r for r in rows if r["정답청크순위_전"] != r["정답청크순위_후"] or r["적중_전"] != r["적중_후"] or r["top5_바뀜"] == "Y"]
    L += ["", f"## 달라진 문항 {len(moved)}개 (정답 청크 순위 전 → 후, 적중 전 → 후)"]
    for r in moved:
        L.append(f"- {r['id']} [{r['대학']}] 순위 {r['정답청크순위_전']} → {r['정답청크순위_후']}, 적중 {r['적중_전']} → {r['적중_후']}"
                 f"{', top-5 바뀜' if r['top5_바뀜'] == 'Y' else ''}{', 정답 청크 본문 바뀜' if r['정답청크_바뀜'] == 'Y' else ''}")
    md_path = csv_path.with_suffix(".md")
    md_path.write_text("\n".join(x for x in L if x is not None) + "\n", encoding="utf-8")
    print(md_path.read_text(encoding="utf-8"))

    cost = tokens / 1e6 * run_rag.EMBED_PRICE
    run_rag.log_usage("retrieval_eval", run_rag.EMBED_MODEL, tokens, 0, cost, f"{args.tag} 검색 지표 비교, 개발용 51문항 질문 임베딩")
    print(f"저장: {csv_path.relative_to(ROOT)}, {md_path.relative_to(ROOT)}  (질문 임베딩 {tokens}토큰 ${cost:.5f})")


if __name__ == "__main__":
    sys.exit(main())
