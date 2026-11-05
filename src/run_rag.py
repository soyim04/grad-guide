"""기본 RAG(고치기 전) 실행·채점: 개발용 51문항 전용.

하위 명령
  answer  질문 임베딩 → Chroma 상위 k개 → 답변 생성. 결과: eval/results/<날짜>_dev_base-rag_<모델>.csv
  judge   답변 파일을 읽어 자동 표시 + 판정관(LLM) 사전 채점. 결과: <같은 이름>_grade-v1.csv
          (최종판정·최종틀린이유·최종인용일치·최종검색적중 열은 사람이 채운다)
  report  사람이 채운 채점 파일에서 지표를 계산해 출력하고 <같은 이름>_report.md로 저장

원칙 (eval/grading_rubric.md 에 동결)
  - 순수 RAG: 메타데이터 필터 없음, 질문 문장만으로 검색. 평가셋의 대학·학번·정답은 모델에 보내지 않는다.
  - 홀드아웃 파일은 이 스크립트가 열지 않는다 (DEV_CSV 하나만 읽는다).
  - 프롬프트를 바꾸면 PROMPT_VERSION을 올리고 grading_rubric.md 의 해시를 갱신한다.

실행 예
  .venv\\Scripts\\python.exe src\\run_rag.py answer
  .venv\\Scripts\\python.exe src\\run_rag.py judge
  .venv\\Scripts\\python.exe src\\run_rag.py report
  (시험용: answer --limit 2 → 파일명에 _smoke가 붙고 judge·report도 --smoke로 같은 파일을 읽는다)
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import chromadb
import openai
from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
DEV_CSV = ROOT / "eval" / "questions_dev.csv"  # 개발용 51문항만. 홀드아웃은 열지 않는다
CHUNKS = ROOT / "data" / "chunks.jsonl"
CHROMA_DIR = ROOT / "chroma_db"
RESULTS = ROOT / "eval" / "results"
USAGE_LOG = ROOT / "eval" / "usage_log.csv"

CHUNKS_SHA256 = "35c2070b351069414a5d3489e7615f18a86e17938a610c556d4832ccff054ab8"  # CLAUDE.md 5단계 기록
COLLECTION = "base-text-embedding-3-small"
EMBED_MODEL = "text-embedding-3-small"
EMBED_PRICE = 0.02  # 달러 / 100만 토큰
MODEL = "gpt-6-luna"
JUDGE_MODEL = "gpt-6-luna"
PRICE_IN, PRICE_OUT = 0.10, 0.50  # 달러 / 100만 토큰 (blank_test.py와 같음)
K = 5
PROMPT_VERSION = "answer-v1"
JUDGE_VERSION = "judge-v1"

ANSWER_SYSTEM = """당신은 대전 지역 5개 대학(배재·충남·한남·한밭·목원)의 졸업요건 안내 도우미입니다.
아래 [근거]에 적힌 내용만으로, 한국어로 쉽게 답하세요.

규칙
1. [근거]에 답이 없으면 숫자나 조건을 지어내지 말고 "확인 불가"라고 답하고, 어떤 내용이 근거에 없는지 한 줄로 밝힌다.
2. 질문한 학번이 2022~2026학번 범위 밖이면 "확인 불가"라고 답한다. 근거에 다른 학번의 값이 있어도 그 학번의 값처럼 말하지 않는다.
3. 근거마다 대학과 적용 학번(입학년도)이 다를 수 있다. 질문의 대학·학번에 맞는 근거만 쓰고, 다른 대학·다른 학번의 값을 섞지 않는다.
4. 숫자나 조건을 말할 때마다 근거 번호를 [1]처럼 붙인다.
5. 질문에 대학이나 학번이 없어 답이 갈리면 하나로 단정하지 말고, 갈리는 조건을 밝히거나 되묻는다.
6. 질문에 대한 답만 간결하게 한다.

