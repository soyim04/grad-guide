"""질문 하나를 계산 → 조회 → RAG 순으로 답한다. 평가(run_rag.py answer)와 서비스(engine.py·app.py)가 이 한 구현을 같이 쓴다.

7단계에서 run_rag.cmd_answer의 반복문 본문을 그대로 옮겼다. 로직·프롬프트·결과 열은 6단계 채택본(E8 조회, E9 answer-v2,
E10 lookup-v2, E11 calc-v1, E2 필터, E3 확장)과 같고, 바뀐 것은 설정(args → Settings)과 출력(print → notes)뿐이다.
프롬프트·Chat·검색 도우미(chunk_header 등)는 run_rag.py에 그대로 둬서 프롬프트 해시가 변하지 않는다.
순환 import를 피하려고 run_rag.cmd_answer가 이 모듈을 함수 안에서 불러온다.

경로 순서: 계산(criteria_calc) → 조회(criteria_lookup) → RAG. 앞 경로가 안 걸리면 다음 경로로 간다.
평가용 열(근거·대학·학번)이 없는 질문 행(서비스)은 검색 적중 후보·혼입 진단을 건너뛴다.
"""

import json
from collections import namedtuple
from dataclasses import dataclass
from datetime import datetime

import criteria_calc
import criteria_lookup
import query_expand
import query_filter
import run_rag as R

Result = namedtuple("Result", "row notes embed_tokens")


@dataclass
class Settings:
    filter: bool = False
    expand: bool = False
    lookup: bool = False
    calc: bool = False
    prompt: str = "v1"  # RAG 답변 프롬프트: v1 | v2
    lookup_prompt: str = "v1"  # 조회 답변 프롬프트: v1 | v2
    collection: str = R.COLLECTION
    chunks_sha: str = ""


