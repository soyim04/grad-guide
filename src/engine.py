"""7단계 서비스 엔진: 질문 하나를 6단계 채택 파이프라인(pipeline.py)으로 답하고 화면용 dict로 돌려준다.

설정은 6단계 최종(E11): E2 대학·학번 필터 + E3 질문 동의어 확장 + 조회(lookup-v2) + 계산(calc-v1) + RAG(answer-v2), k=5.
파이프라인 로직은 평가(run_rag.py answer)와 같은 pipeline.Pipeline.answer_one을 쓴다. 이 파일이 하는 일은 세 가지다.
1. 사이드바 값(대학·학번·학과)을 질문 앞에 붙이되, 질문에 이미 있는 것은 질문을 우선한다(build_question).
2. 결과 행에서 화면용 출처 카드·배지·본문을 만든다(출처 줄 분리, 같은 행·같은 조항은 한 번만).
3. 비용·응답 시간을 잰다.
"""

import re
import time

import chromadb
from dotenv import load_dotenv
from openai import OpenAI

import criteria_calc
import criteria_lookup as L
import pipeline
import query_filter as QF
import run_rag as R

OUT_OF_RANGE = "범위 밖"  # 학번 선택지: 2022~2026학번 밖
SERVICE_SETTINGS = dict(filter=True, expand=True, lookup=True, calc=True, prompt="v2", lookup_prompt="v2")
SOURCE_LINE = re.compile(r"\n[ \t]*(?:[-•*][ \t]*)?(?:인용[ \t]*)?출처[ \t]*[:：—-]")
FLAG_NOTE = ("학과 확인 필요", "사유 미확인")


# ---------- 질문 만들기 ----------

def _mentions_dept(question):
    return any(m not in L.SCHOOL_WORDS and m != "일반학과" for m in L.MENTION_RE.findall(question))


def build_question(question, univ=None, year=None, dept=None):
    """사이드바 값 중 질문에 없는 것만 앞에 붙인다(질문 우선).
    - 대학: 질문에 대학이 있으면 붙이지 않는다(사이드바 한남 + 질문 '충남대'가 대학 2개가 되는 것을 막는다)
    - 학번: 질문에 N학번이 있으면 붙이지 않는다
    - 학과: 질문에 학과·학부 이름이 있거나 질문의 대학이 사이드바 대학과 다르면 붙이지 않는다
    반환: (학과를 붙인 질문, 학과 없이 만든 질문, 학과를 붙였는지)"""
    q_univ = QF.extract_universities(question)
    parts = []
    if univ and not q_univ:
        parts.append(f"{univ}대")
    if isinstance(year, int) and not QF.extract_years(question):
        parts.append(f"{year}학번")
    plain = (" ".join(parts) + " 학생: " + question) if parts else question
    dept_ok = bool(dept) and not _mentions_dept(question) and (not q_univ or q_univ == [univ])
    if not dept_ok:
        return plain, plain, False
    with_dept = " ".join(parts + [dept]) + " 학생: " + question
    return with_dept, plain, True


def routable(question):
    """계산 또는 조회 경로로 답할 수 있는 질문인가(LLM 호출 없이 규칙만 본다)"""
    return criteria_calc.calc(question)[0] is not None or L.lookup(question)[0] is not None


def choose_question(question, univ=None, year=None, dept=None):
    """학과를 붙였을 때 계산·조회 경로가 열리면 그 문장을 쓰고, 안 열리면 학과 없이 만든 문장을 쓴다.
    (학과 이름이 있으면 '지목했는데 맞는 행이 없으면 RAG로 폴백'하는 조회 규칙 때문에, 대학 공통 행만 있는 항목이 막히는 것을 피한다.
    RAG 경로는 학과 없이 만든 문장을 쓴다.) 반환: (사용한 질문, 학과를 붙였는지)"""
    with_dept, plain, used = build_question(question, univ, year, dept)
    if used and routable(with_dept):
        return with_dept, True
    return plain, False