출력 필드
- 답변: 사용자에게 보여 줄 답변 ([1] 같은 근거 번호 포함)
- 인용: 답변에 실제로 쓴 근거 번호 목록 (근거를 쓰지 않았으면 빈 목록)"""

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"답변": {"type": "string"}, "인용": {"type": "array", "items": {"type": "integer"}}},
    "required": ["답변", "인용"],
    "additionalProperties": False,
}

JUDGE_SYSTEM = """너는 대학 졸업요건 안내 챗봇의 답변을 채점하는 채점자다. [문항]의 기준으로 [챗봇 답변]을 판정하고, [인용한 근거]가 답변을 뒷받침하는지도 본다.

판정 규칙
- 정답: 핵심항목을 모두 말하고 오답신호가 없음. 부분: 핵심항목 일부만 말함, 또는 핵심은 맞지만 다른 대학·다른 학번의 값이나 조건이 섞임. 오답: 핵심항목이 틀리거나 오답신호를 정답처럼 말함.
- 오답신호에 적힌 값을 질문한 대상의 값으로 말하면 오답이다. 다른 대상의 값임을 분명히 구분해 말한 것은 오답신호로 보지 않는다.
- 질문 밖 정보: 정답과 모순되지 않으면 감점 없음, 모순되면 오답.
- 표현이 달라도 뜻이 같으면 맞은 것으로 본다. 숫자는 값과 단위가 같아야 한다.
- 채점유형이 "확인불가"인 문항: 해당 학번·내용을 확인할 수 없다고 답하고 그 학번의 값을 단정하지 않으면 정답. 숫자를 단정하면 오답. (참고로 다른 학번의 값을 구분해 덧붙이는 것은 감점 없음)
- 채점유형이 "되묻기"인 문항: 숫자를 단정하지 않고 대학·학번(·학과)을 되물으면 정답. 하나의 숫자로 단정하면 오답. 갈리는 경우를 구분해 알려 주기만 하고 되묻지 않으면 부분.
- 그 밖의 문항에서 챗봇이 "확인 불가"라고만 답하면 판정은 "확인불가"로 한다(오답과 구분).
- 판정이 정답이 아니면 틀린이유를 고른다: 학교 혼동(다른 대학의 값) / 학번 혼동(다른 학번·판의 값) / 구버전(옛 규정·옛 문구) / 지어냄(근거에 없는 값) / 기타. 확인불가 판정이면 빈 문자열.

인용일치 규칙 (챗봇이 인용한 근거 번호의 본문을 기준으로)
- 일치: 답변의 핵심 숫자·조건이 인용한 근거에 그대로 있음.
- 부분: 일부만 있거나, 근거가 그 숫자의 대상(대학·학번·학과)과 다름.
- 불일치: 인용한 근거에 그 내용이 없거나 모순됨.
- 미확인: 답변이 숫자·조건을 말하는데 인용이 하나도 없음.
- 해당없음: 답변이 확인 불가·되묻기여서 뒷받침할 내용이 없음."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["정답", "부분", "오답", "확인불가"]},
        "틀린이유": {"type": "string", "enum": ["", "학교 혼동", "학번 혼동", "구버전", "지어냄", "기타"]},
        "missing": {"type": "array", "items": {"type": "string"}},
        "contaminated": {"type": "array", "items": {"type": "string"}},
        "인용일치": {"type": "string", "enum": ["일치", "부분", "불일치", "미확인", "해당없음"]},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "틀린이유", "missing", "contaminated", "인용일치", "reason"],
    "additionalProperties": False,
}

UNANSWERABLE_RE = re.compile(r"확인\s*불가|확인\s*(할|될|되지|이)\s*(수\s*)?(없|않|어렵)|확인되지|알 수 없|근거(에|가)?\s*없")
NUM_RE = re.compile(r"\d+(?:\.\d+)?")


# ---------- 공통 ----------