class Pipeline:
    def __init__(self, client, col, chat, settings):
        self.client, self.col, self.chat, self.s = client, col, chat, settings
        self.system, self.version = (R.ANSWER_SYSTEM_V2, R.PROMPT_VERSION_V2) if settings.prompt == "v2" else (R.ANSWER_SYSTEM, R.PROMPT_VERSION)
        self.lsys, self.lver = {"v2": (R.LOOKUP_SYSTEM_V2, R.LOOKUP_VERSION_V2), "v3": (R.LOOKUP_SYSTEM_V3, R.LOOKUP_VERSION_V3)}.get(settings.lookup_prompt, (R.LOOKUP_SYSTEM, R.LOOKUP_VERSION))

    def search_query(self, question):
        """실험 3: 검색용 임베딩만 확장하고 답변 모델은 원래 질문을 본다"""
        return query_expand.expand(question) if self.s.expand else question

    def embed(self, text):
        emb = self.client.embeddings.create(model=R.EMBED_MODEL, input=[text])
        return emb.data[0].embedding, emb.usage.total_tokens

    def answer_one(self, r, sq, vec=None):
        """r: 질문 행(최소 id·질문). sq: 검색용 질문. vec: 미리 만든 질문 벡터(없고 RAG 경로면 여기서 임베딩).
        반환: Result(row=결과 CSV 한 줄과 같은 dict, notes=진행 로그 줄, embed_tokens=이 호출에서 임베딩한 토큰)"""
        s, chat, col = self.s, self.chat, self.col
        notes = []
        if s.calc:
            cres, cwhy = criteria_calc.calc(r["질문"])
            if cres is not None:  # 실험 11: 계산·비교 질문은 코드가 계산, LLM은 설명만
                calc_text, rows_text, row_ids = criteria_calc.build_context(cres)
                user_msg = "[계산 결과]" + chr(10) + calc_text + chr(10) + chr(10) + "[기준표 조회 결과]" + chr(10) + rows_text + chr(10) + chr(10) + "[질문]" + chr(10) + r["질문"]
                ans, tin, tout = chat.json(R.MODEL, R.CALC_SYSTEM, user_msg, R.ANSWER_SCHEMA, "answer")
                cited = [n for n in ans["인용"] if 1 <= n <= len(row_ids)]
                row = {
                    "id": r["id"], "질문": r["질문"], "답변": ans["답변"],
                    "인용": ";".join(map(str, cited)), "인용청크": ";".join(row_ids[n - 1] for n in cited),
                    "검색청크": ";".join(row_ids), "검색거리": "",
                    "검색근거표시": " | ".join(f"{criteria_lookup.BY_ID[i]['대학']} 기준표 {criteria_lookup.BY_ID[i]['항목']} {criteria_lookup.BY_ID[i]['대상']}" for i in row_ids),
                    "적중후보": "", "혼입_대학": "0/0", "혼입_학번": "0/0", "혼입_합계": "0/0",
                    "필터": "", "검색질문": "(criteria 계산)", "계산결과": calc_text.replace(chr(10), " / "),
                    "모델": R.MODEL, "프롬프트버전": R.CALC_VERSION, "프롬프트해시": R.prompt_hash(R.CALC_SYSTEM),
                    "k": "", "컬렉션": "criteria-calc", "chunks_sha256": R.file_sha256(R.ROOT / "data" / "criteria.csv"),
                    "온도": "0" if chat.temperature == 0 else "기본(temperature 거부)",
                    "실행시각": datetime.now().isoformat(timespec="seconds"), "입력토큰": tin, "출력토큰": tout,
                }
                notes.append(f"  {r['id']} 계산({cres['kind']}) 행 {row_ids} 값 {cres['values']} 인용 {cited}")
                return Result(row, notes, 0)
            notes.append(f"  {r['id']} 계산 안 함({cwhy})")
        if s.lookup:
            result, why = criteria_lookup.lookup(r["질문"])
            if result is not None:  # 실험 8: 숫자 질문은 기준표 조회, LLM은 설명만
                context, row_ids = criteria_lookup.build_context(result)
                ans, tin, tout = chat.json(R.MODEL, self.lsys, "[기준표 조회 결과]" + chr(10) + context + chr(10) + chr(10) + "[질문]" + chr(10) + r["질문"], R.ANSWER_SCHEMA, "answer")
                cited = [n for n in ans["인용"] if 1 <= n <= len(row_ids)]
                row = {
                    "id": r["id"], "질문": r["질문"], "답변": ans["답변"],
                    "인용": ";".join(map(str, cited)), "인용청크": ";".join(row_ids[n - 1] for n in cited),
                    "검색청크": ";".join(row_ids), "검색거리": "",
                    "검색근거표시": " | ".join(f"{criteria_lookup.BY_ID[i]['대학']} 기준표 {criteria_lookup.BY_ID[i]['항목']} {criteria_lookup.BY_ID[i]['대상']}" for i in row_ids),
                    "적중후보": "", "혼입_대학": "0/0", "혼입_학번": "0/0", "혼입_합계": "0/0",
                    "필터": "", "검색질문": "(criteria 조회)",
                    "모델": R.MODEL, "프롬프트버전": self.lver, "프롬프트해시": R.prompt_hash(self.lsys),
                    "k": "", "컬렉션": "criteria-lookup", "chunks_sha256": R.file_sha256(R.ROOT / "data" / "criteria.csv"),
                    "온도": "0" if chat.temperature == 0 else "기본(temperature 거부)",
                    "실행시각": datetime.now().isoformat(timespec="seconds"), "입력토큰": tin, "출력토큰": tout,
                }
                notes.append(f"  {r['id']} 조회 행 {row_ids} 인용 {cited}")
                return Result(row, notes, 0)
            notes.append(f"  {r['id']} RAG 폴백({why})")
        embed_tokens = 0
        if vec is None:
            vec, embed_tokens = self.embed(sq)
        where = query_filter.where_for(r["질문"]) if s.filter else None
        hit = col.query(query_embeddings=[vec], n_results=R.K, where=where, include=["documents", "metadatas", "distances"])
        ids, docs, metas, dists = hit["ids"][0], hit["documents"][0], hit["metadatas"][0], hit["distances"][0]
        context = "\n\n".join(f"{R.chunk_header(i, m)}\n{d}" for i, (m, d) in enumerate(zip(metas, docs), 1))
        user = f"[근거]\n{context}\n\n[질문]\n{r['질문']}"
        ans, tin, tout = chat.json(R.MODEL, self.system, user, R.ANSWER_SCHEMA, "answer")
        cited = [n for n in ans["인용"] if 1 <= n <= len(ids)]
        diagnose = all(k in r for k in ("근거", "대학", "학번"))  # 평가용 열이 있을 때만 적중·혼입을 센다
        mix = R.mixed_flags(r, metas) if diagnose else {"대학혼입": 0, "대학대상": 0, "학번혼입": 0, "학번대상": 0, "합계혼입": 0, "합계대상": 0}
        row = {
            "id": r["id"], "질문": r["질문"], "답변": ans["답변"],
            "인용": ";".join(map(str, cited)), "인용청크": ";".join(ids[n - 1] for n in cited),
            "검색청크": ";".join(ids), "검색거리": ";".join(f"{d:.3f}" for d in dists),
            "검색근거표시": " | ".join(f"{m['대학']} {m['규정명']} {m['조항'][:30]}" for m in metas),
            "적중후보": ";".join("Y" if R.hit_candidate(r["근거"], m) else "N" for m in metas) if diagnose else "",
            "혼입_대학": f"{mix['대학혼입']}/{mix['대학대상']}", "혼입_학번": f"{mix['학번혼입']}/{mix['학번대상']}",
            "혼입_합계": f"{mix['합계혼입']}/{mix['합계대상']}",
            "필터": json.dumps(where, ensure_ascii=False) if s.filter else "",
            "검색질문": sq if s.expand else "",
            "모델": R.MODEL, "프롬프트버전": self.version, "프롬프트해시": R.prompt_hash(self.system),
            "k": R.K, "컬렉션": s.collection, "chunks_sha256": s.chunks_sha,
            "온도": "0" if chat.temperature == 0 else "기본(temperature 거부)",
            "실행시각": datetime.now().isoformat(timespec="seconds"), "입력토큰": tin, "출력토큰": tout,
        }
        notes.append(f"  {r['id']} 인용 {cited} 혼입 {mix['합계혼입']}/{mix['합계대상']}")
        return Result(row, notes, embed_tokens)
