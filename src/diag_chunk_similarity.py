"""진단 (실험 1b 기각 근거): 한남 편람 이수원칙 청크가 왜 검색되지 않는가. 읽기 + 질문·시험 조각 임베딩만 쓴다.
색인은 저장하지 않는다. 개발용 질문만 쓴다.

  1. 질문 ↔ 22-0001, 22-0002 유사도와 기준선 2,108청크 중 순위, 1위·5위 청크 유사도
  2. 시험 조각(이수유형 단위)과 질문의 유사도 — 머리말은 중립("3. 전공학점 이수"), 머리말을 아예 뺀 경우도 함께
     (조각 머리말에 질문 단서인 '부전공'·'다전공'을 넣지 않는다)
  3. 정답 청크 글자수와 순위의 관계 (eval/gold_chunks.json, 단일 청크 정답 그룹)

사용법
    .venv\\Scripts\\python.exe src\\diag_chunk_similarity.py
출력: 표준 출력 + eval/results/<날짜>_diag_chunk_similarity.md. 비용은 usage_log에 기록 (약 $0.0001 미만).
"""

import csv
import json
import statistics as st
import sys
from datetime import date
from pathlib import Path

import chromadb
import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import run_rag  # noqa: E402

QIDS = ["B03", "H03", "H09", "H10", "H04"]
HEAD = "[한남 | 한남대학교 교육과정편람 2026 · 이수원칙 | %s]\n"
DEPTH = 300


def unit(m):
    return m / np.linalg.norm(m, axis=-1, keepdims=True)