def prompt_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def file_sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def log_usage(task, model, tin, tout, cost, memo):
    new = not USAGE_LOG.exists()
    with USAGE_LOG.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["시각", "작업", "모델", "입력 토큰", "출력 토큰", "비용(달러)", "메모"])
        if new:
            w.writeheader()
        w.writerow({"시각": datetime.now().isoformat(timespec="seconds"), "작업": task, "모델": model,
                    "입력 토큰": tin, "출력 토큰": tout, "비용(달러)": f"{cost:.5f}", "메모": memo})


def result_base(smoke):
    name = f"{date.today().isoformat()}_dev_base-rag_{MODEL}" + ("_smoke" if smoke else "")
    return RESULTS / name


def find_answer_file(smoke):
    pat = f"*_dev_base-rag_{MODEL}" + ("_smoke" if smoke else "") + ".csv"
    files = sorted(RESULTS.glob(pat))
    if not files:
        sys.exit(f"답변 파일이 없습니다: eval/results/{pat}")
    return files[-1]


class Chat:
    """chat.completions JSON 출력. temperature=0을 시도하고, 모델이 거부하면 기본값으로 다시 부른다."""

    def __init__(self, client):
        self.client = client
        self.temperature = 0

    def json(self, model, system, user, schema, name):
        kw = {"model": model,
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
              "response_format": {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}}
        if self.temperature is not None:
            kw["temperature"] = self.temperature
        try:
            res = self.client.chat.completions.create(**kw)
        except openai.BadRequestError as e:
            if self.temperature is None or "temperature" not in str(e).lower():
                raise
            self.temperature = None
            kw.pop("temperature")
            res = self.client.chat.completions.create(**kw)
        return json.loads(res.choices[0].message.content), res.usage.prompt_tokens, res.usage.completion_tokens


# ---------- 검색 ----------

def chunk_header(i, meta):
    s, e = meta["학번_시작"], meta["학번_끝"]
    if s == 0 and e == 9999:
        applies = "표기 없음"
    else:
        applies = f"{s or ''}~{'' if e == 9999 else e}학번" if s != e else f"{s}학번"
    edition = meta.get("판본", "")
    if meta.get("판본연도"):
        edition += f"({meta['판본연도']})"
    return (f"[{i}] {meta['대학']} / {meta['규정명']} / {meta['조항']} / PDF {meta['쪽_PDF']}쪽 / "
            f"판본 {edition or '표기 없음'} / 적용 학번 {applies}")


def student_numbers(cell):
    return [int(x) for x in re.findall(r"\d{4}", cell or "")]


def mixed_flags(row, metas):
    """검색 혼입: 질문의 대학과 다른 대학 청크, 질문의 학번이 적용 학번 구간에 없는 청크.
    대학이 '공통'이면 대학 판정 안 함, 학번이 비면 학번 판정 안 함, 청크에 적용 학번 구간이 없으면 학번 혼입으로 세지 않는다."""
    univ_on = row["대학"] != "공통"
    nums = student_numbers(row["학번"])
    out = {"대학대상": 0, "대학혼입": 0, "학번대상": 0, "학번혼입": 0, "합계대상": 0, "합계혼입": 0}
    for m in metas:
        u_mix = univ_on and m["대학"] != row["대학"]
        n_mix = False
        if nums:
            s, e = m["학번_시작"], m["학번_끝"]
            if not (s == 0 and e == 9999):
                n_mix = not any(s <= n <= e for n in nums)
        if univ_on:
            out["대학대상"] += 1
            out["대학혼입"] += u_mix
        if nums:
            out["학번대상"] += 1
            out["학번혼입"] += n_mix
        if univ_on or nums:
            out["합계대상"] += 1
            out["합계혼입"] += (u_mix or n_mix)
    return out


def norm(s):
    return re.sub(r"[\s\-·ㆍ.,()<>\[\]]", "", s.replace("학교", ""))