# ---------- 화면용 변환 ----------

def split_answer(text):
    """LLM이 끝에 붙인 '출처:' 줄을 본문에서 뗀다. 출처 카드는 인용 행·청크의 메타데이터로 따로 만든다."""
    m = SOURCE_LINE.search("\n" + text)
    if not m:
        return text.strip(), ""
    cut = m.start() - 1  # 앞에 붙인 "\n" 보정
    if cut <= 0:  # 본문 없이 출처 줄만 있으면 통째로 본문으로 둔다
        return text.strip(), ""
    return text[:cut].strip(), text[cut:].strip()


def _grade_label(g):
    return {"A": "A 규정 원문", "B": "B 교육과정 편람", "C": "C 학사안내", "D": "D 입학·공지"}.get(g, g or "")


def cited_pairs(row, body, criteria_route=False):
    """답에 나온 근거 번호와 그 번호가 가리키는 청크·행 ID를 (번호, ID) 쌍으로 돌려준다(번호 오름차순).
    번호는 모델이 본 검색 번호 그대로이고 카드에서 다시 매기지 않는다. 모델이 JSON 인용 목록에 안 넣었어도 답 본문에 [n]이 있으면 포함한다.
    조회·계산 경로에서 인용이 하나도 없으면 넘어온 행 전부를 근거로 본다."""
    retrieved = [i for i in str(row["검색청크"]).split(";") if i]
    nums = [int(n) for n in str(row["인용"]).split(";") if n.strip().isdigit()]
    nums += [int(n) for n in re.findall(r"\[(\d+)\]", body)]
    nums = sorted({n for n in nums if 1 <= n <= len(retrieved)})
    if not nums and criteria_route:
        nums = list(range(1, len(retrieved) + 1))
    return [(n, retrieved[n - 1]) for n in nums]


