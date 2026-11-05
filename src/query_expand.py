"""실험 3: 질문 동의어 확장. data/synonyms.json의 groups(같은 뜻)만 쓰고 similar는 쓰지 않는다. 비용 0.

질문에 그룹 용어가 있으면, 질문의 학교가 쓰는 용어(school_terms, 비었거나 학교 미지정이면 그룹 전체 terms) 중
질문에 없는 것을 뒤에 덧붙인다. 원래 단어는 지우지 않는다. 검색용 임베딩에만 쓴다 (답변 모델은 원래 질문을 봄).
`학번` 그룹은 E2 필터가 다루므로 제외.
"""

import json
from pathlib import Path

import query_filter

ROOT = Path(__file__).resolve().parent.parent
SYN = json.loads((ROOT / "data" / "synonyms.json").read_text(encoding="utf-8"))
SKIP = {"학번"}


def added_terms(question):
    schools = query_filter.extract_universities(question)
    added = []
    for g in SYN["groups"]:
        if g["canon"] in SKIP or not any(t in question for t in g["terms"]):
            continue
        if schools and all(g["school_terms"].get(s) for s in schools):
            pool = [t for s in schools for t in g["school_terms"][s]]
        else:
            pool = g["terms"]
        for t in pool:
            if t not in question and t not in added:
                added.append(t)
    return added


def expand(question):
    add = added_terms(question)
    return f"{question} ({' '.join(add)})" if add else question