def hit_candidate(evidence, meta):
    """검색 적중 후보(자동): 근거 칸에 청크의 규정명과 조항 번호(제N조·별표 N)가 같이 나오면 Y. 최종은 사람이 본다."""
    ev = norm(evidence)
    if norm(meta["규정명"]) not in ev:
        return False
    art = re.match(r"\s*(제\d+조(?:의\d+)?|\(?별표\s*\d+|\(?별지\s*\d+)", meta["조항"])
    return bool(art) and norm(art.group(1).lstrip("(")) in ev


# ---------- answer ----------

def cmd_answer(args):
    sha = file_sha256(CHUNKS)
    if sha != CHUNKS_SHA256:
        sys.exit(f"chunks.jsonl sha256이 기록과 다릅니다 ({sha}). 색인이 낡았을 수 있어 중단합니다.")
    rows = load_csv(DEV_CSV)
    if args.limit:
        rows = rows[:args.limit]
    client = OpenAI()
    col = chromadb.PersistentClient(path=str(CHROMA_DIR)).get_collection(COLLECTION)
    print(f"컬렉션 {COLLECTION}: {col.count()}개, 질문 {len(rows)}개, k={K}")

    emb = client.embeddings.create(model=EMBED_MODEL, input=[r["질문"] for r in rows])
    q_vecs = [d.embedding for d in sorted(emb.data, key=lambda d: d.index)]
    emb_tokens = emb.usage.total_tokens

    chat = Chat(client)
    out, tin_sum, tout_sum = [], 0, 0
    for r, vec in zip(rows, q_vecs):
        hit = col.query(query_embeddings=[vec], n_results=K, include=["documents", "metadatas", "distances"])
        ids, docs, metas, dists = hit["ids"][0], hit["documents"][0], hit["metadatas"][0], hit["distances"][0]
        context = "\n\n".join(f"{chunk_header(i, m)}\n{d}" for i, (m, d) in enumerate(zip(metas, docs), 1))
        user = f"[근거]\n{context}\n\n[질문]\n{r['질문']}"
        ans, tin, tout = chat.json(MODEL, ANSWER_SYSTEM, user, ANSWER_SCHEMA, "answer")
        tin_sum += tin
        tout_sum += tout
        cited = [n for n in ans["인용"] if 1 <= n <= len(ids)]
        mix = mixed_flags(r, metas)
        out.append({
            "id": r["id"], "질문": r["질문"], "답변": ans["답변"],
            "인용": ";".join(map(str, cited)), "인용청크": ";".join(ids[n - 1] for n in cited),
            "검색청크": ";".join(ids), "검색거리": ";".join(f"{d:.3f}" for d in dists),
            "검색근거표시": " | ".join(f"{m['대학']} {m['규정명']} {m['조항'][:30]}" for m in metas),
            "적중후보": ";".join("Y" if hit_candidate(r["근거"], m) else "N" for m in metas),
            "혼입_대학": f"{mix['대학혼입']}/{mix['대학대상']}", "혼입_학번": f"{mix['학번혼입']}/{mix['학번대상']}",
            "혼입_합계": f"{mix['합계혼입']}/{mix['합계대상']}",
            "모델": MODEL, "프롬프트버전": PROMPT_VERSION, "프롬프트해시": prompt_hash(ANSWER_SYSTEM),
            "k": K, "컬렉션": COLLECTION, "chunks_sha256": sha,
            "온도": "0" if chat.temperature == 0 else "기본(temperature 거부)",
            "실행시각": datetime.now().isoformat(timespec="seconds"), "입력토큰": tin, "출력토큰": tout,
        })
        print(f"  {r['id']} 인용 {cited} 혼입 {mix['합계혼입']}/{mix['합계대상']}", flush=True)

    base = result_base(bool(args.limit))
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = base.with_suffix(".csv")
    write_csv(path, out, list(out[0]))
    cost = tin_sum / 1e6 * PRICE_IN + tout_sum / 1e6 * PRICE_OUT
    emb_cost = emb_tokens / 1e6 * EMBED_PRICE
    memo = f"기본 RAG 개발용 {len(rows)}문항, k={K}, {PROMPT_VERSION}" + (" (smoke)" if args.limit else "")
    log_usage("rag_answer", MODEL, tin_sum, tout_sum, cost, memo)
    log_usage("rag_query_embed", EMBED_MODEL, emb_tokens, 0, emb_cost, memo)
    print(f"저장: {path.relative_to(ROOT)}\n답변 토큰 {tin_sum:,}/{tout_sum:,} ${cost:.5f}, 질문 임베딩 {emb_tokens}토큰 ${emb_cost:.6f}")


