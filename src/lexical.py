"""E31 [2]: 간이 BM25 어휘 검색. 벡터 top-5는 그대로 두고, 같은 필터로 거른 후보에서 BM25 상위 N개 중 벡터 top-5에 없는 청크를 덧붙인다.
형태소 분석 없이 글자 2개 단위 낱말(1글자 낱말은 그대로)로 쪼갠다. N=4는 서비스 사례 3건에 맞춘 값이다(experiments.md E31 사전 등록)."""

import collections
import math
import re

TOP_N = 4
K1, B = 1.2, 0.75
STOP = set("몇 어떻게 받으면 있어 해요 해야 돼 들을 수 까지 어떤 이상 학생 학번 최대".split())
_PREFIX = re.compile(r"^.*?학생:\s*")  # 사이드바가 붙인 "한남대 2023학번 경영정보학과 학생: " 접두는 낱말에서 뗀다
_cache = {}  # 청크 id → 낱말 목록(프로세스 안에서 한 번만 계산)


def toks(text):
    out = []
    for w in re.sub(r"[^0-9가-힣A-Za-z]+", " ", text).split():
        if w in STOP:
            continue
        out += [w] if len(w) == 1 else [w[i:i + 2] for i in range(len(w) - 1)]
    return out


def extra_chunks(col, question, where, dense_ids):
    """반환: [(id, 문서, 메타데이터)] — BM25 상위 TOP_N 중 dense_ids에 없는 청크, BM25 순서대로"""
    g = col.get(where=where, include=["documents", "metadatas"]) if where else col.get(include=["documents", "metadatas"])
    ids, docs, metas = g["ids"], g["documents"], g["metadatas"]
    if not ids:
        return []
    for i, d in zip(ids, docs):
        if i not in _cache:
            _cache[i] = toks(d)
    D = [_cache[i] for i in ids]
    n = len(D)
    avg = sum(map(len, D)) / n
    df = collections.Counter(t for d in D for t in set(d))
    q = set(toks(_PREFIX.sub("", question, count=1)))
    scored = []
    for k, d in enumerate(D):
        c = collections.Counter(d)
        s = 0.0
        for t in q:
            if t in c:
                s += math.log(1 + (n - df[t] + .5) / (df[t] + .5)) * c[t] * (K1 + 1) / (c[t] + K1 * (1 - B + B * len(d) / avg))
        scored.append((s, k))
    scored.sort(key=lambda x: (-x[0], x[1]))
    top = [k for s, k in scored[:TOP_N] if s > 0]
    return [(ids[k], docs[k], metas[k]) for k in top if ids[k] not in set(dense_ids)]