def embed(client, texts):
    res = client.embeddings.create(model=run_rag.EMBED_MODEL, input=texts)
    return unit(np.array([d.embedding for d in sorted(res.data, key=lambda d: d.index)], dtype=np.float64)), res.usage.total_tokens


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(ROOT / ".env")
    dev = {r["id"]: r for r in run_rag.load_csv(run_rag.DEV_CSV)}
    chunks = {}
    for line in run_rag.CHUNKS.open(encoding="utf-8"):
        c = json.loads(line)
        chunks[c["id"]] = c
    col = chromadb.PersistentClient(path=str(run_rag.CHROMA_DIR)).get_collection(run_rag.COLLECTION)
    got = col.get(include=["embeddings"])
    ids, mat = got["ids"], unit(np.array(got["embeddings"], dtype=np.float64))
    pos = {i: k for k, i in enumerate(ids)}
    client = OpenAI()
    tokens = 0

    qv, t = embed(client, [dev[q]["질문"] for q in QIDS])
    tokens += t
    L = ["# 진단: 한남 편람 이수원칙 청크 유사도 (실험 1b 기각 근거)", ""]

    L += ["## 1. 질문 ↔ 청크 유사도 (코사인, 기준선 2,108청크 중 순위)", "",
          "| 질문 | 22-0001 | 22-0002 | 1위 청크 | 5위 |", "|---|---|---|---|---|"]
    for k, q in enumerate(QIDS):
        s = mat @ qv[k]
        order = np.argsort(-s)

        def rank(cid):
            return int((s > s[pos[cid]]).sum()) + 1
        top = ids[order[0]]
        L.append(f"| {q} {dev[q]['질문'][:24]} | {s[pos['22-0001']]:.3f} ({rank('22-0001')}위) | {s[pos['22-0002']]:.3f} ({rank('22-0002')}위) | "
                 f"{s[order[0]]:.3f} {top} {chunks[top]['대학']} {chunks[top]['조항'][:16]} | {s[order[4]]:.3f} |")

    lines = chunks["22-0002"]["text"].split("\n")
    typ = [x.strip() for x in lines[1:7]]
    pieces = {
        "이수유형1~6 표만": HEAD % "3. 전공학점 이수 (이수유형 1~6)" + "3. 전공학점 이수\n" + "\n".join(typ),
        "유형4 (중립 머리말)": HEAD % "3. 전공학점 이수" + typ[3],
        "유형5 (중립 머리말)": HEAD % "3. 전공학점 이수" + typ[4],
        "유형4+5 두 줄 (중립)": HEAD % "3. 전공학점 이수" + "\n".join(typ[3:5]),
        "유형4 본문만 (머리말 없음)": typ[3],
    }
    pv, t = embed(client, list(pieces.values()))
    tokens += t
    names = list(pieces)
    L += ["", "## 2. 시험 조각 ↔ 질문 유사도 (괄호는 2,108청크 중 그 유사도의 순위, 색인 저장 없음)", "",
          "| 질문 | 22-0002 원본 | " + " | ".join(names) + " |", "|---|---|" + "---|" * len(names)]
    for k, q in enumerate(QIDS):
        s = mat @ qv[k]
        row = [f"{s[pos['22-0002']]:.3f} ({int((s > s[pos['22-0002']]).sum()) + 1})"]
        for j in range(len(names)):
            sim = float(pv[j] @ qv[k])
            row.append(f"{sim:.3f} ({int((s > sim).sum()) + 1})")
        L.append(f"| {q} | " + " | ".join(row) + " |")
    L += ["", "22-0002는 1,243자 중 이수유형 표가 앞 약 293자이고 나머지는 다전공 제도 안내다.", "", "시험 조각 텍스트:"]
    for n, tx in pieces.items():
        L += [f"- **{n}** ({len(tx)}자)", "  ```", *("  " + x for x in tx.split("\n")), "  ```"]

    # 3. 정답 청크 글자수와 순위 (기준선 컬렉션으로 질문마다 top-300 조회)
    gold = json.loads((ROOT / "eval" / "gold_chunks.json").read_text(encoding="utf-8"))["문항"]
    allq = run_rag.load_csv(run_rag.DEV_CSV)
    av, t = embed(client, [r["질문"] for r in allq])
    tokens += t
    xs, ys, hit, miss = [], [], [], []
    for r, v in zip(allq, av):
        g = gold[r["id"]]
        if g["해당없음"]:
            continue
        order = col.query(query_embeddings=[v.tolist()], n_results=DEPTH)["ids"][0]
        for grp in g["groups"]:
            if len(grp) != 1:
                continue
            rk = order.index(grp[0]) + 1 if grp[0] in order else DEPTH + 1
            n = chunks[grp[0]]["글자수"]
            xs.append(n)
            ys.append(rk)
            (hit if rk <= run_rag.K else miss).append(n)

    def rankdata(a):
        o = np.argsort(a)
        r = np.empty(len(a))
        r[o] = np.arange(len(a))
        return r

    rho = np.corrcoef(rankdata(np.array(xs)), rankdata(np.array(ys)))[0, 1]
    base = [c["글자수"] for c in chunks.values() if c["기본색인"]]
    L += ["", "## 3. 청크 글자수와 정답 청크 순위",
          f"- 기본 색인 청크 글자수: 중앙값 {st.median(base):.0f}, 평균 {st.mean(base):.0f}, 최대 {max(base)}, 600자 초과 {sum(n > 600 for n in base)}개({sum(n > 600 for n in base) / len(base):.1%}), 1,000자 초과 {sum(n > 1000 for n in base) / len(base):.1%}",
          f"- 단일 청크 정답 그룹 {len(xs)}개: 글자수–순위 스피어만 상관 {rho:.2f}",
          f"- top-5 안 정답 청크 글자수 중앙값 {st.median(hit):.0f} (n={len(hit)}), top-5 밖 {st.median(miss):.0f} (n={len(miss)})"]
    text = "\n".join(L) + "\n"
    out = ROOT / "eval" / "results" / f"{date.today().isoformat()}_diag_chunk_similarity.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    cost = tokens / 1e6 * run_rag.EMBED_PRICE
    run_rag.log_usage("diag_embed", run_rag.EMBED_MODEL, tokens, 0, cost, "1b 기각 진단: 질문·시험 조각 임베딩 (색인 저장 없음)")
    print(f"저장: {out.relative_to(ROOT)}  (임베딩 {tokens}토큰 ${cost:.5f})")


if __name__ == "__main__":
    sys.exit(main())