# ---------- judge ----------

def floats(text):
    return {float(x) for x in NUM_RE.findall(text.replace(",", ""))}


def auto_flags(q, answer):
    key = floats(q["핵심항목"])
    ans = floats(answer)
    missing = sorted(k for k in key if k not in ans)
    wrong = sorted((floats(q["오답신호"]) - key) & ans)
    return {
        "자동_확인불가표현": "Y" if UNANSWERABLE_RE.search(answer) else "N",
        "자동_핵심숫자누락": ";".join(f"{x:g}" for x in missing),
        "자동_오답숫자포함": ";".join(f"{x:g}" for x in wrong),
    }


def attention(q, a, verdict):
    """판정관과 자동 표시가 어긋나는 문항: 사람이 먼저 본다."""
    notes = []
    if q["채점유형"] == "확인불가":
        if verdict == "정답" and a["자동_확인불가표현"] == "N":
            notes.append("확인불가 문항인데 확인 불가 표현 없이 정답 판정")
    elif verdict == "정답":
        if a["자동_확인불가표현"] == "Y":
            notes.append("확인 불가 표현이 있는데 정답 판정")
        if a["자동_핵심숫자누락"]:
            notes.append("핵심 숫자 누락인데 정답 판정")
        if a["자동_오답숫자포함"]:
            notes.append("오답신호 숫자가 있는데 정답 판정")
    return "; ".join(notes)


def cmd_judge(args):
    ans_path = find_answer_file(args.smoke)
    answers = load_csv(ans_path)
    dev = {r["id"]: r for r in load_csv(DEV_CSV)}
    all_chunks = {}
    wanted = {cid for a in answers for cid in a["인용청크"].split(";") if cid}
    for line in CHUNKS.open(encoding="utf-8"):
        c = json.loads(line)
        if c["id"] in wanted:
            all_chunks[c["id"]] = c

    chat = Chat(OpenAI())
    out, tin_sum, tout_sum = [], 0, 0
    for a in answers:
        q = dev[a["id"]]
        cited_txt = "\n\n".join(
            f"[인용 {i}] {all_chunks[cid]['대학']} / {all_chunks[cid]['규정명']} / {all_chunks[cid]['조항']}\n{all_chunks[cid]['text']}"
            for i, cid in enumerate([c for c in a["인용청크"].split(";") if c], 1)) or "(인용 없음)"
        user = (f"[문항]\n질문: {q['질문']}\n채점유형: {q['채점유형']}\n정답: {q['정답']}\n"
                f"핵심항목: {q['핵심항목']}\n오답신호: {q['오답신호'] or '(없음)'}\n\n"
                f"[챗봇 답변]\n{a['답변']}\n\n[인용한 근거]\n{cited_txt}")
        j, tin, tout = chat.json(JUDGE_MODEL, JUDGE_SYSTEM, user, JUDGE_SCHEMA, "judge")
        tin_sum += tin
        tout_sum += tout
        flags = auto_flags(q, a["답변"])
        out.append({
            "id": a["id"], "질문": a["질문"], "대학": q["대학"], "학번": q["학번"], "유형": q["유형"],
            "채점유형": q["채점유형"], "빈손여부": q["빈손여부"], "답변": a["답변"], "인용": a["인용"],
            "정답": q["정답"], "핵심항목": q["핵심항목"], "오답신호": q["오답신호"],
            "근거(평가셋)": q["근거"], "검색근거표시": a["검색근거표시"], "적중후보": a["적중후보"],
            **flags,
            "판정관_판정": j["verdict"], "판정관_틀린이유": j["틀린이유"], "판정관_인용일치": j["인용일치"],
            "판정관_누락": ";".join(j["missing"]), "판정관_섞임": ";".join(j["contaminated"]), "판정관_이유": j["reason"],
            "사람확인_우선": attention(q, flags, j["verdict"]),
            "최종판정": "", "최종틀린이유": "", "최종인용일치": "", "최종검색적중": "", "메모": "",
            "판정관모델": JUDGE_MODEL, "판정프롬프트버전": JUDGE_VERSION, "판정프롬프트해시": prompt_hash(JUDGE_SYSTEM),
            "판정온도": "0" if chat.temperature == 0 else "기본(temperature 거부)",
        })
        print(f"  {a['id']} {j['verdict']} 인용 {j['인용일치']}", flush=True)

    path = ans_path.with_name(ans_path.stem + "_grade-v1.csv")
    write_csv(path, out, list(out[0]))
    cost = tin_sum / 1e6 * PRICE_IN + tout_sum / 1e6 * PRICE_OUT
    log_usage("rag_judge", JUDGE_MODEL, tin_sum, tout_sum, cost, f"판정관 {JUDGE_VERSION}, {len(out)}문항" + (" (smoke)" if args.smoke else ""))
    print(f"저장: {path.relative_to(ROOT)}\n판정 토큰 {tin_sum:,}/{tout_sum:,} ${cost:.5f}")
    print(f"사람 확인 우선 {sum(1 for o in out if o['사람확인_우선'])}문항 (51문항 전부 최종 판정은 사람이 한다)")


