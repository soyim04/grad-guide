"""data/chunks.jsonl 중 기본색인=true 청크를 임베딩해 ChromaDB에 저장한다 (5단계, 기본 RAG).

- 임베딩 입력은 embed_text(머리말 + 본문), 저장 문서는 text
- 순수 RAG이므로 메타데이터 필터는 쓰지 않는다. 메타데이터는 저장만 해 둔다 (개선 단계에서 필터로 사용)
- Chroma 메타데이터는 None·리스트를 못 쓰므로 변환한다: 쪽은 문자열("242" 또는 "242-243"),
  학번 구간은 정수(시작 비면 0, 끝 비면 9999, 판별 문서가 아니면 둘 다 0/9999)
- 사용 토큰과 비용은 eval/usage_log.csv에 쌓는다 (1차와 같은 형식)

실험용 색인 (6단계): 규칙을 적용한 청크 파일로 새 컬렉션을 만들고 기준선 컬렉션은 건드리지 않는다.
  --chunks data/chunks_exp1a.jsonl --collection exp1a-text-embedding-3-small --reuse-from base-text-embedding-3-small
  --reuse-from: 기준선 컬렉션에서 embed_text가 같은 청크의 임베딩을 그대로 복사하고, 바뀐 청크만 새로 임베딩한다.

사용법
    .venv\\Scripts\\python.exe src\\build_index.py
"""

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import chromadb
from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
CHUNKS = ROOT / "data" / "chunks.jsonl"
CHROMA_DIR = ROOT / "chroma_db"
USAGE_LOG = ROOT / "eval" / "usage_log.csv"

EMBED_MODEL = "text-embedding-3-small"
EMBED_PRICE_PER_1M = 0.02  # 달러 (1차에서 확인한 값, 2026-10-02)
BATCH_SIZE = 100
COLLECTION = f"base-{EMBED_MODEL}"
DROP_FIELDS = ("text", "embed_text", "쪽_PDF", "쪽_인쇄", "학번_시작", "학번_끝")


def pages(v):
    if not v:
        return ""
    return str(v[0]) if v[0] == v[1] else f"{v[0]}-{v[1]}"


def to_metadata(c):
    meta = {k: v for k, v in c.items() if k not in DROP_FIELDS and v is not None}
    meta["쪽_PDF"] = pages(c["쪽_PDF"])
    meta["쪽_인쇄"] = pages(c["쪽_인쇄"])
    meta["학번_시작"] = c["학번_시작"] if c["학번_시작"] is not None else 0
    meta["학번_끝"] = c["학번_끝"] if c["학번_끝"] is not None else 9999
    return meta


def embed_all(client, texts):
    vectors, total = [], 0
    for start in range(0, len(texts), BATCH_SIZE):
        res = client.embeddings.create(model=EMBED_MODEL, input=texts[start:start + BATCH_SIZE])
        vectors.extend(d.embedding for d in sorted(res.data, key=lambda d: d.index))
        total += res.usage.total_tokens
        print(f"  임베딩 {min(start + BATCH_SIZE, len(texts))}/{len(texts)}", flush=True)
    return vectors, total


def log_usage(row):
    is_new = not USAGE_LOG.exists()
    with USAGE_LOG.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if is_new:
            w.writeheader()
        w.writerow(row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", default=str(CHUNKS))
    ap.add_argument("--collection", default=COLLECTION)
    ap.add_argument("--reuse-from", default="")
    args = ap.parse_args()
    chunks_path, collection = Path(args.chunks), args.collection
    if chunks_path.resolve() != CHUNKS.resolve() and collection == COLLECTION:
        sys.exit("기준선 컬렉션 이름으로 다른 청크 파일을 색인할 수 없습니다. --collection을 바꾸세요.")
    load_dotenv(ROOT / ".env")
    chunks = [c for c in map(json.loads, chunks_path.open(encoding="utf-8")) if c["기본색인"]]
    db = chromadb.PersistentClient(path=str(CHROMA_DIR))

    vectors = [None] * len(chunks)
    reused = 0
    if args.reuse_from:
        base_embed = {c["id"]: c["embed_text"] for c in map(json.loads, CHUNKS.open(encoding="utf-8")) if c["기본색인"]}
        got = db.get_collection(args.reuse_from).get(ids=[c["id"] for c in chunks if c["id"] in base_embed], include=["embeddings"])
        base_vec = dict(zip(got["ids"], got["embeddings"]))
        for k, c in enumerate(chunks):
            if c["id"] in base_vec and base_embed.get(c["id"]) == c["embed_text"]:
                vectors[k] = [float(x) for x in base_vec[c["id"]]]
                reused += 1
    todo = [k for k, v in enumerate(vectors) if v is None]
    print(f"기본색인=true 청크 {len(chunks)}개: 기준선 임베딩 재사용 {reused}개, 새로 임베딩 {len(todo)}개")
    new_vecs, tokens = embed_all(OpenAI(), [chunks[k]["embed_text"] for k in todo]) if todo else ([], 0)
    for k, v in zip(todo, new_vecs):
        vectors[k] = v

    if collection in [c.name for c in db.list_collections()]:
        db.delete_collection(collection)
    col = db.create_collection(collection, embedding_function=None, metadata={"hnsw:space": "cosine"})
    for s in range(0, len(chunks), 500):
        part = chunks[s:s + 500]
        col.add(ids=[c["id"] for c in part], documents=[c["text"] for c in part],
                embeddings=vectors[s:s + 500], metadatas=[to_metadata(c) for c in part])
    print(f"컬렉션 {collection}: {col.count()}개 저장")

    cost = tokens / 1_000_000 * EMBED_PRICE_PER_1M
    log_usage({
        "시각": datetime.now().isoformat(timespec="seconds"), "작업": "build_index", "모델": EMBED_MODEL,
        "입력 토큰": tokens, "출력 토큰": 0, "비용(달러)": f"{cost:.5f}",
        "메모": (f"기본 RAG 색인, 청크 {len(chunks)}개 (기본색인=true만)" if collection == COLLECTION else
                f"실험 색인 {collection}, 청크 {len(chunks)}개 중 새로 임베딩 {len(todo)}개(기준선 재사용 {reused}개), {chunks_path.name}"),
    })
    print(f"임베딩 토큰 {tokens:,}개, 비용 약 ${cost:.5f} → eval/usage_log.csv")


if __name__ == "__main__":
    sys.exit(main())