class Engine:
    def __init__(self):
        load_dotenv(R.ROOT / ".env")
        self.client = OpenAI()
        self.col = chromadb.PersistentClient(path=str(R.CHROMA_DIR)).get_collection(R.COLLECTION)
        self.chat = R.Chat(self.client)
        # 서비스는 색인을 새로 만들지 않으므로 기록된 청크 해시를 그대로 적는다(평가 실행은 파일 해시를 다시 확인한다)
        self.settings = pipeline.Settings(collection=R.COLLECTION, chunks_sha=R.CHUNKS_SHA256, **SERVICE_SETTINGS)
        self.pl = pipeline.Pipeline(self.client, self.col, self.chat, self.settings)

    def answer(self, question, univ=None, year=None, dept=None):
        """반환 dict: answer(본문), tail(LLM이 붙인 출처 줄), sources[], badges[], route, cost_usd, latency_ms, question_used, used_dept"""
        t0 = time.time()
        if year == OUT_OF_RANGE:
            body = "입학년도(학번)가 이 서비스의 범위(2022~2026학번) 밖이라 확인할 수 없어요. 학과 사무실이나 학사 공지를 확인해 주세요."
            return {"answer": body, "tail": "", "sources": [], "badges": [{"kind": "확인불가", "text": "서비스 범위(2022~2026학번) 밖"}],
                    "route": "범위 밖", "cost_usd": 0.0, "latency_ms": int((time.time() - t0) * 1000), "question_used": question, "used_dept": False,
                    "tokens_in": 0, "tokens_out": 0, "embed_tokens": 0}
        q, used = choose_question(question, univ, year, dept)
        res = self.pl.answer_one({"id": "svc", "질문": q}, self.pl.search_query(q))
        row = res.row
        body, tail = split_answer(row["답변"])
        sources, badges = self._sources_and_badges(row, body)
        cost = row["입력토큰"] / 1e6 * R.PRICE_IN + row["출력토큰"] / 1e6 * R.PRICE_OUT + res.embed_tokens / 1e6 * R.EMBED_PRICE
        route = {"criteria-calc": "계산", "criteria-lookup": "조회"}.get(row["컬렉션"], "규정 검색")
        return {"answer": body, "tail": tail, "sources": sources, "badges": badges, "route": route, "cost_usd": cost,
                "latency_ms": int((time.time() - t0) * 1000), "question_used": q, "used_dept": used, "calc_text": row.get("계산결과", ""),
                "tokens_in": row["입력토큰"], "tokens_out": row["출력토큰"], "embed_tokens": res.embed_tokens}

    # ---- 출처 카드·배지 ----
    def _sources_and_badges(self, row, body):
        criteria_route = row["컬렉션"] in ("criteria-calc", "criteria-lookup")
        pairs = cited_pairs(row, body, criteria_route)
        ids = [cid for _, cid in pairs]
        nums_of = {}  # 같은 행·조항을 한 카드로 합칠 때 모델이 본 번호를 모두 남긴다
        for n, cid in pairs:
            nums_of.setdefault(cid, []).append(n)
        sources, badges, seen = [], [], set()
        if criteria_route:
            for rid in ids:
                if rid in seen or rid not in L.BY_ID:
                    continue  # 같은 행은 한 번만
                seen.add(rid)
                r = L.BY_ID[rid]
                value = f"{r['값']}{r['단위']} {r['비교']}".strip() if r["값"] else r["상태"]
                sources.append({"kind": "기준표", "id": rid, "nums": nums_of[rid], "title": f"{r['대학']} 기준표 · {r['항목']}", "target": r["대상"], "value": value,
                                "status": r["상태"], "article": r["출처조항"], "pages": r["출처쪽"], "grade": _grade_label(r["출처등급"])})
                if r["상태"] == "잠정":
                    badges.append({"kind": "잠정", "text": "이 값은 잠정이에요 (학과 확인)", "rid": rid})
                if any(k in r["비고"] for k in FLAG_NOTE):
                    badges.append({"kind": "학과확인필요", "text": "출처마다 값이 달라요 (학과 확인)", "rid": rid})
        else:
            metas = {}
            if ids:
                got = self.col.get(ids=list(dict.fromkeys(ids)), include=["metadatas"])
                metas = dict(zip(got["ids"], got["metadatas"]))
            groups = {}
            for cid in ids:
                m = metas.get(cid)
                if not m:
                    continue
                g = groups.setdefault((m["규정명"], m["조항"]), {"kind": "규정", "id": cid, "nums": [], "title": m["규정명"], "article": m["조항"],
                                                              "pages": [], "grade": _grade_label(m["출처등급"]), "edition": f"{m['판본']}({m['판본연도']})" if m.get("판본연도") else m.get("판본", ""),
                                                              "univ": m["대학"]})
                g["nums"] = sorted(set(g["nums"]) | set(nums_of[cid]))
                pdf = f"PDF {m['쪽_PDF']}쪽" + (f" (인쇄 {m['쪽_인쇄']}쪽)" if m.get("쪽_인쇄") not in (None, "", m["쪽_PDF"]) else "")
                if pdf not in g["pages"]:
                    g["pages"].append(pdf)
            for g in groups.values():
                g["pages"] = ", ".join(g["pages"])
                sources.append(g)
        if R.UNANSWERABLE_RE.search(body):
            badges.insert(0, {"kind": "확인불가", "text": "규정에서 확인되지 않은 내용이 있어요. 학과 사무실이나 학사 공지를 확인하세요"})
        uniq, out = {}, []
        for b in badges:  # 같은 문구는 한 번만(배지에는 행 ID를 쓰지 않는다. 행 ID는 'rids'에만 모아 두고 개발자 모드에서만 화면에 붙인다, E24d)
            rid = b.pop("rid", None)
            k = (b["kind"], b["text"])
            if k not in uniq:
                uniq[k] = b
                b["rids"] = []
                out.append(b)
            if rid and rid not in uniq[k]["rids"]:
                uniq[k]["rids"].append(rid)
        return sources, out