# ---------- report ----------

def frac(n, d):
    return f"{n}/{d} ({n / d:.0%})" if d else "0/0"


def cmd_report(args):
    ans_path = find_answer_file(args.smoke)
    grade = load_csv(ans_path.with_name(ans_path.stem + "_grade-v1.csv"))
    answers = {a["id"]: a for a in load_csv(ans_path)}
    blank = [r for r in grade if not r["최종판정"].strip()]
    if blank and not args.allow_unfinished:
        sys.exit(f"최종판정이 비어 있는 문항 {len(blank)}개 ({', '.join(r['id'] for r in blank[:8])}…). 사람 판정을 채우세요.")
    rows = [r for r in grade if r["최종판정"].strip()]
    lines = [f"# 기본 RAG 개발용 채점 요약 ({ans_path.stem})", ""]
    first = next(iter(answers.values()))
    lines += [f"- 답변 모델 {first['모델']} · 프롬프트 {first['프롬프트버전']}({first['프롬프트해시']}) · k={first['k']} · 컬렉션 {first['컬렉션']}",
              f"- chunks.jsonl sha256 {first['chunks_sha256']}",
              f"- 판정관 {rows[0]['판정관모델']} · {rows[0]['판정프롬프트버전']}({rows[0]['판정프롬프트해시']}) · 사람 최종 판정 {len(rows)}문항", ""]

    def verdicts(group, title):
        c = Counter(r["최종판정"] for r in group)
        n = len(group)
        return (f"| {title} | {n} | {frac(c['정답'], n)} | {frac(c['정답'] + c['부분'], n)} | "
                f"{c['부분']} | {c['오답']} | {c['확인불가']} |")

    head = "| 구분 | 문항 | 정답 | 정답+부분 | 부분 | 오답 | 확인불가 |\n|---|---|---|---|---|---|---|"
    lines += ["## 정답률", head, verdicts(rows, "전체")]
    bl = [r for r in rows if r["빈손여부"] == "Y"]
    lines += [verdicts(bl, "빈손 문항"), verdicts([r for r in bl if r["id"] != "B09"], "빈손 문항 (B09 제외)")]
    lines += ["", "빈손 비교 기준: luna 끔 20%(3/15) · luna 켬 67%(10/15) · ChatGPT 켬 27%(4/15) / B09 제외 14문항 14%·71%·29%", ""]
    for key, title in (("대학", "대학별"), ("유형", "유형별"), ("채점유형", "채점유형별")):
        lines += [f"## {title}", head]
        groups = defaultdict(list)
        for r in rows:
            groups[r[key]].append(r)
        lines += [verdicts(g, k) for k, g in sorted(groups.items())]
        lines.append("")

    unans = [r for r in rows if r["채점유형"] == "확인불가"]
    lines += ["## 지표",
              f"- 확인 불가 처리율 (확인불가 문항에서 정답): {frac(sum(r['최종판정'] == '정답' for r in unans), len(unans))}"]
    cit = [r for r in rows if r["최종인용일치"] in ("일치", "부분", "불일치", "미확인")]
    cc = Counter(r["최종인용일치"] for r in cit)
    lines.append(f"- 인용일치율 (해당없음 제외): 일치 {frac(cc['일치'], len(cit))} · 부분 {cc['부분']} · 불일치 {cc['불일치']} · 미확인 {cc['미확인']}")
    confuse = [r for r in rows if r["최종판정"] != "정답" and re.search("학교 혼동|학번 혼동", r["최종틀린이유"])]
    lines.append(f"- 답변 혼동률 (학교·학번 혼동으로 틀린 문항 / 전체): {frac(len(confuse), len(rows))}")
    sums = defaultdict(lambda: [0, 0])
    for r in rows:
        a = answers[r["id"]]
        for key in ("대학", "학번", "합계"):
            m, d = map(int, a[f"혼입_{key}"].split("/"))
            sums[key][0] += m
            sums[key][1] += d
    lines.append("- 검색 혼입률 (top-5 청크 중 다른 대학·다른 학번 판): "
                 + " · ".join(f"{k} {frac(*sums[k])}" for k in ("합계", "대학", "학번")))
    hit = [r for r in rows if r["최종검색적중"] in ("Y", "N")]
    lines.append(f"- 검색 적중률 (근거 청크가 top-5에 있음, 불명 제외): {frac(sum(r['최종검색적중'] == 'Y' for r in hit), len(hit))}")
    cand = [any(x == "Y" for x in answers[r["id"]]["적중후보"].split(";")) for r in rows if r["채점유형"] != "확인불가" and r["채점유형"] != "되묻기"]
    lines.append(f"- (참고) 자동 적중 후보: {frac(sum(cand), len(cand))} (확인불가·되묻기 제외, 규정명+조항 문자열 일치, 사람 확인 전 수치)")
    agree = sum(r["판정관_판정"] == r["최종판정"] for r in rows)
    lines.append(f"- 판정관-사람 판정 일치: {frac(agree, len(rows))}")
    reasons = Counter(x.strip() for r in rows if r["최종판정"] != "정답" for x in re.split(r"[;,]", r["최종틀린이유"]) if x.strip())
    lines += ["", "## 틀린 이유 집계 (정답 아닌 문항, 복수 가능)", "| 이유 | 건수 |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in reasons.most_common()]
    text = "\n".join(lines) + "\n"
    out = ans_path.with_name(ans_path.stem + "_report.md")
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"저장: {out.relative_to(ROOT)}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(ROOT / ".env")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("answer")
    a.add_argument("--limit", type=int, default=0, help="앞에서 N문항만 (시험용, 파일명에 _smoke)")
    j = sub.add_parser("judge")
    j.add_argument("--smoke", action="store_true")
    r = sub.add_parser("report")
    r.add_argument("--smoke", action="store_true")
    r.add_argument("--allow-unfinished", action="store_true", help="최종판정이 빈 문항을 빼고 계산")
    args = p.parse_args()
    {"answer": cmd_answer, "judge": cmd_judge, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
