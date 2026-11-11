"""7단계 점검 (API 비용 0). 8단계 코드 동결 확인에도 쓴다.

    python src/check_service.py            # equiv + logic 모두
    python src/check_service.py equiv      # 파이프라인 동치: 개발용 51문항의 경로·검색 청크/조회 행 ID·검색 거리·필터·확장 질문·LLM에 보낸 프롬프트 해시·진행 로그가
                                           #   기준 스냅샷(eval/pipeline_snapshot.json)과 같은가
    python src/check_service.py equiv --write-baseline   # 의도한 변경 뒤 기준 스냅샷을 다시 쓴다(추출 전 코드의 스냅샷으로 처음 만들었다)
    python src/check_service.py logic      # 사이드바 우선 규칙, 영역별 계획(T1·T2·T3), 체크리스트, 학사 선택 비교, 출처 줄 분리, 편입 안내·체크리스트 안내 규칙
    python src/check_service.py citations  # 답 속 [n]이 모두 카드 번호 중에 있는지(실제 답변 전체)
    python src/check_service.py app        # 화면 스모크(streamlit AppTest, 가짜 엔진, 임시 로그 DB)

equiv는 OpenAI 임베딩을 질문 해시로 만든 고정 벡터로, LLM을 프롬프트 해시만 기록하는 가짜로 바꿔 run_rag.cmd_answer를 그대로 실행한다
(임베딩 API 잡음이 없고 비용이 0이다). 답변 문장·토큰·실행 시각은 비교하지 않는다. 결과 CSV·사용 로그는 쓰지 않는다.
"""

import argparse
import builtins
import hashlib
import json
import random
import re
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import courses as CR  # noqa: E402
import criteria_calc  # noqa: E402
import criteria_lookup as L  # noqa: E402
import engine  # noqa: E402
import query_filter as QF  # noqa: E402
import run_rag as R  # noqa: E402
import service_calc as S  # noqa: E402

BASELINE = ROOT / "eval" / "pipeline_snapshot.json"
RESULTS = []
SKIPS = []  # 자료 파일이 없어 건너뛴 점검(요약에 개수를 따로 표시, 8단계 동결 전에는 0개여야 한다)


def skip(msg):
    SKIPS.append(msg)
    print("SKIP " + msg)


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


# ---------- 파이프라인 동치 ----------

def _fake_vec(text, dim=1536):
    rnd = random.Random(int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16))
    v = [rnd.gauss(0, 1) for _ in range(dim)]
    n = sum(x * x for x in v) ** 0.5
    return [x / n for x in v]


def snapshot():
    captured, calls = {}, []

    class FakeEmb:
        def create(self, model, input):
            return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=_fake_vec(t)) for i, t in enumerate(input)],
                                   usage=SimpleNamespace(total_tokens=0))

    class FakeOpenAI:
        def __init__(self, *a, **k):
            self.embeddings = FakeEmb()

    def sha(s):
        return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]

    def fake_json(self, model, system, user, schema, name):
        calls.append({"name": name, "model": model, "system": sha(system), "user": sha(user), "user_len": len(user)})
        return {"답변": "stub", "인용": [1]}, 0, 0

    saved = (R.OpenAI, R.Chat.json, R.write_csv, R.log_usage, builtins.print)
    R.OpenAI, R.Chat.json = FakeOpenAI, fake_json
    R.write_csv = lambda path, rows, fields: captured.__setitem__("rows", rows)
    R.log_usage = lambda *a, **k: None
    log_lines = []
    builtins.print = lambda *a, **k: log_lines.append(" ".join(str(x) for x in a))
    args = argparse.Namespace(chunks="", collection="", filter=True, expand=True, lookup=True, lookup_prompt="v3", calc=True, prompt="v2",
                              ids="", limit=0, tag="snapcheck")
    try:
        R.cmd_answer(args)
    finally:
        R.OpenAI, R.Chat.json, R.write_csv, R.log_usage, builtins.print = saved
    skip = {"답변", "실행시각", "입력토큰", "출력토큰", "온도"}
    rows = []
    for i, row in enumerate(captured["rows"]):
        rec = {k: v for k, v in row.items() if k not in skip}
        rec["llm_call"] = calls[i]
        rows.append(rec)
    assert len(rows) == len(calls)
    return json.loads(json.dumps({"rows": rows, "log_lines": log_lines}, ensure_ascii=False, sort_keys=True))


def snapshot_fresh_process():
    import subprocess
    out = subprocess.run([sys.executable, "-X", "utf8", "-I", str(Path(__file__).resolve()), "_snapshot"], capture_output=True, text=True,
                         encoding="utf-8", check=True).stdout
    return json.loads(out.strip().splitlines()[-1])


MAX_TRIES = 5  # 새 프로세스 재시도 최대 횟수(첫 시도에서 B01이 흔들리는 일이 잦았다: 6번 중 5번)
TIE_TOL = 0.005 # 마지막 순위 거리 차이 허용치. B01에서 실제로 잰 차이는 0.004(0.985↔0.981)라 0.002로는 이 흔들림이 통과하지 못한다
DERIVED = {"검색청크", "검색거리", "검색근거표시", "llm_call"}  # 검색 결과가 바뀌면 따라 바뀌는 열


def _tail_noise(o, c):
    """o(기준)·c(이번) 행의 차이가 '마지막 순위 청크 1개 + 거리 차이 작음'뿐이면 True"""
    if not str(o.get("컬렉션", "")).startswith("base-") or o.get("컬렉션") != c.get("컬렉션"):
        return False  # RAG가 아니거나 경로가 바뀐 문항은 흔들림이 아니라 진짜 변경이다
    a, b = o["검색청크"].split(";"), c["검색청크"].split(";")
    da, db = [float(x) for x in o["검색거리"].split(";")], [float(x) for x in c["검색거리"].split(";")]
    if len(a) != len(b) or len(a) < 4 or set(a) == set(b):
        return False
    gone, came = set(a) - set(b), set(b) - set(a)
    if len(gone) != 1 or len(came) != 1 or a[:len(a) - 2] != b[:len(b) - 2]:
        return False
    if a[-1] not in gone and b[-1] not in came:
        return False
    if abs(da[-1] - db[-1]) > TIE_TOL:
        return False
    keys = {k for k in set(o) | set(c) if o.get(k) != c.get(k)}
    lo, lc = o["llm_call"], c["llm_call"]
    return keys <= DERIVED and all(lo[k] == lc[k] for k in ("name", "model", "system"))


def diff_rows(old, cur):
    """(허용 밖 불일치 목록, 마지막 순위 흔들림 문항 ID 목록)"""
    hard, soft = [], []
    if list(old) != list(cur):
        hard.append(("문항 목록", ""))
    for i in old:
        if i not in cur:
            continue
        keys = sorted(k for k in set(old[i]) | set(cur[i]) if old[i].get(k) != cur[i].get(k))
        if not keys:
            continue
        if _tail_noise(old[i], cur[i]):
            soft.append(i)
        else:
            hard.extend((i, k) for k in keys)
    return hard, soft


def _norm_log(lines):
    """진행 로그에서 실행 날짜(저장 파일명의 YYYY-MM-DD)를 지우고 비교한다. 날짜가 들어 있으면 날이 바뀔 때마다 동치 점검이 실패한다(2026-11-10 발견)"""
    return [re.sub(r"\d{4}-\d{2}-\d{2}", "<날짜>", l) for l in lines]


def cmd_equiv(write_baseline=False):
    snap = snapshot()
    routes = {}
    for r in snap["rows"]:
        routes[r["컬렉션"]] = routes.get(r["컬렉션"], 0) + 1
    if write_baseline:
        BASELINE.write_text(json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"기준 스냅샷 저장: {BASELINE.relative_to(ROOT)} (문항 {len(snap['rows'])}, 경로 {routes})")
        return
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    old = {r["id"]: r for r in base["rows"]}
    # Chroma의 근사 검색(HNSW)은 거리가 거의 같은 마지막 순위 후보에서 실행마다 가끔 바뀐다(같은 코드로 실패·통과가 섞여 나옴, B01 5위).
    # 재시도는 그 경우에만 허용한다: RAG 문항에서 검색 청크가 정확히 1개만 바뀌고(앞 순위 3개는 그대로, 빠진 청크가 기준 또는 이번의 5위),
    # 마지막 순위 거리 차이가 TIE_TOL 이하이며, 바뀐 열이 검색 결과에서 파생되는 열뿐일 때. 그 밖의 불일치는 바로 실패한다.
    attempts, noisy, hard = 0, {}, []
    for attempts in range(1, MAX_TRIES + 1):
        cur = {r["id"]: r for r in snap["rows"]}
        hard, soft = diff_rows(old, cur)
        if not hard and not soft and _norm_log(snap["log_lines"]) == _norm_log(base["log_lines"]):
            break
        if hard or (not soft):  # 허용 밖 불일치(또는 행은 같은데 진행 로그만 다름)는 재시도하지 않는다
            hard = hard or [("진행 로그", "")]
            break
        noisy.update({i: attempts for i in soft})
        if attempts < MAX_TRIES:
            # 같은 프로세스 안에서 다시 돌리면 같은 결과가 나온다(관찰: 한 프로세스에서 3번 모두 B01 동일). 새 프로세스로 돌린다.
            print(f"  (시도 {attempts}: {sorted(soft)}만 마지막 순위 청크가 달라요(HNSW 동점 근처) → 새 프로세스로 다시 돌립니다)")
            snap = snapshot_fresh_process()
    else:
        hard = hard or [(f"{MAX_TRIES}번 모두 마지막 순위 흔들림", "")]
    ok = not hard
    note = f" · {attempts}번째 시도에 통과(마지막 순위가 흔들린 문항 {sorted(noisy)})" if ok and attempts > 1 else ""
    check(f"파이프라인 동치: 문항 {len(old)}개 · 경로 {routes}" + note, ok, f"불일치 {hard[:5]}")
    hashes = {"answer-v1": R.prompt_hash(R.ANSWER_SYSTEM), "answer-v2": R.prompt_hash(R.ANSWER_SYSTEM_V2), "lookup-v1": R.prompt_hash(R.LOOKUP_SYSTEM),
              "lookup-v2": R.prompt_hash(R.LOOKUP_SYSTEM_V2), "lookup-v3": R.prompt_hash(R.LOOKUP_SYSTEM_V3), "calc-v1": R.prompt_hash(R.CALC_SYSTEM), "judge-v2": R.prompt_hash(R.JUDGE_SYSTEM)}
    expected = {"answer-v1": "151fc2fa1a4b", "answer-v2": "95af4a805902", "lookup-v1": "aa2dd09cd98b", "lookup-v2": "2085142f4358", "lookup-v3": "93e8bf1da70f",
                "calc-v1": "fa46be364a36", "judge-v2": "f06259a59823"}
    check("프롬프트 해시 7종 불변", hashes == expected, str(hashes))


# ---------- 서비스 로직 ----------

def cmd_logic():
    # 0. E31 [1] 배지 종류, [3] 평점 질문 경로(점수 불변 변경: 개발용 51문항 경로는 equiv로 따로 확인)
    k = engine.unanswerable_kind
    check("E31 [1]: 핵심 답이 앞에 있고 확인 불가가 뒤 문장이면 '일부확인불가'(휴학 사례)",
          k("일반휴학은 최대 1년 단위로 신청하고 통산 10년을 넘을 수 없습니다[1]. 규정에 최대 학기 수는 없어 학기 수로는 확인 불가입니다.") == "일부확인불가")
    check("E31 [1]: 첫 문장이 확인 불가이거나 인용이 없으면 강한 '확인불가', 표현이 없으면 배지 없음",
          k("장학금 평점은 확인 불가입니다. 조회된 행은 졸업 기준입니다. [1]") == "확인불가" and k("확인 불가입니다.") == "확인불가" and k("면제입니다 [1].") is None and k("60학점이에요 확인 불가한 부분은 없어요") == "확인불가")
    ifor = L.items_for
    check("E31 [3]: 장학금·학사경고·조기졸업 평점 질문은 졸업 평점 조회로 가지 않는다(RAG)",
          ifor("장학금 받으려면 평점 몇 이상이야?") is None and ifor("학사경고 평점 몇 점 이하야?") is None and ifor("조기졸업 평점 몇 이상이야?") is None)
    check("E31 [3]: 졸업 평점 질문은 그대로 조회(dev T08·C06 문장 포함)",
          ifor("졸업 평점 몇 이상이야?") == ["평점_최저"] and ifor("충남대는 졸업하려면 평점이 몇 점 이상이어야 해?") == ["평점_최저"] and ifor("한밭대도 졸업하려면 평점이 2.00 이상이어야 해?") == ["평점_최저"])
    check("E31 [3] 보강: 평점이 있어도 신청 학점을 묻는 질문은 수강상한 조회", ifor("평점 4.3이면 몇 학점까지 신청돼?") == ["수강상한_학기"])
    # 1. 사이드바 값은 질문에 없을 때만 붙인다 (질문 우선)
    q = "부전공은 몇 학점이야?"
    w, p, used = engine.build_question(q, "한남", 2023, "경영정보학과")
    check("사이드바: 질문에 아무것도 없으면 대학·학번·학과를 모두 붙인다", w == "한남대 2023학번 경영정보학과 학생: " + q and used and p == "한남대 2023학번 학생: " + q, w)
    w, p, used = engine.build_question("충남대 부전공은 몇 학점이야?", "한남", 2023, "경영정보학과")
    check("사이드바 한남 + 질문 '충남대': 대학이 하나(충남)로 남고 학과는 붙이지 않는다",
          QF.extract_universities(w) == ["충남"] and QF.extract_universities(p) == ["충남"] and not used and "경영정보학과" not in w, w)
    w, p, used = engine.build_question("2024학번은 부전공 몇 학점이야?", "한남", 2023, "경영정보학과")
    check("질문에 학번이 있으면 사이드바 학번을 붙이지 않는다", QF.extract_years(w) == [2024] and "2023학번" not in w, w)
    w, p, used = engine.build_question("경영학부는 졸업학점이 몇 학점이야?", "충남", 2025, "경영학부")
    check("질문에 학과가 있으면 사이드바 학과를 붙이지 않는다", not used and w.count("경영학부") == 1, w)
    w, p, used = engine.build_question(q, "한남", None, None)
    check("학번·학과를 안 고르면 대학만 붙는다", w == "한남대 학생: " + q and not used, w)
    w, p, used = engine.build_question(q, "한남", engine.OUT_OF_RANGE, None)
    check("학번 '범위 밖' 선택은 질문에 학번을 붙이지 않는다(엔진이 확인 불가로 답한다)", "학번" not in w, w)
    w, p, used = engine.build_question("한남대 2023학번 경영정보학과는 부전공 몇 학점이야?", "한남", 2023, "경영정보학과")
    check("질문에 대학·학번·학과가 다 있으면 질문 그대로", w == "한남대 2023학번 경영정보학과는 부전공 몇 학점이야?" and not used, w)
    # 학과를 붙였을 때 계산·조회가 열리면 그 문장을, 안 열리면 학과 없는 문장을 쓴다
    q1, used1 = engine.choose_question("졸업학점은 몇 학점이야?", "목원", 2022, "경영학부")
    check("학과를 붙여야 열리는 질문(목원 경영학부 졸업학점)은 학과를 붙인 문장을 쓴다", used1 and engine.routable(q1), q1)
    rows_of2 = lambda q: sorted({r["행ID"] for rs in (L.lookup(q)[0] or {}).values() for r in rs})
    q2, used2 = engine.choose_question("부전공은 몇 학점이야?", "한남", 2023, "경영정보학과")
    check("학과를 붙인 문장도 조회로 열리고 학과 없는 문장과 같은 행(E27 규칙 1 뒤: 한남 부전공)", engine.routable(q2) and rows_of2(q2) == rows_of2("한남대 2023학번 학생: 부전공은 몇 학점이야?"), q2)
    # 1-1. 회귀 사례(E12, 서비스 시험 중 발견한 조회 규칙 버그. 평가셋에는 넣지 않았다)
    def rows_of(q):
        res = L.lookup(q)[0]
        return None if res is None else sorted({r["행ID"] for rs in res.values() for r in rs})
    q, used = engine.choose_question("재수강은 어떤 조건에서 할 수 있어?", "충남", 2024, "경영학부")
    check("회귀 E12-1: 충남 2024 재수강 질문은 수강상한 조회로 가지 않고 RAG로 간다", rows_of(q) is None and not engine.routable(q), q)
    check("회귀 E12-1: 재이수도 마찬가지", rows_of("충남대 2024학번 학생: 재이수는 몇 번 할 수 있어?") is None)
    check("회귀 E12-1: 수강상한 질문은 그대로 조회(한 학기 최대 몇 학점 → CN-077·078)",
          rows_of("충남대 2024학번 학생: 한 학기에 최대 몇 학점 들을 수 있어?") == ["CN-077", "CN-078"])
    q, used = engine.choose_question("수강신청은 언제부터 할 수 있어?", "충남", 2024, "경영학부")
    check("회귀 E12-3: 충남 2024 수강신청 일정 질문은 수강상한 조회로 가지 않고 RAG로 간다(학점·상한 단서 없음)", rows_of(q) is None and not engine.routable(q), q)
    check("회귀 E12-3: 학점 단서가 있으면 수강신청도 수강상한 조회(한 학기에 몇 학점 수강신청할 수 있어 → CN-077·078)",
          rows_of("충남대 2024학번 학생: 한 학기에 몇 학점 수강신청할 수 있어?") == ["CN-077", "CN-078"])
    q, used = engine.choose_question("복수전공은 몇 학점 이수해야 해?", "충남", 2024, "경영학부")
    check("회귀 E12-2: 충남 2024 경영학부 복수전공은 조회로 간다(주전공 학점 CN-070 학과 행 + 이수학점 CN-067 전체 행)",
          used and rows_of(q) == ["CN-067", "CN-070"], f"{used} {rows_of(q)}")
    check("회귀 E12-2: 2026학번은 이수학점도 학과 행(CN-071·070)", rows_of("충남대 2026학번 경영학부 학생: 복수전공은 몇 학점 이수해야 해?") == ["CN-070", "CN-071"])
    check("회귀 E12-2: 학과 행이 묶음 어디에도 없으면 여전히 RAG(간호학과 복수전공)", rows_of("충남대 2024학번 간호학과 학생: 복수전공은 몇 학점 이수해야 해?") is None)
    check("회귀 E12-2: 학과를 고르지 않으면 주전공 학점 행이 학과 한정이라 RAG(묶음 불완전)", rows_of("충남대 2024학번 학생: 복수전공은 몇 학점 이수해야 해?") is None)
    # 1-1b. 회귀 사례(E13, 서비스 시험 중 발견한 조회 항목 빈틈)
    q, used = engine.choose_question("비교과 몇 시간 들어야 돼?", "한밭", 2024, "융합경영학과")
    check("회귀 E13-1: 한밭 2024 비교과 질문은 조회로 간다(HB-021 70유닛·HB-022 35유닛)", engine.routable(q) and rows_of(q) == ["HB-021", "HB-022"], f"{q} {rows_of(q)}")
    check("회귀 E13-1: 목원 2022 비교과는 MW-064(20시간, 편입·재입학 제외)",
          rows_of("목원대 2022학번 학생: 비교과는 몇 시간 이수해야 해?") == ["MW-064"], str(rows_of("목원대 2022학번 학생: 비교과는 몇 시간 이수해야 해?")))
    check("회귀 E13-1: 수치 의도 없는 비교과 질문(신청 방법)은 여전히 RAG", rows_of("목원대 2022학번 학생: 비교과 프로그램은 어떻게 신청해?") is None)
    check("회귀 E13-1: '비교'는 여전히 계산·비교로 RAG(비교과가 아닌 비교 질문)", rows_of("한밭대 2024학번 학생: 졸업학점이랑 평점 중에 비교해 줘") is None)
    # 1-1c. 회귀 사례(E16, 서비스 점검 #7): 학과 한정 주전공 학점 행 + 대학 전체 이수학점 행인 대학도 계산 경로로 가고, 결과가 학사 선택 비교 탭(S.compare)과 같다
    for u, y, d, want in (("배재", 2023, "IT경영정보학과", [72.0, 75.0]), ("배재", 2025, "IT경영정보학과", [78.0, 96.0]), ("충남", 2024, "경영학부", [78.0, 78.0])):
        q, used = engine.choose_question("부전공이랑 다전공 중 뭐가 전공학점이 적어?", u, y, d)
        res = criteria_calc.calc(q)[0]
        cmp_ = S.compare(u, y, d)
        got = list(res["values"].values()) if res else None
        check(f"회귀 E16: {u} {y} 부전공↔다전공 질문 경로(계산) 결과 {want} = S.compare 결과", res is not None and got == want == [t["total"] for t in cmp_["table"]] and used, f"{q} {got}")
    check("회귀 E16: 학과를 안 적은 배재 질문(주전공 학점이 학과 한정 행뿐)은 여전히 RAG로 폴백(P04와 같음)",
          criteria_calc.calc("배재대 2024학번은 부전공이랑 다전공 중에 전공학점이 더 적게 드는 건 뭐야?")[0] is None)
    # 1-1d. 회귀 사례(E20 데이터 보완, 한밭 융합경영학과 주전공 요구 학점 HB-023·024 잠정)
    for y in (2022, 2024, 2026):
        q, used = engine.choose_question("부전공이랑 복수전공 중 뭐가 전공학점이 적어?", "한밭", y, "융합경영학과")
        res = criteria_calc.calc(q)[0]
        cmp_ = S.compare("한밭", y, "융합경영학과")
        got = list(res["values"].values()) if res else None
        check(f"회귀 E20: 한밭 {y} 융합경영학과 부전공↔복수전공 계산 [57, 72] = S.compare, 최저값 안내가 붙음",
              res is not None and got == [57.0, 72.0] == [t["total"] for t in cmp_["table"]] and "최저값" in cmp_["floor_note"], f"{q} {got} {cmp_.get('floor_note')}")
    check("회귀 E20: 한밭 복수전공 몇 학점은 조회(HB-011 이수학점 + HB-023 주전공 학점)",
          sorted(rows_of("한밭대 2024학번 융합경영학과 학생: 복수전공은 몇 학점 이수해야 해?") or []) == ["HB-011", "HB-023"])
    check("회귀 E20: 학과를 안 적은 한밭 복수전공 질문은 주전공 행이 학과 한정이라 여전히 RAG",
          rows_of("한밭대 2024학번 학생: 복수전공은 몇 학점 이수해야 해?") is None)
    check("회귀 E20: 범위 값이 없는 대학(목원)은 최저값 안내가 붙지 않음", not S.compare("목원", 2023, "경영학부").get("floor_note"))
    # 1-1f. 회귀 사례(E22b, 서비스 점검 #17): 학과 이름 매칭은 글자 경계 규칙(target_mentioned). 옛 규칙은 '교육'이 '기계금속공학교육과' 안에 걸렸다
    G = "학생: 졸업하려면 총 몇 학점이 필요해?"
    for u_dept, want in (("기계금속공학교육과", ["CN-008"]), ("국어교육과", ["CN-002"]), ("교육학과", ["CN-004"]), ("수의학과", ["CN-016"]), ("의학과", ["CN-015"])):
        check(f"회귀 E22b: 충남 2022 {u_dept} 졸업학점은 {want}만(다른 학과 행이 같이 걸리지 않음)", rows_of(f"충남대 2022학번 {u_dept} {G}") == want, str(rows_of(f"충남대 2022학번 {u_dept} {G}")))
    r_ = rows_of("충남대 2022학번 경영학부 학생: 졸업학칙의 졸업학점 몇 학점이야?") or []
    check("회귀 E22b: 질문 속 '의' 한 글자가 의학과(CN-015)에 걸리지 않는다(경영학부 CN-020~022만)", r_ == ["CN-020", "CN-021", "CN-022"], str(r_))
    check("회귀 E22b: '전공'이라는 단어가 대상 '건축학 전공(5년제)'(CN-012)에 걸리지 않고, '교육과정'이 교육학과(CN-004)에 걸리지 않는다(대학 전체 행 CN-001)",
          rows_of("충남대 2022학번 학생: 전공 졸업학점 몇 학점이야?") == ["CN-001"] and rows_of("충남대 2022학번 학생: 교육과정은 졸업하려면 몇 학점이야?") == ["CN-001"])
    check("회귀 E22b: 한남 '간호학과' 언급은 간호학과 행(HN-007)만, 이학·공학·예능·체능·간호 '계열' 행(HN-002)에는 안 걸림",
          rows_of("한남대 2023학번 간호학과 학생: 졸업하려면 몇 학점이야?") == ["HN-007"])
    check("회귀 E22b: 반대로 '간호계열'·'이학계열' 언급은 계열 행(HN-002)에 걸리고, 계열이라는 말 없는 '공학'만으로는 안 걸림",
          rows_of("한남대 2023학번 학생: 간호계열은 졸업하려면 몇 학점이야?") == ["HN-002"] and rows_of("한남대 2023학번 학생: 이학계열은 졸업하려면 몇 학점이야?") == ["HN-002"]
          and rows_of("한남대 2023학번 학생: 공학은 졸업하려면 몇 학점이야?") is None)
    check("회귀 E22b: 조사가 붙어도 걸린다(간호학과는·사범대학은·건축학(5년제)은), 괄호 속 말은 무시",
          L.target_mentioned("간호학과", "배재대 간호학과는 몇 학점?") and L.target_mentioned("사범대학", "한남대 사범대학은 몇 학점?") and L.target_mentioned("건축학 전공(5년제)", "충남대 건축학은 몇 학점?")
          and not L.target_mentioned("교육학과", "기계금속공학교육과") and not L.target_mentioned("약학과", "요약해 줘") and not L.target_mentioned("및", "복수전공 및 부전공"))
    # 1-1g. E23 배재 별지3 묶음 행(대상에 학과를 쉼표로 나열): 학과별 영역 기준·이수 방식·중복 없음
    def pl(d, y):
        p_ = S.area_plan("배재", d, y)
        a_ = {x["name"]: x["min"] for x in p_["areas"]}
        return p_["tier"], p_["method"], (p_["grad"] or {}).get("값"), a_.get("교양"), a_.get("전공"), a_.get("공유혁신")
    targets = S.grad_targets("배재")
    check("E23: 배재 '그 외 학과' 선택지에 별지3 학과가 나열된다(경영학과·생명공학과·글로벌자율융합학부·자율전공학부 포함, 40개 이상)",
          all(d in targets for d in ("경영학과", "생명공학과", "글로벌자율융합학부", "자율전공학부", "간호학과", "건축학과(5년제)", "평생교육융합학부")) and len(targets) >= 40, str(len(targets)))
    check("E23: 간호 2022 변경 전 규정 T1 140 = 교양 30 + 전공 110(주석 단), 간호 2023 T1 134 = 30 + 104, 건축 2024 T1 161 = 30 + 131",
          pl("간호학과", 2022) == ("T1", "단수", "140", 30.0, 110.0, None) and pl("간호학과", 2023) == ("T1", "단수", "134", 30.0, 104.0, None) and pl("건축학과(5년제)", 2024) == ("T1", "단수", "161", 30.0, 131.0, None))
    check("E23: 경영학과 2023 교양 36·전공 66, 2025 융합과정 교양 28·전공 60·공유혁신 13 (IT경영정보학과 기존 행과 같은 값)",
          pl("경영학과", 2023)[1:] == ("단수", "130", 36.0, 66.0, None) and pl("경영학과", 2025)[1:] == ("융합과정", "127", 28.0, 60.0, 13.0) and pl(S.BASE_DEPT["배재"], 2025)[1:] == ("융합과정", "127", 28.0, 60.0, 13.0))
    check("E23: 공유혁신 없는 2025~ 학과는 단수 이수유형(간호 28·104, 유아 28·66, 글로벌자율 20·66, 평생 14·60), 공유혁신 영역 없음",
          pl("간호학과", 2025)[1:] == ("단수", "134", 28.0, 104.0, None) and pl("유아교육과", 2025)[1:] == ("단수", "127", 28.0, 66.0, None)
          and pl("글로벌자율융합학부", 2025)[1:] == ("단수", "127", 20.0, 66.0, None) and pl("평생교육융합학부", 2025)[1:] == ("단수", "110", 14.0, 60.0, None))
    check("E23: 전공 묶음 값(생명공학 2024 78·2025 72, 전자공학 2023 78, 전기공학 2023 66, 외식조리 2025 전공 60, 실내건축 2025 72, 글로벌자율 2022 교양 25)",
          pl("생명공학과", 2024)[4] == 78.0 and pl("생명공학과", 2025)[4] == 72.0 and pl("전자공학과", 2023)[4] == 78.0 and pl("전기공학과", 2023)[4] == 66.0
          and pl("외식조리학과", 2025)[4] == 60.0 and pl("실내건축학과", 2025)[4] == 72.0 and pl("글로벌자율융합학부", 2022)[3] == 25.0)
    check("E23: 별지3 표에 없는 연도의 학과(2025 중국통상학과·2022 자율전공학부)는 영역별 기준 없이 총 졸업학점까지(T0)", pl("중국통상학과", 2025)[0] == "T0" and pl("자율전공학부", 2022)[0] == "T0" and pl("중국통상학과", 2025)[2] == "127")
    check("E23: 자율전공학부 2025는 공유혁신 소계 '-'라 공유혁신 영역이 없고 전공 60, 병합 이어짐 학과(레저스포츠학부·뷰티케어)·자율전공은 잠정",
          pl("자율전공학부", 2025)[4:] == (60.0, None) and all(r["상태"] == "잠정" for r in L.CRITERIA if r["대학"] == "배재" and r["항목"] == "전공" and r["입학년도_시작"] == "2025" and r["대상"] in ("자율전공학부", "레저스포츠학부,뷰티케어학과")))
    seen_ = {}
    dup_ = []
    for r_ in L.CRITERIA:
        if r_["대학"] == "배재" and r_["기준값여부"] == "기준" and r_["대상"] not in ("", "전체"):
            for y_ in range(int(r_["입학년도_시작"] or 2022), int(r_["입학년도_끝"] or 2028) + 1):
                for d_ in L.targets_of(r_):
                    k_ = (d_, y_, r_["이수유형"], r_["항목"], r_["구분"], r_["조건"])
                    if k_ in seen_:
                        dup_.append((k_, seen_[k_], r_["행ID"]))
                    seen_[k_] = r_["행ID"]
    check("E23: 배재 학과 행은 (학과·학번·이수유형·항목) 중복이 없다(묶음 행 펼친 뒤)", not dup_, str(dup_[:3]))
    cmp_ = S.compare("배재", 2023, "경영학과")
    check("E23: 경영학과 2023 부전공↔다전공 비교 72 vs 75(묶음 행, IT경영정보학과와 같음), 간호·건축은 주전공 학점 없음(학과 확인)",
          [t["total"] for t in cmp_["table"]] == [72.0, 75.0] and all(t["total"] is None for t in S.compare("배재", 2023, "간호학과")["table"]))
    q_ = "배재대 2023학번 경영학과 학생: 복수전공은 몇 학점 이수해야 해?"
    q2_ = "배재대 2023학번 IT경영정보학과 학생: 복수전공은 몇 학점 이수해야 해?"
    check("E23: 묶음 행 조회 — 경영학과 질문은 묶음 행(39)을, IT경영정보학과 질문은 기존 BJ-039를 쓰고 서로 걸리지 않는다('경영' 글자 경계)",
          "BJ-039" not in (rows_of(q_) or []) and any(L.BY_ID[i]["값"] == "39" for i in rows_of(q_) or []) and "BJ-039" in (rows_of(q2_) or []) and len(rows_of(q2_) or []) == 2)
    # 1-1h. E24 목원 별표 4 묶음 행: 학과별 영역 기준·MSC·교직·전공필수(괄호) 하위행
    def mw(d, y):
        p_ = S.area_plan("목원", d, y)
        a_ = {x["name"]: x["min"] for x in p_["areas"]}
        return p_["tier"], (p_["grad"] or {}).get("값"), a_.get("교양"), a_.get("전공"), a_.get("MSC교과"), a_.get("교직필수"), p_["badges"]
    mt = S.grad_targets("목원")
    check("E24: 목원 '그 외 학과' 선택지에 별지 학과가 나열되고 쉼표 묶음 이름은 없다(80개 이상)",
          all(d in mt for d in ("신학과", "응급구조학과", "국어교육과", "사범대학", "건축학부 건축공학전공", "국제대학 글로벌융합학부")) and not any("," in d for d in mt) and len(mt) >= 80, str(len(mt)))
    check("E24: 건축공학전공 2023 T1 126 = 교양 20 + 전공 72(전필 36) + MSC 12 + 자유 0~22, 전공필수 하위행 때문에 배지가 뜨지 않음",
          mw("건축학부 건축공학전공", 2023) == ("T1", "126", 20.0, 72.0, 12.0, None, []))
    check("E24: 국어교육과 2022 T1 140 = 교양 23 + 전공 75 + 교직 22 + 자유 0~20, 2025는 교직 24·T2(미지정 17)",
          mw("국어교육과", 2022) == ("T1", "140", 23.0, 75.0, None, 22.0, []) and mw("국어교육과", 2025)[:2] == ("T2", "134") and mw("국어교육과", 2025)[5] == 24.0
          and S.area_plan("목원", "국어교육과", 2025)["unassigned"] == 17.0)
    check("E24: 건축학(5년)전공 2024 졸업 160·교양 31·전공 121, 글로벌융합학부 2026 졸업 120·교양 12·전공 72, 응급구조학과 2026 전공 92, 경영학부 2024 교양 31·전공 72(기존 행)",
          mw("건축학부 건축학(5년)전공", 2024)[:4] == ("T1", "160", 31.0, 121.0) and mw("국제대학 글로벌융합학부", 2026)[1:4] == ("120", 12.0, 72.0)
          and mw("응급구조학과", 2026)[1:4] == ("126", 21.0, 92.0) and mw("경영학부", 2024)[1:4] == ("126", 31.0, 72.0))
    check("E24: 목원 학과 행은 (학과·학번·이수유형·항목·조건) 중복이 없다(묶음 행 펼친 뒤)",
          not [k for k, v in __import__("collections").Counter((t, y, r["이수유형"], r["항목"], r["구분"], r["조건"]) for r in L.CRITERIA if r["대학"] == "목원" for t in L.targets_of(r) for y in range(2022, 2027) if L.in_range(r, y)).items() if v > 1])
    # 1-1i. E26 한남 전 학과: 졸업학점 묶음·교양·건축/간호 전공 예외·공학인증 안내
    def hn(d, y):
        p_ = S.area_plan("한남", d, y)
        return p_["tier"], p_["method"], (p_["grad"] or {}).get("값"), {a["name"]: a["min"] for a in p_["areas"]}, p_["unassigned"]
    ht = S.grad_targets("한남")
    check("E26: 한남 선택지에 학과가 나열되고 쉼표 묶음 이름은 없다(60개 이상), 계열은 선택지에 그대로 있다",
          all(d in ht for d in ("국어국문·창작학과", "수학과", "회화과", "미술교육과", "법학부", "간호학과", "건축학(5년제)", "인문사회계열")) and not any("," in d for d in ht) and len(ht) >= 60 and "코스메틱사이언스학과" not in ht, str(len(ht)))
    check("E26: 졸업학점 — 인문사회 120(국어국문·창작 2024)·이학 128(수학과 2023)·사범 127(미술교육과 2024), 2024학번 영역은 교양 30 참고(T3)",
          hn("국어국문·창작학과", 2024)[:3] == ("T3", "단수", "120") and hn("수학과", 2023)[2] == "128" and hn("미술교육과", 2024)[2] == "127"
          and hn("국어국문·창작학과", 2024)[3] == {"교양": 30.0})
    check("E26: 2022학번은 심화단수 교양 29 + 전공 66 = 95 → T2 미지정 25(국어국문·창작·무역학과·정보통신공학과 128은 33)",
          hn("국어국문·창작학과", 2022) == ("T2", "심화단수", "120", {"교양": 29.0, "전공": 66.0}, 25.0) and hn("무역학과", 2022)[4] == 25.0
          and hn("정보통신공학과", 2022)[2:5] == ("128", {"교양": 29.0, "전공": 66.0}, 33.0))
    rn = [("무역학과", "무역물류학과", 2022), ("호텔항공경영학과", "호텔항공경영학과", 2022), ("토목·건축공학부 건축공학전공", "건축공학과", 2023), ("토목·건축공학부 토목환경공학전공", "건설환경공학과", 2022), ("외국어문학부 일어일문학전공", "일어일문학과", 2023)]
    check("E26 수정: 이름이 바뀐 학과는 옛 학번 행에 옛 이름·지금 이름이 둘 다 있어 2022 무역물류학과 → T0 아님(T2 95학점, 미지정 25), 옛·지금 이름 결과가 같다",
          all(hn(a_, y_)[0] != "T0" and hn(a_, y_) == hn(b_, y_) for a_, b_, y_ in rn) and hn("무역물류학과", 2022) == ("T2", "심화단수", "120", {"교양": 29.0, "전공": 66.0}, 25.0))
    check("E26: 건축(5년제) 전공 108(2022 T2 미지정 15·2024 T2 14), 간호 2022 89·2023 87(T2 미지정 10·11)",
          hn("건축학(5년제)", 2022)[3:] == ({"교양": 29.0, "전공": 108.0}, 15.0) and hn("건축학(5년제)", 2024)[3:] == ({"교양": 30.0, "전공": 108.0}, 14.0)
          and hn("간호학과", 2022)[3:] == ({"교양": 29.0, "전공": 89.0}, 10.0) and hn("간호학과", 2023)[3:] == ({"교양": 30.0, "전공": 87.0}, 11.0))
    ec = lambda d, y: [i["text"] for i in S.checklist("한남", y, d) if i["title"] == "공학교육인증"]
    check("E26: 공학인증 안내 — 정보통신공학과 2022는 '2027년 2월 졸업생까지', 건설환경공학과 2025·토목환경공학전공 2023은 '일반 학과 기준', 수학과는 없음",
          len(ec("정보통신공학과", 2022)) == 1 and "2027년 2월" in ec("정보통신공학과", 2022)[0] and len(ec("건설환경공학과", 2025)) == 1 and "일반 학과 기준" in ec("건설환경공학과", 2025)[0]
          and len(ec("토목·건축공학부 토목환경공학전공", 2023)) == 1 and ec("수학과", 2024) == [])
    check("E26: 한남 학과 행은 (학과·학번·이수유형·항목·조건) 중복이 없다(묶음 행 펼친 뒤, 졸업학점은 학과당 하나)",
          not [k for k, v in __import__("collections").Counter((t, y, r["이수유형"], r["항목"], r["구분"], r["조건"]) for r in L.CRITERIA if r["대학"] == "한남" for t in L.targets_of(r) for y in range(2022, 2027) if L.in_range(r, y) and r["항목"] != "공학인증_안내" and not (t == "경영정보학과" and r["항목"] == "졸업학점")).items() if v > 1])  # 경영정보학과 졸업학점 HN-005·006 겹침은 E26 이전부터(편람 126 잠정)
    # 1-1j. E25 한밭 전 학과: 계열별 전공 72·기본·심화·대학특화·교양 %, 건축 106, 편입_이수요건
    def hbp(d, y):
        p_ = S.area_plan("한밭", d, y)
        return p_["tier"], (p_["grad"] or {}).get("값"), {a["name"]: a["min"] for a in p_["areas"]}, p_["unassigned"]
    hbt = S.grad_targets("한밭")
    check("E25: 한밭 선택지에 학과가 나열되고 쉼표 묶음 이름은 없다(30개 이상)",
          all(d in hbt for d in ("기계공학과", "건축설비시스템공학과", "산업디자인학과", "영어영문학과", "회계세무학과", "건축학과(5년제)", "국제학부")) and not any("," in d for d in hbt) and len(hbt) >= 30, str(len(hbt)))
    check("E25: 계열별 대학특화는 2023학번부터(공학 11·디자인 8·인문 4·경상 5), 2022학번은 전공 72만(대학특화 없음)",
          hbp("기계공학과", 2023)[2] == {"교양": None, "전공": 72.0, "대학특화": 11.0} and hbp("산업디자인학과", 2024)[2].get("대학특화") == 8.0 and hbp("영어영문학과", 2025)[2].get("대학특화") == 4.0
          and hbp("회계세무학과", 2026)[2].get("대학특화") == 5.0 and "대학특화" not in hbp("기계공학과", 2022)[2] and hbp("기계공학과", 2022)[2].get("전공") == 72.0)
    check("E25: 학번별 정원이 있는 학과만 — 우주국방첨단융합학과 2025는 T0·2026은 T3, 설비공학과·건축설비시스템공학과는 2022~ 이름 둘 다 T3(이름 변경 규칙)",
          hbp("우주국방첨단융합학과", 2025)[0] == "T0" and hbp("우주국방첨단융합학과", 2026)[0] == "T3" and hbp("설비공학과", 2022)[0] == "T3" and hbp("건축설비시스템공학과", 2022) == hbp("설비공학과", 2022))
    check("E25: 건축학과(5년제) 전공 106(2022 T3 교양 %), 2026 교양 33 + 전공 106 + 대학특화 11 = 150 → T2 미지정 10, 졸업 160",
          hbp("건축학과(5년제)", 2022)[:3] == ("T3", "160", {"교양": None, "전공": 106.0}) and hbp("건축학과(5년제)", 2026) == ("T2", "160", {"교양": 33.0, "전공": 106.0, "대학특화": 11.0}, 10.0))
    check("E25: 융합경영학과(기존 행)는 그대로 T3·전공 72·대학특화 5, 국제학부는 T0",
          hbp("융합경영학과", 2025)[2] == {"교양": None, "전공": 72.0, "대학특화": 5.0} and hbp("국제학부", 2025)[0] == "T0")
    tr = [i["title"] for i in S.checklist("한밭", 2024, "기계공학과", entry="편입")]
    check("E25: 한밭 편입 체크리스트에 편입 심화전공·전공 50학점·교양 10학점 이내, 신입은 없음",
          {"편입 심화전공 이수", "편입 전공 50학점", "편입 교양 10학점 이내"} <= set(tr) and not [i for i in S.checklist("한밭", 2024, "기계공학과") if i["title"].startswith("편입")])
    check("E25: 한밭 학과 행은 (학과·학번·이수유형·항목·조건) 중복이 없다(묶음 행 펼친 뒤)",
          not [k for k, v in __import__("collections").Counter((t, y, r["이수유형"], r["항목"], r["구분"], r["조건"]) for r in L.CRITERIA if r["대학"] == "한밭" and r["항목"] != "편입_이수요건" for t in L.targets_of(r) for y in range(2022, 2027) if L.in_range(r, y)).items() if v > 1])
    # 1-1k. E27 서비스 점검 #18~21: 학과 행이 없는 항목은 전체 행으로 채움·공학인증 조회·학과+영역/기준 질문 조회
    rq = lambda raw, u, y, d: rows_of(engine.choose_question(raw, u, y, d)[0])
    check("E27: 목원 응급구조학과 '졸업학점이랑 전공 몇 학점이야?'는 학과를 붙인 채 조회(E27b로 전공 MW-262 + E27b 묶음 졸업학점 MW-338, 학과 행이 없는 항목은 이름이 기준표에 있으면 전체 행으로 채움)",
          rq("졸업학점이랑 전공 몇 학점이야?", "목원", 2024, "응급구조학과") == ["MW-262", "MW-338"] and engine.choose_question("졸업학점이랑 전공 몇 학점이야?", "목원", 2024, "응급구조학과")[1])
    check("E27: 기준표 어디에도 없는 학과 이름은 E8대로 RAG(조회 안 함)", L.lookup("목원대 2024학번 우주해양학과 학생: 졸업학점 몇 학점이야?")[0] is None and not L.dept_in_criteria("목원", "목원대 2024학번 우주해양학과 학생: 졸업학점 몇 학점이야?"))
    check("E27: 공학인증 안내 조회 — 한남 정보통신공학과 2023 HN-064·2022 HN-063, 학과 행이 없는 수학과·학과 없는 질문은 RAG",
          rq("공학인증 해야 돼?", "한남", 2023, "정보통신공학과") == ["HN-064"] and rq("공학인증 해야 돼?", "한남", 2022, "정보통신공학과") == ["HN-063"]
          and rq("공학인증 해야 돼?", "한남", 2023, "수학과") is None)
    check("E27: 학과+영역별·전공 기준 질문은 그 학과 행 조회 — 한남 2022 무역물류학과 영역별 HN-042·054·011, 한밭 2024 산업디자인학과 전공 기준 HB-001·048·045·046·047·049",
          rq("졸업까지 영역별로 얼마나 들어야 해?", "한남", 2022, "무역물류학과") == sorted(["HN-042", "HN-054", "HN-011"])
          and rq("전공 기준 알려줘", "한밭", 2024, "산업디자인학과") == sorted(["HB-001", "HB-048", "HB-045", "HB-046", "HB-047", "HB-049"]))
    check("E27: 다른 주제의 '기준'은 조회로 안 감(졸업 평점 기준·수강신청 기준·재수강 기준은 영역 질문 아님), 학과 없는 '졸업요건'도 RAG",
          all(rq(x, "한남", 2023, "경영정보학과") is None for x in ("졸업 평점 기준 있어?", "수강신청 기준 알려줘", "재수강 기준이 뭐야?")) and rq("졸업요건 알려줘", "한남", 2023, None) is None)
    # 1-1l. E27b: 졸업학점·교양·전공 중 둘 이상을 묻는 질문은 항목을 모두 조회, 하나뿐인 질문은 그대로
    check("E27b: 목원 2024 응급구조학과 '졸업학점이랑 전공' → 학과 묶음 졸업 MW-338 + 전공 MW-262(전체 행 MW-002의 '예외 대상 제외'를 안 쓴다)",
          rq("졸업학점이랑 전공 몇 학점이야?", "목원", 2024, "응급구조학과") == ["MW-262", "MW-338"])
    check("E27b: '교양이랑 전공 몇 학점'(졸업학점 없이)도 둘 다 조회", L.extra_area_items("교양이랑 전공 몇 학점이야?") == ["교양", "전공"]
          and rq("교양이랑 전공 몇 학점이야?", "한남", 2023, "경영정보학과") is not None)
    check("E27b: 항목 하나짜리 질문은 그대로(졸업학점만·전공만·복수전공 전공학점은 영역 낱말 아님)",
          L.extra_area_items("졸업학점 몇 학점이야?") == [] and L.extra_area_items("전공 몇 학점이야?") == [] and L.extra_area_items("복수전공은 몇 학점이야?") == []
          and L.extra_area_items("복수전공하면 졸업학점이 몇 학점이야?") == [])
    check("E27b: 학과 행이 없는 전공 항목은 건너뛰어 졸업학점 단독 조회가 새로 RAG로 가지 않는다(학과 없는 한밭 질문)",
          rq("졸업학점이랑 전공 몇 학점이야?", "한밭", 2024, None) is not None)
    mw_grad = {}
    for r_ in L.CRITERIA:
        if r_["대학"] == "목원" and r_["항목"] == "졸업학점" and r_["대상단위"] != "대학":
            for t_ in L.targets_of(r_):
                for y_ in range(2022, 2027):
                    if L.in_range(r_, y_):
                        mw_grad.setdefault((t_, y_), []).append(int(r_["값"]))
    mw_depts = {(t_, y_) for r_ in L.CRITERIA if r_["대학"] == "목원" and r_["대상단위"] == "학과" and r_["항목"] == "교양" for t_ in L.targets_of(r_) for y_ in range(2022, 2027) if L.in_range(r_, y_) and t_ != "사범대학"}
    teach_ = ("국어교육과", "영어교육과", "음악교육과", "미술교육과", "유아교육과", "수학교육과", "에듀테크융합자율전공학부")
    def mw_want(k_):  # 원문 합계 칸: 2022 기본 132(건축학(5년) 165·정보통신 140·사범 140), 2023 기본 126(건축학(5년) 160·사범 134), 2024~ 126(건축학(5년) 160·사범 134·글로벌융합 120)
        d_, y_ = k_
        if "건축학(5년)" in d_:
            return 165 if y_ == 2022 else 160
        if d_ in teach_:
            return 140 if y_ == 2022 else 134
        if d_ == "정보통신공학과" and y_ == 2022:
            return 140
        if "글로벌융합" in d_:
            return 120
        return 132 if y_ == 2022 else 126
    check("E27b·E27c: 목원 2022~2026 학과 묶음 모든 학과·학번에 졸업학점 행이 정확히 하나이고 값이 원문 합계 칸과 같다",
          all(len(mw_grad.get(k_, [])) == 1 for k_ in mw_depts) and all(mw_grad[k_][0] == mw_want(k_) for k_ in mw_depts),
          [k_ for k_ in mw_depts if len(mw_grad.get(k_, [])) != 1 or mw_grad[k_][0] != mw_want(k_)])
    check("E26c: 한남 코스메틱사이언스학과(정원외 외국인 전담학과)는 어느 학번 기준표 대상에도 없고 학과 선택지에도 없다(연계·융합전공 이름은 학과가 아니라 해당 없음)",
          not any("코스메틱" in t_ for r_ in L.CRITERIA if r_["대학"] == "한남" for t_ in L.targets_of(r_))
          and all("코스메틱사이언스학과" not in sum(S.dept_choices("한남", y_), []) for y_ in range(2022, 2027)))
    # 1-1n. E24d: 화면용 정리 함수(display_note·strip_ids) — criteria.csv 원본·프롬프트용 clean_note는 그대로
    hn026_ = L.BY_ID["HN-026"]["비고"]
    check("E24d: display_note — 평가셋·내부 메모 문장은 지우고 학생용 안내('부전공 없이 단수 54는 선택 불가(융합교육 필수)')는 남긴다",
          S.display_note(hn026_) == "주전공 45 + 부전공 21 = 66. 부전공 없이 단수 54는 선택 불가(융합교육 필수)." and "평가셋" in hn026_)
    SI_ = {"비전설계 영역에서 1과목(3학점)을 이수해요(기준표 BJ-016).": "비전설계 영역에서 1과목(3학점)을 이수해요.",
           "전공융합설계 9학점 이상(BJ-034), 비전설계 3학점(BJ-035)예요.": "전공융합설계 9학점 이상, 비전설계 3학점예요.",
           "전공탐색(0.5학점×2, BJ-033)은 없어요": "전공탐색(0.5학점×2)은 없어요", "남았어요. 행 BJ-050": "남았어요.",
           "근거 행: HN-026, HN-020": "", "`HB-001` · 이수 방식 단수": "이수 방식 단수", "부전공은 54학점(HN-026)이에요.": "부전공은 54학점이에요."}
    check("E24d: strip_ids — 괄호에 ID만 든 것은 괄호째, '(…, ID)'는 ID만, '행 ID'·'근거 행: …'·코드 서식 ID는 지운다", all(S.strip_ids(k_) == v_ for k_, v_ in SI_.items()), str([(k_, S.strip_ids(k_)) for k_, v_ in SI_.items() if S.strip_ids(k_) != v_]))
    leak_rows_ = [r_["행ID"] for r_ in L.CRITERIA if re.search(r"평가셋|(?:BJ|MW|HB|HN|CN)-\d{3}|시작 비움", S.display_note(r_["비고"]))]
    check("E24d: 기준표 모든 행의 비고가 display_note를 거치면 평가셋·행 ID·'시작 비움'이 남지 않는다(원본 criteria.csv 비고는 그대로: 평가셋 28행)",
          not leak_rows_ and sum(1 for r_ in L.CRITERIA if "평가셋" in r_["비고"]) == 28, str(leak_rows_[:5]))
    # 1-1m. E24b: 사이드바 학과 목록(학번별 · 묶음 행은 학과 하나하나 · 대체 선택지는 따로)
    DEPT_KNOWN_NO_GRAD = {("충남", "약학과")}  # 졸업학점 행이 둘(168·232, 원문 구분 설명 없음)이라 하나로 안 풀림: 선택은 되고 화면이 확인 불가를 안내
    bad_dc = []
    for u_ in S.BASE_DEPT:
        for y_ in range(2022, 2027):
            ds_, al_ = S.dept_choices(u_, y_)
            bad_dc += [(u_, y_, t_) for t_ in ds_ + al_ if S.graduation_row(u_, t_, y_) is None and (u_, t_) not in DEPT_KNOWN_NO_GRAD]
            bad_dc += [(u_, y_, "빈 목록")] if not ds_ else []
    check("E24b: 학번별 학과 목록의 모든 학과·계열이 그 학번에 졸업학점 행이 풀린다(알려진 예외 2개 제외), 목록은 학교·학번마다 비지 않는다", not bad_dc, str(bad_dc[:5]))
    d22_, a22_ = S.dept_choices("목원", 2022)
    d24_, a24_ = S.dept_choices("목원", 2024)
    check("E24b: 목원 응급구조학과는 2022 목록에 없고 2024 목록에 있다(학번에 행이 있는 학과만), 사범대학·계약학과 및 영어트랙은 대체 선택지",
          "응급구조학과" not in d22_ and "응급구조학과" in d24_ and "사범대학" in a22_ and "계약학과 및 영어트랙" in a24_ and "사범대학" not in d24_ and "계약학과 및 영어트랙" not in d24_)
    dh_, ah_ = S.dept_choices("한남", 2023)
    check("E24b: 한남 계열 2개는 대체 선택지(학과 목록 뒤)이고 학과 목록에 없다, 묶음 행은 학과 하나하나로 펼쳐 이름이 겹치지 않는다",
          {"인문사회계열", "이학·공학·예능·체능·간호계열"} <= set(ah_) and not ({"인문사회계열", "이학·공학·예능·체능·간호계열"} & set(dh_)) and len(dh_) == len(set(dh_)) and "경영정보학과" in dh_)
    check("E24b: 학번이 없으면 2022~2026 합집합(목원 학과가 학번별 목록보다 많다), 범위 밖 값도 합집합", len(S.dept_choices("목원", None)[0]) > len(d24_) and S.dept_choices("목원", "범위 밖")[0] == S.dept_choices("목원", None)[0])
    check("E24b: 기존 grad_targets(univ)는 그대로(학번 없는 전체 목록)", all(set(S.dept_choices(u_, None)[0] + S.dept_choices(u_, None)[1]) <= set(S.grad_targets(u_)) for u_ in S.BASE_DEPT))
    # 1-1e. 회귀 사례(E20, 서비스 점검 #14): 편입생 필수·면제 질문은 편입_이수요건(BJ-060~063)을 조회한다(배재). 학점·수치 질문은 영향 없음
    E20_ROWS = ["BJ-060", "BJ-061", "BJ-062", "BJ-063"]
    for raw in ("편입생은 전공 말고 필수로 들어야하는게 아펜젤러만 있나?", "편입생도 채플 들어야 해?", "편입생 교양필수 뭐 들어야 돼?"):
        q, used = engine.choose_question(raw, "배재", 2023, "IT경영정보학과")
        check(f"회귀 E20: 배재 2023 편입 질문 '{raw}'은 조회 BJ-060~063", rows_of(q) == E20_ROWS and engine.routable(q), f"{q} {rows_of(q)}")
    check("회귀 E20: 배재 '편입생은 전공 몇 학점 들어야 해?'(학점 질문, 서비스 점검 #11)는 이수요건이 아니라 RAG 그대로",
          rows_of(engine.choose_question("편입생은 전공 몇 학점 들어야 해?", "배재", 2023, "IT경영정보학과")[0]) is None)
    check("회귀 E20: 한밭 '편입생도 채플 들어야 해?'는 편입 행이 다루지 않는 주제라 RAG로 남음",
          rows_of(engine.choose_question("편입생도 채플 들어야 해?", "한밭", 2024, "융합경영학과")[0]) is None)
    check("E25b: 한밭 '편입생은 전공 몇 학점 들어야 해?'는 편입 행(전공 50학점)이 다루는 주제라 조회(HB-076~078), 졸업학점 질문·행에 없는 봉사·졸업시험은 조회 아님",
          rows_of(engine.choose_question("편입생은 전공 몇 학점 들어야 해?", "한밭", 2024, "융합경영학과")[0]) == ["HB-076", "HB-077", "HB-078"]
          and rows_of(engine.choose_question("편입생은 졸업하려면 몇 학점 이수해야 해?", "한밭", 2024, "융합경영학과")[0]) != ["HB-076", "HB-077", "HB-078"]
          and all(rows_of(engine.choose_question(x, "한밭", 2024, "융합경영학과")[0]) is None for x in ("편입생도 봉사 들어야 해?", "편입생도 졸업시험 봐야 해?")))
    check("E25b: 일반 규칙 — 주제어는 그 학교 편입 행에서 뽑는다(배재 채플·아펜젤러·면제, 한밭 전공·심화전공·학점·교양, 한밭엔 채플 없음)",
          {"채플", "아펜젤러", "면제"} <= L.transfer_topics("배재") and "학점" not in L.transfer_topics("배재") and {"전공", "심화전공", "학점", "교양"} <= L.transfer_topics("한밭") and "채플" not in L.transfer_topics("한밭"))
    check("회귀 E20: 수치 의도가 앞선다(편입생은 졸업하려면 몇 학점 이수해야 해? → 졸업학점 조회, 편입_이수요건 아님)",
          "BJ-060" not in (rows_of(engine.choose_question("편입생은 졸업하려면 몇 학점 이수해야 해?", "배재", 2023, "IT경영정보학과")[0]) or []))
    q, used = engine.choose_question("혁신교육과미래설계 꼭 들어야 해?", "배재", 2025, "IT경영정보학과")
    check("한계 E13: 과목명 필수 여부(BJ-032 혁신교육과미래설계)는 조회 항목이 아니라 RAG로 간다(이번에 고치지 않음)", rows_of(q) is None and not engine.routable(q), q)
    # 1-1c. 편입 학번 안내(사이드바, 2026-11-09 조사)와 체크리스트 안내 규칙
    for u, arts in (("배재", ("제17조 ⑦", "제63조 ②", "제64조 ④")), ("한남", ("제12조", "제20조의2")), ("한밭", ("졸업요건 웹페이지", "등급 C", "2021학년도 이후 편입생"))):
        n = S.transfer_note(u)
        check(f"편입 안내 {u}: 한 줄(2년 앞 학번·2023학번 예시), 근거 접기에 3학년 편입 기준·조문·해석 명시, '4학년 24학점' 문구 없음",
              n["text"] == "편입생은 2년 앞 학번을 고르세요. (예: 2025년 편입 → 2023학번)" and any("3학년 편입 기준이에요. 그 외 학년은 학과에 확인하세요." == b for b in n["basis"])
              and all(any(a in b for b in n["basis"]) for a in arts) and any(("해석" in b) or (u == "한밭" and "학과에 확인하세요" in b) for b in n["basis"]) and "24학점" not in n["text"] + "".join(n["basis"]), str(n)[:120])
    check("편입 안내 충남·목원: 한 줄 '적용 학번을 학과에서 확인하세요' + 근거 없음",
          all(S.transfer_note(u) == {"text": S.TRANSFER_CHECK_LINE, "basis": []} for u in ("충남", "목원")))
    for u, y, d, q, want in (("배재", 2025, "IT경영정보학과", "혁신교육과미래설계 꼭 들어야 해?", ["0학점 이수 필수"]),
                             ("목원", 2024, "경영학부", "체험교과목 이수해야 해?", ["체험교과목"]),
                             ("충남", 2024, "경영학부", "졸업 평점은 몇 점이야?", ["졸업 평점"]),
                             ("한밭", 2024, "융합경영학과", "졸업하려면 뭐가 더 필요해?", [])):
        got = S.checklist_hint(q, u, y, d)
        check(f"체크리스트 안내 규칙: {q} → {want}", got == want, str(got))
    check("체크리스트 안내: 학번이 정수가 아니면(모름·범위 밖) 붙이지 않는다", S.checklist_hint("혁신교육과미래설계 꼭 들어야 해?", "배재", None, "IT경영정보학과") == [])
    # 개발용 51문항: 최신 채택 답변 기준 '확인 불가' 배지가 뜨는 문항 중 안내 줄이 붙는 문항 수(2026-11-09 기록: 17문항 중 0개)
    import csv
    ans = {}
    for tag in ("e8-full", "e9-r1", "e10-r1", "e11-r1", "e13-r1"):
        for f in (ROOT / "eval" / "results").glob(f"*_dev_base-rag_gpt-6-luna_{tag}.csv"):
            for r in csv.DictReader(open(f, encoding="utf-8-sig")):
                ans[r["id"]] = r["답변"]
    unans, shown = [], []
    for r in csv.DictReader(open(ROOT / "eval" / "questions_dev.csv", encoding="utf-8-sig")):
        if r["id"] in ans and R.UNANSWERABLE_RE.search(engine.split_answer(ans[r["id"]])[0]):
            unans.append(r["id"])
            if r["대학"] in S.BASE_DEPT and r["학번"].isdigit() and 2022 <= int(r["학번"]) <= 2026 and \
                    S.checklist_hint(r["질문"], r["대학"], int(r["학번"]), S.BASE_DEPT[r["대학"]], "신입", True):
                shown.append(r["id"])
    check(f"체크리스트 안내: 개발용 '확인 불가' 문항 {len(unans)}개 중 안내가 붙는 문항 0개(기록과 같음)", len(unans) == 17 and shown == [], f"{len(unans)} {shown}")
    # 1-2. 동치 점검의 재시도 허용 규칙(B01 흔들림만 허용하고 나머지는 바로 실패)
    def row(chunks, dists, coll="base-x", user="u1", filt='{"대학": "배재"}'):
        return {"컬렉션": coll, "검색청크": ";".join(chunks), "검색거리": ";".join(dists), "검색근거표시": ";".join(chunks), "필터": filt,
                "llm_call": {"name": "answer", "model": "m", "system": "s", "user": user, "user_len": 1}}
    base_row = row(["a", "b", "c", "d", "e"], ["0.979", "0.979", "0.981", "0.981", "0.985"])
    b01 = row(["a", "b", "c", "x", "d"], ["0.979", "0.979", "0.981", "0.981", "0.981"], user="u2")
    check("재시도 허용: B01 모양(마지막 순위 청크 1개 교체, 거리 차 0.004)", diff_rows({"B01": base_row}, {"B01": b01}) == ([], ["B01"]))
    far = row(["a", "b", "c", "x", "d"], ["0.979", "0.979", "0.981", "0.981", "0.995"], user="u2")
    check("재시도 불허: 마지막 순위 거리 차이가 허용치(0.005)보다 크다", diff_rows({"B01": base_row}, {"B01": far})[0] != [])
    two = row(["a", "b", "x", "y", "e"], ["0.979", "0.979", "0.981", "0.981", "0.985"], user="u2")
    check("재시도 불허: 청크가 2개 바뀜", diff_rows({"B01": base_row}, {"B01": two})[0] != [])
    top = row(["x", "b", "c", "d", "e"], ["0.979", "0.979", "0.981", "0.981", "0.985"], user="u2")
    check("재시도 불허: 앞 순위 청크가 바뀜", diff_rows({"B01": base_row}, {"B01": top})[0] != [])
    other = dict(b01, 필터='{"대학": "한남"}')
    check("재시도 불허: 필터 등 파생이 아닌 열도 다름", diff_rows({"B01": base_row}, {"B01": other})[0] != [])
    lk = row(["a", "b", "c", "x", "d"], ["0.979", "0.979", "0.981", "0.981", "0.981"], coll="criteria-lookup", user="u2")
    check("재시도 불허: RAG가 아닌 경로(조회·계산)의 불일치", diff_rows({"B01": dict(base_row, 컬렉션="criteria-lookup")}, {"B01": lk})[0] != [])
    check("같은 행은 불일치 없음", diff_rows({"B01": base_row}, {"B01": dict(base_row)}) == ([], []))
    # 2. 영역별 계획: 2단계 드라이런과 같은 판정
    tiers = {}
    for u, d in S.BASE_DEPT.items():
        for y in S.YEARS:
            tiers[(u, y)] = S.area_plan(u, d, y)
    count = {t: sum(1 for p in tiers.values() if p["tier"] == t) for t in ("T1", "T2", "T3")}
    check("영역별 계획 판정 T1 8 · T2 8 · T3 9 (E26: 한남 2022 심화단수 T2)", count == {"T1": 8, "T2": 8, "T3": 9}, str(count))
    t1_ok = all(p["areas"] and sum(a["min"] for a in p["areas"]) <= float(p["grad"]["값"]) <= sum(a["max"] for a in p["areas"]) for p in tiers.values() if p["tier"] == "T1")
    check("T1은 영역 합이 졸업학점과 맞는다", t1_ok)
    check("충남 2026 기본 방식은 심화단수 행", tiers[("충남", 2026)]["method"] == "심화단수" and tiers[("충남", 2026)]["tier"] == "T1")
    check("배재 2022~2024 교양: '합이 안 맞는 영역 있음' 배지(하위 34 ≠ 계 36)", all(tiers[("배재", y)]["badges"] and "34" in tiers[("배재", y)]["badges"][0] for y in (2022, 2023, 2024)))
    check("배재 2025~: 교양 하위 합 일치라 배지 없음, 규정 표에 영역이 지정되지 않은 학점 26", all(not tiers[("배재", y)]["badges"] and tiers[("배재", y)]["unassigned"] == 26 for y in (2025, 2026)))
    check("목원 2025·2026: 규정 표에 영역이 지정되지 않은 학점 23", all(tiers[("목원", y)]["tier"] == "T2" and tiers[("목원", y)]["unassigned"] == 23 for y in (2025, 2026)))
    check("한남 2023~·한밭은 T3(참고 표), 한남 2022는 심화단수 교양 29 + 전공 66 = 95 → T2(미지정 25)(E26)",
          all(tiers[(u, y)]["tier"] == "T3" and tiers[(u, y)]["ref_rows"] for u in ("한남", "한밭") for y in S.YEARS if (u, y) != ("한남", 2022))
          and tiers[("한남", 2022)]["tier"] == "T2" and tiers[("한남", 2022)]["method"] == "심화단수" and tiers[("한남", 2022)]["unassigned"] == 25)
    other = S.area_plan("충남", "간호학과", 2024)
    check("경영 계열 밖 학과는 총 졸업학점까지만(충남 간호학과 T0)", other["tier"] == "T0" and other["grad"] is not None and not other["areas"], other["tier"])
    p = tiers[("충남", 2024)]
    rem = S.remaining(p, {"교양": 30, "전공": 80, "일반선택": 5})
    check("남은 학점: 영역별(6+0+11=17)과 총(130−115=15)을 따로 계산하고 초과분에 확인 문구", rem["area_remaining_sum"] == 17 and rem["total_remaining"] == 15
          and any("학과 확인 필요" in a["note"] for a in rem["areas"]), str(rem["area_remaining_sum"]) + "/" + str(rem["total_remaining"]))
    # 3. 학점 외 체크리스트
    def kinds(u, y, entry="신입", teacher=False, dept=None):
        return {(i["title"], i["kind"]): i for i in S.checklist(u, y, dept or S.BASE_DEPT[u], entry, teacher)}
    check("배재 2025~: 0학점 이수 필수(BJ-032) 표시, 2024는 없음", ("0학점 이수 필수", "요건") in kinds("배재", 2025) and ("0학점 이수 필수", "요건") not in kinds("배재", 2024))
    check("배재 졸업 평점은 확인 불가", ("졸업 평점", "확인불가") in kinds("배재", 2024))
    check("목원 졸업 평점은 '없음'(본문은 쉬운 말, 조문은 출처 줄에)", ("졸업 평점", "없음") in kinds("목원", 2024) and "제47조" not in kinds("목원", 2024)[("졸업 평점", "없음")]["text"] and "제47조" in kinds("목원", 2024)[("졸업 평점", "없음")]["src"]["source"])
    k = kinds("목원", 2024)
    check("목원 신입: 비교과 20시간, 체험교과목 일반학과 없음", ("비교과", "요건") in k and "20시간" in k[("비교과", "요건")]["text"] and ("체험교과목", "없음") in k)
    check("목원 편입: 비교과는 제외 대상", ("비교과", "해당없음") in kinds("목원", 2024, "편입"))
    check("목원 2026 재입학: 비교과 20시간(편입학자만 제외)", ("비교과", "요건") in kinds("목원", 2026, "재입학"))
    check("목원 사범·교직이수자: 체험교과목 3학점", "3학점" in kinds("목원", 2024, "신입", True).get(("체험교과목", "요건"), {"text": ""})["text"])
    check("한밭 신입 70유닛 / 편입 35유닛", "70유닛" in kinds("한밭", 2023)[("비교과", "요건")]["text"] and "35유닛" in kinds("한밭", 2023, "편입")[("비교과", "요건")]["text"])
    check("목원 글로벌융합학부: 비교과 없음", ("비교과", "없음") in kinds("목원", 2026, "신입", False, "국제대학 글로벌융합학부"))
    # 4. 학사 선택 비교: 평가셋 정답과 E11 규칙 A와 같은 값
    def totals(u, y, d):
        r = S.compare(u, y, d)
        return r, [t["total"] for t in r["table"]] if r["ok"] else None
    r, v = totals("목원", 2022, "경영학부")
    check("비교 M08(목원 2022): 부전공 72·복수전공 66, 복수가 6학점 적음", v == [72, 66] and r["less"] == "복수전공" and r["diff"] == 6, str(v))
    r, v = totals("한남", 2023, "경영정보학과")
    check("비교 H10(한남 2023): 부전공 66·다전공 72, 부전공이 6학점 적음", v == [66, 72] and r["less"] == "부전공" and r["diff"] == 6, str(v))
    r, v = totals("배재", 2024, "IT경영정보학과")
    check("비교 P04(배재 2024, 학과 입력): 부전공 72·다전공 75, 부전공이 3학점 적음", v == [72, 75] and r["less"] == "부전공" and r["diff"] == 3, str(v))
    r = S.compare("배재", 2024, None)
    check("배재는 학과를 안 고르면 주전공 요구 학점이 없어 합을 계산하지 않는다(확인 불가)", r["ok"] and not r["full"] and all(t["total"] is None for t in r["table"]), str(r.get("reasons")))
    same = True
    for u, y in (("목원", 2022), ("한남", 2023)):
        q = S.explain_question(u, y, S.BASE_DEPT[u])
        e11 = criteria_calc.calc(q)[0]
        mine = S.compare(u, y, S.BASE_DEPT[u])
        same &= e11 is not None and [float(x) for x in e11["values"].values()] == [t["total"] for t in mine["table"]]
    check("비교 값이 E11 규칙 A(criteria_calc) 결과와 같다(목원 2022·한남 2023)", same)
    # 5. 답변 본문과 출처 줄 분리
    body, tail = engine.split_answer("복수전공이 6학점 더 적어요.\n\n출처: [1] 학칙 제1조")
    check("출처 줄 분리", body == "복수전공이 6학점 더 적어요." and tail.startswith("출처:"), repr((body, tail)))
    body, tail = engine.split_answer("결론이에요.\n- 설명 1\n\n인용 출처: [1] 학칙")
    check("'인용 출처:' 줄 분리", body.endswith("설명 1") and tail.startswith("인용 출처"), repr((body, tail)))
    body, tail = engine.split_answer("출처 없이 끝나는 답이에요.")
    check("출처 줄이 없으면 그대로", body == "출처 없이 끝나는 답이에요." and tail == "")
    body, tail = engine.split_answer("출처: [1] 학칙")
    check("본문 없이 출처 줄만 있으면 통째로 본문", body == "출처: [1] 학칙" and tail == "")


    # 1-9b. 체크리스트 본문에는 조항·개정 이력·부칙이 없다(5개 대학 × 2022~2026학번 × 입학 구분 3 × 사범대 여부, 기본 학과 기준)
    ref_re = re.compile(r"제\s*\d+\s*조|개정|신설|부칙|시행세칙|\d{4}\.\s?\d")
    bad_ck, n_ck = [], 0
    for u_ in S.BASE_DEPT:
        for y_ in range(2022, 2027):
            for en_ in S.ENTRY_TYPES:
                for tc_ in ((False, True) if S.has_teacher_rows(u_) else (False,)):
                    for it_ in S.checklist(u_, y_, S.BASE_DEPT[u_], en_, tc_):
                        n_ck += 1
                        if ref_re.search(it_["title"] + it_["text"]):
                            bad_ck.append((u_, y_, en_, it_["title"], it_["text"][:40]))
    check(f"체크리스트 본문: 조항·개정·부칙이 남는 항목 0개(항목 {n_ck}개 점검)", not bad_ck and n_ck > 100, str(bad_ck[:3]))
    t_, rm_ = S.plain_text("일반학과는 이 요건이 없어요(학칙 시행세칙 제27조 ④ (개정 2025.3.29.); 부칙(세칙 제24109호, 2025.3.29.) 제2조 체험교과목 이수에 관한 적용례).")
    check("체크리스트 본문 정리 규칙: 중첩 괄호의 조항·개정·부칙은 본문에서 빠지고 뺀 문구로 돌려준다, 조건 괄호는 그대로", t_ == "일반학과는 이 요건이 없어요." and any("제27조" in x for x in rm_) and any("부칙" in x for x in rm_)
          and S.plain_text("비교과를 20시간 이수해야 해요. (조건: 편입학자 제외)") == ("비교과를 20시간 이수해야 해요. (조건: 편입학자 제외)", []))
    mw = {it_["title"]: it_ for it_ in S.checklist("목원", 2023, "경영학부", "신입", False)}
    check("체크리스트: 목원 졸업 평점·체험교과목은 쉬운 한 문장, 조항은 출처 줄(src)에 그대로", mw["졸업 평점"]["text"] == "졸업 평점 기준은 없어요. 학과에 한 번 확인하세요." and mw["체험교과목"]["text"] == "일반학과는 체험교과목 요건이 없어요."
          and "제47조" in mw["졸업 평점"]["src"]["source"] and "제27조" in mw["체험교과목"]["src"]["source"])
    # 1-9c. E19 로직 부품: % 기준 표기, 부족 영역 → 개설 과목 영역, 약어 툴팁
    import ui_style as U_
    hb = {r["항목"]: r for r in S.area_plan("한밭", S.BASE_DEPT["한밭"], 2024)["ref_rows"]}
    check("E19: % 기준은 '졸업학점의 25% 이상', 학점 기준은 그대로('5학점 이상'), fmt_value는 그대로('25% 이상')",
          S.fmt_basis(hb["교양"]) == "졸업학점의 25% 이상" and S.fmt_basis(hb["대학특화"]) == "5학점 이상" and S.fmt_value(hb["교양"]) == "25% 이상" and S.fmt_basis(hb["기본전공"]) == "36~51학점 범위")

    def fa(name, remaining, kids=()):
        return {"name": name, "remaining": remaining, "kids": [{"name": k, "remaining": r} for k, r in kids]}
    ra = [fa("교양", 20, [("교양필수", 0.0), ("교양_글로벌언어", 3.0), ("교양_균형학문", 9.0), ("교양_비전설계", 3.0)]), fa("전공", 5)]
    check("E19: 부족 영역 → 개설 과목 영역 — 세부 입력 있으면 부족한 교양 세부 영역과 전공, 2022~2024는 교양_비전설계 포함",
          CR.deficit_targets(2023, ra, False, True) == (["교양_글로벌언어", "교양_균형학문", "교양_비전설계", "전공"], False))
    check("E19: 교양 부족인데 세부 입력이 없으면 영역을 미리 고르지 않고(pick=True) 전공만 연결", CR.deficit_targets(2023, ra, False, False) == (["전공"], True))
    check("E19: 배재 편입은 교양 연결 안 함(pick도 False), 전공만", CR.deficit_targets(2023, ra, True, True) == (["전공"], False))
    check("E19: 2025~ 공유혁신 부족은 공유혁신 영역, 편입이면 제외, 부족 없으면 빈 결과, 2025~에는 교양_비전설계 영역이 없어 교양 세부가 안 맞으면 pick",
          CR.deficit_targets(2025, [fa("공유혁신", 4)], False, False) == (["공유혁신"], False) and CR.deficit_targets(2025, [fa("공유혁신", 4)], True, False) == ([], False)
          and CR.deficit_targets(2025, [fa("교양", 0), fa("전공", 0)], False, True) == ([], False) and CR.deficit_targets(2025, [fa("교양", 3, [("교양_비전설계", 3.0)])], False, True) == ([], True))
    t_ = U_.abbr_html("교필선 (영역 표시 없음) · 교선 전체 · 전공필수 · 교양필수 · 혁신교육과미래설계 (전필, P/F)")
    check("E19: 약어 툴팁 — 교필선·교선·전필에 풀이(title), '전공필수'·'교양필수' 같은 풀이된 말에는 안 붙음",
          'title="교양필수선택(영역을 골라 듣는 교양)">교필선</abbr>' in t_ and 'title="교양선택">교선</abbr>' in t_ and 'title="전공필수">전필</abbr>' in t_ and t_.count("<abbr") == 3 and "전공필수 ·" in t_
          and all(k in U_.ABBR_HELP for k in ("교필=교양필수", "교필선=", "교선=교양선택", "전필=전공필수", "전선=전공선택", "일선=일반선택")))
    # 1-9d. E19b 표시 이름: 기준표 항목 코드는 그대로, 화면 이름은 개설 과목 영역 이름과 같은 표를 쓴다
    names_ = set()
    for u_ in S.BASE_DEPT:
        for y_ in range(2022, 2027):
            for a_ in S.area_plan(u_, S.BASE_DEPT[u_], y_)["areas"]:
                names_ |= {a_["name"]} | {c_["항목"] for c_ in a_["children"]}
    check("E19b: 5개 대학 × 2022~2026학번 모든 영역·세부 항목 이름이 화면 이름에서 '교양_'·'공유혁신_'·밑줄 없음", all("_" not in CR.item_label(n_) and not CR.item_label(n_).startswith("교양_") for n_ in names_)
          and len(names_) > 20, str(sorted(n_ for n_ in names_ if "_" in CR.item_label(n_))))
    check("E19b: 표시 이름 대응(개설 과목 영역 이름과 같은 표) — 글로벌-언어·글로벌-세계시민·글쓰기와토론·미래와기술·균형학문·비전설계·교양필수, 표에 없는 접두도 풀어서(전문기초·공유혁신 전공필수), 기준표 코드는 그대로",
          [CR.item_label(k_) for k_ in ("교양_글로벌언어", "교양_글로벌세계시민", "교양_글쓰기와토론", "교양_미래와기술", "교양_균형학문", "교양_비전설계", "교양필수")] == ["글로벌-언어", "글로벌-세계시민", "글쓰기와토론", "미래와기술", "균형학문", "비전설계", "교양필수"]
          and CR.item_label("교양_전문기초") == "전문기초" and CR.item_label("공유혁신_전공필수") == "공유혁신 전공필수" and CR.item_label("전공") == "전공" and "교양_글로벌언어" in names_
          and all(CR.ITEM_LABEL[k_] == CR.AREA_LABEL[k_] for k_ in CR.ITEM_LABEL))
    # 1-9. 배재 개설 과목(가공본이 있을 때만): 파일 659분반, 영역 분류, 공유혁신 분리, 요일 파싱, 제한 배지
    if not CR.available():
        skip("개설 과목 로직 점검: data/courses_baejae_2026-2.json 없음(build_courses.py로 생성)")
    else:
        secs = CR.load()

        def cnt(key):
            ss = [x for x in secs if key(x)]
            return len({x["과목코드"] for x in ss}), len(ss)
        check("개설 과목: 분반 659, 파일별 분반 16·111·119·48·153·212", len(secs) == 659 and [cnt(lambda x, f=f: x["파일"] == f)[1] for f in ("IT경영정보", "공유혁신", "공유대학가상", "교필", "교필선", "교선")] == [16, 111, 119, 48, 153, 212])
        want = {"전공": (16, 16), "교양필수": (5, 48), "교양_글로벌언어": (8, 41), "교양_글로벌세계시민": (18, 18), "교양_글쓰기와토론": (6, 14), "교양_미래와기술": (11, 20),
                "교양_균형학문": (55, 58), "교선": (87, 212), "교양_영역미표시": (2, 2), "타학과전공": (84, 119)}
        got = {k: cnt(lambda x, k=k: x["영역"] == k) for k in want}
        check("개설 과목: 영역별 과목·분반 수(전공 16/16, 교필 5/48, 글로벌언어 8/41, 세계시민 18/18, 글쓰기 6/14, 미래기술 11/20, 균형학문 55/58, 교선 87/212, 영역미표시 2/2, 가상 84/119)", got == want, str(got))
        inv = {k: cnt(lambda x, k=k: x["영역"] == k) for k in ("공유혁신_전공융합설계", "공유혁신_비전설계", "공유혁신_혁신교육과미래설계", "공유혁신_미분류")}
        check("개설 과목: 공유혁신 분리 — 전공융합설계 32/67, 비전설계 22/22(진로·취창업 15 + 자기설계 7), 혁신교육과미래설계 1/10, 미분류 11/12, 합 분반 111",
              inv == {"공유혁신_전공융합설계": (32, 67), "공유혁신_비전설계": (22, 22), "공유혁신_혁신교육과미래설계": (1, 10), "공유혁신_미분류": (11, 12)}
              and cnt(lambda x, **k: x["영역"] == "공유혁신_비전설계" and x["하위"] == "진로·취창업") == (15, 15) and cnt(lambda x: x["영역"] == "공유혁신_비전설계" and x["하위"] == "자기설계") == (7, 7), str(inv))
        check("개설 과목: 학번별 영역 — 2022~2024는 교양_비전설계(공유혁신 없음), 2025~는 공유혁신(비전설계 없음), 범위 밖은 빈 목록",
              "교양_비전설계" in CR.view_areas(2023) and "공유혁신" not in CR.view_areas(2023) and "공유혁신" in CR.view_areas(2026) and "교양_비전설계" not in CR.view_areas(2026) and CR.view_areas(engine.OUT_OF_RANGE) == [] and CR.view_areas(None) == [])
        check("개설 과목: 2025~ 공유혁신 영역 = 전공융합설계+비전설계+혁신교육과미래설계 99분반(미분류 12분반은 제외, 기타 영역에서 따로 보임)",
              len(CR.sections_in(secs, 2025, "공유혁신")) == 99 and len(CR.sections_in(secs, 2025, "공유혁신_기타")) == 12 and len(CR.sections_in(secs, 2023, "교양_비전설계")) == 22)
        kinds_ = {}
        for x in secs:
            kinds_[CR.time_kind(x["시간"])[0]] = kinds_.get(CR.time_kind(x["시간"])[0], 0) + 1
        check("개설 과목: 시간 파싱 요일 510·시간 미정 149('(?)')·실패 0", kinds_ == {"요일": 510, "미정": 149}, str(kinds_))
        check("개설 과목: 시간 문자열 예(월(5, 6)·화(C), 목(D)·(?)·빈 칸·여러 강의실)", CR.parse_days("A117 [월(5, 6)]") == ["월"] and CR.parse_days("MC208 [화(C), 목(D)]") == ["화", "목"]
              and CR.time_kind("(?)")[0] == "미정" and CR.time_kind("")[0] == "미정" and CR.parse_days("K301 [목(1, 2, 3), 금(1, 2, 3)]") == ["목", "금"] and CR.time_kind("미정 문자열")[0] == "실패")
        pos = ["외국인 유학생 전용", "2,3,4학년 수강제한/대학설계", "조경학과만 수강 가능", "타전공 학생만 수강 가능", "1학년 외 수강제한", "평생교육융합학부 전용 / 타학과 수강 금지", "수강 불가"]
        neg = ["전공융합설계-인문사회계열(일본학과)/타전공 수강 가능", "1~2학년 수강 교과목, 잔여 여석 발생 시 3학년 수강 가능", "(AI와SW영역) 자율전공학부, 운동재활복지학과 수강/042-520-5619", "조경학과A, 재수강자 신청가능 분반/042-520-5619", "", "수강 인원 0명으로 운영"]
        check("개설 과목: 강한 제한 문구 판정(전용·수강제한·○○만 수강·외 수강·수강 금지는 배지, '타전공 수강 가능'·'3학년 수강 가능'·학과 나열·빈 비고는 배지 없음)",
              all(CR.is_strong_limit(t) for t in pos) and not any(CR.is_strong_limit(t) for t in neg))
        check("개설 과목: 배지 분반 225/659(34%)(파일별 IT경영 0·공유혁신 32·가상 65·교필 9·교필선 88·교선 31)", sum(1 for x in secs if x["제한"]) == 225 and [sum(1 for x in secs if x["제한"] and x["파일"] == f) for f in ("IT경영정보", "공유혁신", "공유대학가상", "교필", "교필선", "교선")] == [0, 32, 65, 9, 88, 31])
        gcnt = {g: len({x["과목코드"] for x in secs if x["영역"] == "전공" and x["대상학년"] == g}) for g in CR.GRADES}
        check("개설 과목: 전공 대상 학년별 과목 수 1학년 3·2학년 4·3학년 3·4학년 6, 합계 16, 전공 분반 모두 학년이 있고 교양·공유혁신·가상에는 학년이 없음",
              gcnt == {"1학년": 3, "2학년": 4, "3학년": 3, "4학년": 6} and sum(gcnt.values()) == 16 and all(x["대상학년"] for x in secs if x["영역"] == "전공") and not any(x["대상학년"] for x in secs if x["영역"] != "전공"), str(gcnt))
        gm_ = {x["과목코드"]: x["대상학년"] for x in secs if x["영역"] == "전공"}
        check("개설 과목: 학년은 과목코드로 추측하지 않고 학년 파일 값(현장훈련1 EBS26601·졸업(종합)설계 EBS25401은 4학년, 코드 숫자와 다름)", gm_["EBS26601"] == "4학년" and gm_["EBS25401"] == "4학년" and gm_["EBS22107"] == "1학년")
        base_ = [("A1", "가", "전필"), ("A2", "나", "전선")]
        errs = 0
        for per_, label in (({"1학년": [("A1", "가", "전필")], "2학년": [("A2", "나", "전선"), ("A3", "다", "전선")]}, "코드 집합 다름(학년 쪽이 많음)"),
                            ({"1학년": [("A1", "가", "전필")]}, "코드 집합 다름(학년 쪽이 적음)"),
                            ({"1학년": [("A1", "가", "전필"), ("A2", "나", "전선")], "2학년": [("A2", "나", "전선")]}, "한 과목이 두 학년"),
                            ({"1학년": [("A1", "가", "전선")], "2학년": [("A2", "나", "전선")]}, "이수구분 다름")):
            try:
                CR.build_grade_map(per_, base_)
            except ValueError:
                errs += 1
        check("개설 과목: 학년 파일과 기존 전공 파일의 과목코드 집합·이름·이수구분이 다르거나 한 과목이 두 학년에 있으면 실패(ValueError) 4/4, 같으면 통과",
              errs == 4 and CR.build_grade_map({"1학년": [("A1", "가", "전필")], "2학년": [("A2", "나", "전선")]}, base_) == {"A1": "1학년", "A2": "2학년"})
        mon = [c for c in CR.group_courses(CR.sections_in(secs, 2023, "교선")) if CR.filter_sections(c, ["월"])]
        check("개설 과목: 요일 필터 — 월 선택 시 월요일 분반만, '시간 미정'은 따로 선택해야 나옴", all("월" in x["요일"] for c in mon for x in CR.filter_sections(c, ["월"]))
              and all(not x["요일"] for c in CR.group_courses(CR.sections_in(secs, 2023, "교선")) for x in CR.filter_sections(c, ["시간 미정"])))


def cmd_citations():
    """답 속 [n]과 카드 번호: 카드에는 모델이 본 원래 번호를 붙이고(다시 매기지 않음), 답 속 [n]은 모두 카드 번호 중에 있어야 한다.
    eval/results의 실제 답변(개발용 문항, 조회·계산·RAG 경로) 전체와 단위 사례로 본다. API 비용 0."""
    import csv
    import re
    import chromadb
    row = {"검색청크": "a;b;c;d;e", "인용": "3"}
    check("카드 번호: 인용 [3]은 3번 청크 c(1부터 다시 매기지 않음)", engine.cited_pairs(row, "답이에요.[3]") == [(3, "c")])
    check("카드 번호: 인용 목록에 없어도 답에 [2]가 있으면 카드에 포함", engine.cited_pairs(row, "답이에요.[3] 더[2]") == [(2, "b"), (3, "c")])
    check("카드 번호: 범위 밖 번호([9])는 카드로 만들지 않는다", engine.cited_pairs(row, "[3][9]") == [(3, "c")])
    check("카드 번호: 조회·계산 경로는 인용이 없으면 넘어온 행 전부", engine.cited_pairs({"검색청크": "x;y", "인용": ""}, "답", True) == [(1, "x"), (2, "y")])
    check("카드 번호: RAG 경로는 인용이 없으면 카드 없음", engine.cited_pairs({"검색청크": "x;y", "인용": ""}, "답", False) == [])
    eng = engine.Engine.__new__(engine.Engine)
    eng.col = chromadb.PersistentClient(path=str(R.CHROMA_DIR)).get_collection(R.COLLECTION)
    ok_routes = ("criteria-lookup", "criteria-calc", R.COLLECTION)
    checked = bad_missing = bad_nocard = 0
    bad = []
    for f in sorted((ROOT / "eval" / "results").glob("*_dev_base-rag_*.csv")):
        if "_grade-" in f.name or "_report-" in f.name:
            continue
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            if r.get("컬렉션") not in ok_routes or not r.get("검색청크"):
                continue
            body, _ = engine.split_answer(r["답변"])
            retrieved_n = len([i for i in r["검색청크"].split(";") if i])
            sources, _ = eng._sources_and_badges(r, body)
            shown = {n for s in sources for n in s["nums"]}
            cited = {int(n) for n in re.findall(r"\[(\d+)\]", body) if 1 <= int(n) <= retrieved_n}
            checked += 1
            if not cited <= shown:
                bad.append((f.name[-28:], r["id"], sorted(cited - shown)))
            if any(not s["nums"] for s in sources):
                bad.append((f.name[-28:], r["id"], "번호 없는 카드"))
    check(f"답 속 [n]이 모두 카드 번호 중에 있다 (실제 답변 {checked}건: 조회·계산·RAG)", checked > 100 and not bad, f"{len(bad)}건 {bad[:4]}")


def cmd_app():
    """화면 스모크(streamlit AppTest). 엔진은 가짜, 로그 DB는 임시 파일이라 API 비용 0. 8단계 동결 확인에도 쓴다.
    새 디자인(졸업나침반): 메뉴 5개 페이지·홈 요약 카드·입력값 유지·홈=페이지 값 일치·개발자 모드 분리를 본다."""
    import os
    import re
    import sqlite3
    import tempfile
    os.environ["SERVICE_LOG_DB"] = os.path.join(tempfile.mkdtemp(), "log.db")
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    APP = str(ROOT / "src" / "app.py")
    calls = []

    class Fake:
        badge = True
        leak = False  # E24d: True면 답 본문에 행 ID를 적고 잠정·학과확인필요 배지에 rids를 달아 화면 정리를 시험한다

        def answer(self, q, univ=None, year=None, dept=None):
            calls.append((q, univ, year, dept))
            if Fake.leak:
                return {"answer": "부전공은 54학점(HN-026)이에요. 근거는 [1] 입니다.\n\n자세한 설명이에요(기준표 HN-020).", "tail": "", "sources": [
                    {"kind": "기준표", "id": "HN-001", "nums": [1], "title": "한남 기준표 · 졸업학점", "target": "전체", "value": "120학점 이상", "status": "확정",
                     "article": "학칙 제41조", "pages": "20", "grade": "A 규정 원문"}],
                    "badges": [{"kind": "잠정", "text": "이 값은 잠정이에요 (학과 확인)", "rids": ["HN-026"]}, {"kind": "학과확인필요", "text": "출처마다 값이 달라요 (학과 확인)", "rids": ["HN-020", "HN-024"]}],
                    "route": "조회", "cost_usd": 0.001, "latency_ms": 900, "question_used": "한남대 학생: " + q, "used_dept": False, "calc_text": "54+21=75 (HN-026)",
                    "tokens_in": 1, "tokens_out": 1, "embed_tokens": 1}
            body = "첫 문단이에요. " * 10 + "\n\n" + "둘째 문단 자세한 설명이에요. " * 25
            return {"answer": body, "tail": "출처: [1] 학칙", "sources": [
                {"kind": "기준표", "id": "HN-001", "nums": [1], "title": "한남 기준표 · 졸업학점", "target": "전체", "value": "120학점 이상", "status": "확정",
                 "article": "학칙 제41조", "pages": "20", "grade": "A 규정 원문"},
                {"kind": "규정", "id": "c1", "nums": [3], "title": "학칙", "article": "제5조", "pages": "PDF 3쪽", "grade": "A 규정 원문", "edition": "현행(2026)", "univ": "한남"}],
                "badges": [{"kind": "확인불가", "text": "확인되지 않은 내용"}] if Fake.badge else [], "route": "조회", "cost_usd": 0.0012, "latency_ms": 900,
                "question_used": "한남대 학생: " + q, "used_dept": False, "calc_text": "72-66=6", "tokens_in": 1, "tokens_out": 1, "embed_tokens": 1}

    saved = engine.Engine
    engine.Engine = Fake
    st.cache_resource.clear()
    try:
        def run(dev=False):
            at = AppTest.from_file(APP, default_timeout=120)
            if dev:
                at.query_params["dev"] = "1"
            return at.run()

        def pick(at, univ=None, year=None, entry=None, dept=True):
            """대학·학번·입학 구분을 고른다. E24b: 학과는 처음에 비어 있으므로 dept=True(기본)면 그 학교 경영 계열 학과를 골라 기존 점검과 같게 한다.
            dept=False면 학과를 안 고른 채(첫 화면 그대로), dept='이름'이면 그 학과(목록에 없으면 비워 둔다)."""
            if univ:
                at.sidebar.selectbox(key="univ").set_value(univ)
                at.run()
            if year is not None:
                at.sidebar.selectbox(key="year").set_value(year)
                at.run()
            if entry:
                at.sidebar.radio(key="entry").set_value(entry)
            at.run()
            if dept:
                u_ = at.sidebar.selectbox(key="univ").value
                sel_ = at.sidebar.selectbox(key=f"dept_{u_}")
                d_ = S.BASE_DEPT[u_] if dept is True else dept
                if d_ in sel_.options:
                    sel_.set_value(d_)
                    at.run()
            return at

        def nav(at, page):
            at.sidebar.button(key=f"nav_{page}").click()
            at.run()
            return at

        def texts(els):
            return " ".join(e.value for e in els)

        def html(at):  # 화면에 나온 모든 마크다운(HTML 부품 포함)
            return texts(at.markdown) + " " + texts(at.caption)

        def html_outside(at):  # 접기(expander) 안을 뺀 본문 마크다운
            inner = {id(m) for e in at.expander for m in e.markdown}
            return " ".join(m.value for m in at.markdown if id(m) not in inner)

        def expander(at, label):
            hits = [e for e in at.expander if e.label == label]
            return hits[0] if hits else None

        def big(at):  # 큰 숫자 '졸업까지 남은 학점'
            m = re.findall(r'class="bignum">([\d.]+)<', html(at))
            return m[0] if m else None

        def area_sum(at):
            return {x.label: x.value for x in at.metric}.get("영역별 남은 학점의 합(참고)")

        at = run()
        labels = [b.label for b in at.sidebar.button]
        check("화면: [E22] 첫 화면 예외 없음·메뉴 5개 이름·순서(시작하기·규정 질문·내 졸업요건·학사 선택 비교·이번 학기 개설 과목), 개발자 메뉴 없음, 메뉴 아이콘 없음",
              not at.exception and labels == ["시작하기", "규정 질문", "내 졸업요건", "학사 선택 비교", "이번 학기 개설 과목"] and all(not b.proto.icon for b in at.sidebar.button), str(labels))
        import re as _re
        import ui_style
        hide_rules = [r for r in _re.findall(r"([^{}]+)\{([^{}]*)\}", _re.sub(r"/\*.*?\*/", "", ui_style.CSS, flags=_re.S))
                      if "display:none" in r[1].replace(" ", "")]
        hidden = " ".join(r[0] for r in hide_rules)
        check("화면: 사이드바 펼치기·접기 버튼과 도구 막대·헤더를 숨기는 CSS 규칙이 없다(메뉴·배포 버튼만 개별로 숨김)",
              not any(k in hidden for k in ("stExpandSidebarButton", "stSidebarCollapseButton", "stToolbar\"", "stToolbarActions", "stHeader\"", "stSidebar\"", "stSidebarCollapsedControl"))
              and "stMainMenu" in hidden and "stAppDeployButton" in hidden and "InputInstructions" in hidden, hidden[:120])
        src_app = (ROOT / "src" / "app.py").read_text(encoding="utf-8")
        check("화면: set_page_config에 initial_sidebar_state=\"expanded\"", 'initial_sidebar_state="expanded"' in src_app)
        h = html(at)
        sbm = texts(at.sidebar.markdown)
        check("화면: [E22] 사이드바에 서비스명, 중복 문구(5개 대학 안내·지원 범위 한 줄·학점 저장 안내)는 없고 기록 고지 한 줄만",
              "졸업나침반" in sbm and "5개 대학의 학사 규정을 근거로 답변해요" not in sbm and "입력한 학점·평점은 저장하지 않아요" not in sbm
              and "질문 문장은 서비스 개선을 위해 기록돼요." in sbm and "모든 학과가 규정 안내와 졸업요건 확인을 쓸 수 있어요" not in texts(at.sidebar.caption), sbm[:80])
        check("화면: [E22] 시작하기 — 제목·한 줄 소개·4단계(채운 원 2 + 빈 원 2, 선택·배재대 칩)·3상황·회색 상자 3줄(노랑 확인 불가 칩), 상단 머리글·옛 카드·지원 범위 표 없음",
              all(k in h for k in ("졸업나침반 시작하기", "대전 5개 대학의 졸업요건을, 학칙·세칙 근거와 함께 확인하는 곳이에요.", "이렇게 써 보세요", "왼쪽에서 내 정보를 골라요", "내 졸업요건을 확인해요",
                                   "이수 학점을 넣으면 남은 학점이 보여요", "부족한 영역의 이번 학기 과목을 찾아요", "이럴 때 쓰세요", "알아 두세요", "'근거 보기'에서 규정명·조항·쪽을 볼 수 있어요.",
                                   "2022~2026학번 기준이에요. 최종 확인은 학과 사무실에서 하세요. 입력한 학점은 저장하지 않아요."))
              and h.count('class="stp-no') == 4 and h.count('class="stp-no on"') == 2 and 'class="stp-tag">선택<' in h and 'class="stp-tag">배재대<' in h
              and h.count('class="sit-q"') == 3 and "부전공이랑 복수전공 중에 뭐가 덜 힘들지?" in h and "휴학은 몇 학기까지 되지? 재수강은?" in h and "편입하면 몇 학점 인정받고, 뭘 더 들어야 하지?" in h
              and "b-warn" in h and "확인 불가" in h and 'class="topbar"' not in h and "지원 범위" not in h and "학사 규정 질문" not in h and "내 졸업요건 자세히 보기" not in h and not at.text_input, h[:80])
        check("화면: [E22] 시작하기 버튼 4개(내 졸업요건 보기 → · 학사 선택 비교 → · 규정 질문 → 2개)만, 질문 입력칸·큰 숫자 없음",
              [b.label for b in at.button if b.key and b.key.startswith(("go_req", "go_sit"))] == ["내 졸업요건 보기 →", "학사 선택 비교 →", "규정 질문 →", "규정 질문 →"] and big(at) is None)
        check("화면: 학번 선택지는 2022~2026 + 모름 + 범위 밖(자유 입력 없음)", at.sidebar.selectbox(key="year").options == ["2022학번", "2023학번", "2024학번", "2025학번", "2026학번", "모름", "범위 밖"]
              and not at.sidebar.number_input)
        bad = []
        for u in S.BASE_DEPT:
            for y in [*S.YEARS, "모름", "범위 밖"]:
                for en in ("신입", "편입"):
                    pick(at, u, y, en)
                    for pg in ("home", "ask", "remaining", "compare", "courses"):
                        nav(at, pg)
                        if at.exception:
                            bad.append((u, y, en, pg, at.exception[0].value[:60]))
                    nav(at, "home")
        check("화면: 대학 5 × 학번 선택 7 × 입학 구분 2 × 페이지 5 = 350조합 예외 없음", not bad, str(bad[:3]))
        # 홈 = 남은 학점 페이지: 배재 2023 · 편입 · 총 125 → 5
        at = pick(run(), "배재", 2023, "편입")
        side = texts(at.sidebar.info)
        check("화면: 배재 편입이면 학번 아래에 한 줄 안내(2년 앞 학번·2023학번 예시)", side == "편입생은 2년 앞 학번을 고르세요. (예: 2025년 편입 → 2023학번)", side[:80])
        e = [x for x in at.sidebar.expander if x.label == "근거 보기"]
        check("화면: 배재 편입 안내의 근거 접기(제17조 ⑦·제64조 ④·해석 명시)", len(e) == 1 and "제17조 ⑦" in texts(e[0].markdown) and "제64조 ④" in texts(e[0].markdown) and "해석" in texts(e[0].markdown))
        nav(at, "remaining")
        check("화면: 총 이수 학점을 넣기 전에는 큰 숫자 없음(시안 값 하드코딩 없음)", big(at) is None and "총 이수 학점을 입력하면" in html(at))
        at.number_input(key="tot|배재|2023|IT경영정보학과").set_value(125)
        at.run()
        check("화면: 큰 숫자는 하나뿐(st.metric 없음)·125 → 5, 편입 안내 표시, 근거는 접기",
              big(at) == "5" and not at.metric and "편입 인정학점(최대 65학점)도 총 이수 학점에 포함해 넣어 주세요" in html(at) and expander(at, "근거 보기") is not None and "130학점 이상" in html(at), str(big(at)))
        nav(at, "home")
        nav(at, "remaining")
        check("화면: 다른 페이지에 갔다 와도 넣은 125가 입력칸에 남고 큰 숫자 5", at.number_input(key="tot|배재|2023|IT경영정보학과").value == 125 and big(at) == "5")
        at.number_input(key="tot|배재|2023|IT경영정보학과").set_value(120)
        at.run()
        check("화면: 바꾼 값(120) → 큰 숫자 10", big(at) == "10", str(big(at)))
        nav(at, "remaining")
        at.number_input(key="tot|배재|2023|IT경영정보학과").set_value(125)
        at.run()
        # 영역 입력 유지·참고 문구
        at.number_input(key="done|배재|2023|IT경영정보학과|교양").set_value(5)
        at.number_input(key="done|배재|2023|IT경영정보학과|전공").set_value(48)
        at.run()
        check("화면: [E15] 배재 편입 영역 입력 후에도 큰 숫자는 5, 영역별 합은 전공을 편입 기준 45로 계산해 31(교양 31 + 전공 0)", big(at) == "5" and area_sum(at) == "31" and expander(at, "영역별 결과 (참고)") is not None, f"{big(at)} {area_sum(at)}")
        check("화면: [E15] 전공 입력이 기준 45를 넘으면 '전공 기준 45학점 중 0학점 남았어요'(행 ID는 일반 모드에서 안 보임, E24d)", "전공 기준 <b>45학점</b> 중 <b>0학점</b> 남았어요" in html(at) and "BJ-049" not in html(at), html(at)[-200:])
        ref = expander(at, "참고")
        rt = texts(ref.markdown) if ref else ""
        check("화면: [E15] 편입 '참고'에는 편입 전공 기준 안내가 있고, 영역 미지정 학점(28) 안내는 없다(교양 표 불일치 34↔36은 교양 기준이 그대로라 남음)", "편입 전공 기준" in rt and "28학점" not in rt and "전공 세부 항목" not in rt, rt[:120])
        at_n = pick(run(), "배재", 2023, "신입")
        nav(at_n, "remaining")
        at_n.number_input(key="tot|배재|2023|IT경영정보학과").set_value(125)
        at_n.number_input(key="done|배재|2023|IT경영정보학과|교양").set_value(5)
        at_n.number_input(key="done|배재|2023|IT경영정보학과|전공").set_value(48)
        at_n.run()
        ref = expander(at_n, "참고")
        rt = texts(ref.markdown) if ref else ""
        check("화면: 신입은 영역별 합 49, '참고' 접기에 표 합계 불일치(34↔36)와 영역 미지정 학점 28을 쉬운 말로", area_sum(at_n) == "49" and "34학점" in rt and "36학점" in rt and "28학점" in rt and "학생이 할 일은 없어요" in rt, rt[:120])
        check("화면: 편입이면 영역별 확인은 참고용 안내", "참고용이에요" in texts(at.caption))
        check("화면: 남은 학점 화면의 개설 과목 카드는 요약+이동 버튼(목록은 개설 과목 페이지에만)", "이번 학기 개설 과목" in html(at) and "개설 과목 보기" in [b.label for b in at.button] and 'class="crs-sec"' not in html(at))
        nav(at, "home")
        nav(at, "remaining")
        check("화면: 페이지를 옮겼다 와도 영역 입력(교양 5·전공 48)과 총 이수 학점(125) 유지",
              at.number_input(key="done|배재|2023|IT경영정보학과|교양").value == 5 and at.number_input(key="done|배재|2023|IT경영정보학과|전공").value == 48
              and at.number_input(key="tot|배재|2023|IT경영정보학과").value == 125)
        # E15 회귀: 배재 2023 IT경영정보 편입 · 총 126 → 남은 4 · 전공 기준 45. 편입 학년 선택 칸은 없고 3학년 고정(E17b)
        at = pick(run(), "배재", 2023, "편입")
        check("화면: [E17b] 편입 학년 선택 칸이 없다(배재 편입·한남 편입·배재 신입 모두), 편입 안내에 24학점 문구 없음",
              not [x for x in at.sidebar.radio if x.key == "transfer_grade"] and not [x for x in pick(run(), "한남", 2023, "편입").sidebar.radio if x.key == "transfer_grade"]
              and not [x for x in pick(run(), "배재", 2023, "신입").sidebar.radio if x.key == "transfer_grade"]
              and "24학점" not in texts(at.sidebar.info), texts(at.sidebar.info)[-90:])
        nav(at, "remaining")
        at.number_input(key="tot|배재|2023|IT경영정보학과").set_value(126)
        at.number_input(key="done|배재|2023|IT경영정보학과|전공").set_value(40)
        at.run()
        h = html(at)
        check("화면: [E15] 배재 2023 편입(3학년 고정) 총 126 → 남은 4, 전공 기준 45 중 5 남음, 인정학점 상한 65(130·3학년), 행 ID 없음(E24d)",
              big(at) == "4" and "전공 기준 <b>45학점</b> 중 <b>5학점</b> 남았어요" in h and "BJ-049" not in h and "최대 65학점" in h, h[-260:])
        check("화면: [E15] 체크리스트에 편입 요건(면제 안내·인성 이수·학사편입 안내)이 배지로, 채플(2학년 전용)은 화면에 없다",
              "편입 전 필수과목 면제" in h and "b-info" in h and "기독교정신과아펜젤러인성 이수" in h and "편입 후 전공필수 이수" in h and "학사편입" in h and "채플" not in h and "✅" not in h, h[:60])
        check("화면: [E17b] 2학년·4학년 기준 값(상한 33·98, 전공 24)은 화면에 나오지 않는다(안내 문구의 '전공 24학점' 제외)",
              "최대 33학점" not in h and "최대 98학점" not in h and "BJ-050" not in h and "전공 기준 <b>24학점</b>" not in h)
        at = pick(run(), "배재", 2023, "신입")
        nav(at, "remaining")
        h = html(at)
        check("화면: [E15] 신입에게는 편입 요건·인정학점 상한이 안 보인다", "편입 전 필수과목 면제" not in h and "최대 65학점" not in h and "전공 기준 <b>" not in h)
        ids = {r["행ID"] for r in L.CRITERIA}
        check("기준표: [E15] 배재 편입 행 BJ-049~063 15개(060~063은 항목원어 제목), 항목은 모두 '편입_' 접두, 조건에 '이수 필수' 문구 없음(규칙 12 충돌 방지)",
              all(f"BJ-{i:03d}" in ids for i in range(49, 64)) and all(L.BY_ID[f"BJ-{i:03d}"]["항목"].startswith("편입_") and "이수 필수" not in L.BY_ID[f"BJ-{i:03d}"]["조건"] for i in range(49, 64)) and all(L.BY_ID[f"BJ-{i:03d}"]["항목원어"] for i in range(60, 64)) and L.BY_ID["BJ-063"]["출처등급"] == "B")
        # 편입 + 영역만 입력(총 비움) → 큰 숫자 없이 총 입력 요청
        at = pick(run(), "배재", 2024, "편입")
        nav(at, "remaining")
        at.number_input(key="done|배재|2024|IT경영정보학과|교양").set_value(5)
        at.run()
        check("화면: 편입 + 영역만 입력하면 큰 숫자 없이 '총 이수 학점을 먼저' 안내", big(at) is None and "총 이수 학점을 먼저 입력" in html(at), str(big(at)))
        # 신입: 총 비움 + 영역 입력 → 영역 합으로 계산(충남 2024: 30+80+5=115 → 130-115=15)
        at = pick(run(), "충남", 2024, "신입")
        nav(at, "remaining")
        ks = [k for k in (x.key for x in at.number_input) if k.startswith("done|충남|2024|경영학부")]
        for k, v in zip(ks, (30, 80, 5)):
            at.number_input(key=k).set_value(v)
        at.run()
        check("화면: 신입은 총 칸이 비면 영역 합(115)으로 계산 → 15 + 안내 한 줄", len(ks) == 3 and big(at) == "15" and area_sum(at) == "17" and "영역 입력의 합(115학점)" in html(at), f"{big(at)} {area_sum(at)}")
        at.number_input(key="tot|충남|2024|경영학부").set_value(120)
        at.run()
        check("화면: 총 이수 학점을 넣으면 그 값이 우선(130−120=10)", big(at) == "10")
        # 사이드바 편입 안내: 학교별, 신입이면 없음
        at = pick(run(), "한남", 2023, "편입")
        check("화면: 한남 편입 안내('2년 앞 학번')·근거 접기 있음", "2년 앞 학번" in texts(at.sidebar.info) and len([x for x in at.sidebar.expander if x.label == "근거 보기"]) == 1, texts(at.sidebar.info)[:60])
        at = pick(run(), "한밭", 2023, "편입")
        check("화면: 한밭 편입 안내('2년 앞 학번')·근거 접기(웹페이지 C등급) 있음", "2년 앞 학번" in texts(at.sidebar.info) and len([x for x in at.sidebar.expander if x.label == "근거 보기"]) == 1, texts(at.sidebar.info)[:60])
        for u in ("충남", "목원"):  # 사이드바 한 줄만, 근거 접기 없음, 남은 학점·홈 화면에는 중복 줄 없음
            at = pick(run(), u, 2023, "편입")
            side = texts(at.sidebar.info)
            nav(at, "remaining")
            h_rem = html(at)
            nav(at, "home")
            h_home = html(at)
            check(f"화면: {u} 편입은 사이드바에 '{S.TRANSFER_CHECK_LINE}' 한 줄(근거 접기 없음), 남은 학점·홈 화면에는 같은 줄이 없다",
                  side == S.TRANSFER_CHECK_LINE and not [x for x in at.sidebar.expander if x.label == "근거 보기"] and S.TRANSFER_CHECK_LINE not in h_rem and S.TRANSFER_CHECK_LINE not in h_home, side[:60])
        check("화면: 신입이면 사이드바 편입 안내 없음", not pick(run(), "배재", 2023, "신입").sidebar.info)
        # 미지원 안내: 한밭·한남(T3), 경영 계열 외 학과 / 지원: 배재·충남
        for u in ("한밭", "한남"):
            at = pick(run(), u, 2023, "신입")
            nav(at, "remaining")
            at.number_input(key=f"tot|{u}|2023|{S.BASE_DEPT[u]}").set_value(100)
            at.run()
            check(f"화면: {u}(T3) 영역별 미지원 한 줄 안내 + 총 100 → 졸업까지 남은 학점·참고 표", "이 학과는 영역별 계산을 지원하지 않아요. 총 학점만 계산해요." in html(at) and big(at) is not None
                  and expander(at, "참고") is not None and not at.exception and expander(at, "영역별 확인 (선택)") is None, str(big(at)))
        NO_AREA = "이 학과는 영역별 계산을 지원하지 않아요. 총 학점만 계산해요."
        at = pick(run(), "배재", 2023, "신입", dept=False)
        sel = at.sidebar.selectbox(key="dept_배재")
        check("화면: [E24b] 학과 selectbox는 처음에 비어 있고(index=None) 선택지는 학과들 + 맨 아래 '목록에 없는 학과 (대학 공통 기준)', 라디오는 없다",
              sel.value is None and sel.placeholder == "학과를 검색하거나 고르세요" and sel.options[-1] == "목록에 없는 학과 (대학 공통 기준)" and "IT경영정보학과" in sel.options
              and not any(r.key and r.key.startswith("deptkind_") for r in at.sidebar.radio), str(sel.options[:2]))
        for pg, what in (("remaining", "내 졸업요건"), ("compare", "비교 결과")):
            nav(at, pg)
            h = html(at)
            check(f"화면: [E24b] 학과 미선택이면 {pg} 페이지는 '왼쪽에서 학과를 고르면 {what}이 나와요.' 안내만(계산·체크리스트·비교 없음)", not at.exception and f"왼쪽에서 학과를 고르면 {what}이 나와요." in h and big(at) is None
                  and "학점 외 이수 요건" not in h and "<th>전공학점 합</th>" not in h and len(at.number_input) == 0 and "학과 미선택" in h, h[:60])
        at = nav(at, "ask")
        at.text_input(key="q_ask").set_value("재수강은 몇 학점까지 할 수 있어?")
        at.run()
        check("화면: [E24b] 학과 미선택이어도 규정 질문 페이지는 그대로 쓸 수 있다(학과 없이 대학 공통 기준으로 엔진 호출)", not at.exception and at.text_input(key="q_ask") is not None, "")
        at = pick(run(), "목원", 2024, "신입", dept="응급구조학과")
        check("화면: [E24b] 목원 2024에서 응급구조학과를 고르면 그 학과 기준이 나온다", at.sidebar.selectbox(key="dept_목원").value == "응급구조학과" and not at.exception)
        at.sidebar.selectbox(key="year").set_value(2022)
        at.run()
        check("화면: [E24b] 학번을 2022로 바꾸면 새 목록에 없는 이전 학과(응급구조학과)는 빈칸으로 초기화(기본 학과로 되돌리지 않음)·안내가 나온다",
              at.sidebar.selectbox(key="dept_목원").value is None and "응급구조학과" not in at.sidebar.selectbox(key="dept_목원").options and not at.exception)
        at = pick(run(), "목원", 2024, "신입", dept="경영학부")
        at.sidebar.selectbox(key="year").set_value(2023)
        at.run()
        check("화면: [E24b] 학번을 바꿔도 새 목록에 있는 학과(경영학부)는 그대로 유지", at.sidebar.selectbox(key="dept_목원").value == "경영학부")
        at.sidebar.selectbox(key="univ").set_value("배재")
        at.run()
        check("화면: [E24b] 학교를 바꾸면 그 학교 학과 칸은 비어 있다(이전 학교 학과가 새 학교로 새지 않는다)", at.sidebar.selectbox(key="dept_배재").value is None and not at.exception)
        for u, y, want in (("배재", 2023, 130), ("배재", 2025, 127), ("충남", 2023, 130), ("한밭", 2023, 130), ("목원", 2022, 132), ("목원", 2023, 126)):
            at = pick(run(), u, y, "신입", dept="목록에 없는 학과 (대학 공통 기준)")
            at.sidebar.selectbox(key=f"dept_{u}").set_value("목록에 없는 학과 (대학 공통 기준)")
            at.run()
            nav(at, "remaining")
            h = html(at)
            check(f"화면: [학과] {u} {y} '목록에 없는 학과' → 대학 공통 졸업학점 {want}학점, 대학 공통 안내·영역별 미지원 한 줄", f"졸업학점 <b>{want}학점 이상</b>" in h and "대학 공통 기준이에요" in h and NO_AREA in h
                  and "목록에 없는 학과(대학 공통)" in h and "영역별 확인 (선택)" not in [e.label for e in at.expander] and not at.exception, h[:80])
        at = pick(run(), "한남", 2023, "신입", dept=False)
        opts = at.sidebar.selectbox(key="dept_한남").options
        check("화면: [학과] 한남은 '목록에 없는 학과' 없이 계열 2개 + '학과가 속한 계열을 고르세요' 안내", "목록에 없는 학과 (대학 공통 기준)" not in opts and "인문사회계열" in opts and "이학·공학·예능·체능·간호계열" in opts
              and "학과가 속한 계열을 고르세요" in texts(at.sidebar.caption), str(opts))
        at.sidebar.selectbox(key="dept_한남").set_value("인문사회계열")
        at.run()
        nav(at, "remaining")
        check("화면: [학과] 한남 인문사회계열 → 졸업학점 120학점(HN-001)", "졸업학점 <b>120학점 이상</b>" in html(at), html(at)[:60])
        at = pick(run(), "한밭", 2024, "신입")
        nav(at, "remaining")
        check("화면: [정리] 신입에게 편입 전용 비교과 같은 '해당 없음' 항목은 기본 숨김, '해당 없는 요건 N개' 접기 안에만", any(e.label.startswith("해당 없는 요건") for e in at.expander)
              and "b-na" in " ".join(texts(e.markdown) for e in at.expander if e.label.startswith("해당 없는 요건")) and "해당 없음" not in html_outside(at))
        at = pick(run(), "배재", 2023, "신입")
        h_home = html(at)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        check("화면: [E22] 지원 범위 표는 화면(홈)에서 빠지고 README로 옮겼다, 사이드바 지원 범위 한 줄도 없음",
              "지원 범위" not in h_home and "각주 1" not in h_home and "지원 범위" in readme and "영역별 남은 학점" in readme and "모든 학과가 규정 안내와 졸업요건 확인을 쓸 수 있어요" not in texts(at.sidebar.caption))
        import ui_style as _us
        cfg = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
        check("화면: [E22] 스타일 — 사이드바 240px·메뉴 44px·남색 #1E3A8A·선 #E9E9E7·카드 8px, 그림자·그라데이션·옛 보라(#5B47C7) 없음, 테마 색도 남색",
              all(k in _us.CSS for k in ("width:240px", "min-height:44px", "#1E3A8A", "#E9E9E7", "border-radius:8px", "font-size:19px", "font-size:16px", "min-height:40px"))
              and "box-shadow:0" not in _us.CSS and "gradient" not in _us.CSS and "5B47C7" not in _us.CSS and "5B47C7" not in cfg.upper().replace("#", "#") and 'primaryColor = "#1E3A8A"' in cfg and 'baseRadius = "medium"' in cfg)
        import base64 as _b64
        _logo = (ROOT / "assets" / "logo.svg").read_bytes()
        _fav = (ROOT / "assets" / "favicon.svg").read_bytes()
        _brand = re.search(r"\.brand-ico\{[^}]*\}", _us.CSS).group(0)
        _hero = re.search(r"\.hero-ico\{[^}]*\}", _us.CSS).group(0)
        _app_src = (ROOT / "src" / "app.py").read_text(encoding="utf-8")
        check("화면: [로고] 사이드바 로고는 타일 없이 28px SVG(assets/logo.svg를 base64로 CSS에 넣음, 남색 배경 사각형·옛 CSS 아이콘 없음), 홈 hero는 48px 연한 박스 안 30px, 탭 아이콘은 favicon.svg, 글자 '졸업나침반' 그대로",
              b"<svg" in _logo and b"#F2A93B" in _logo and b"<svg" in _fav and b'stroke-width="5"' in _fav
              and "width:28px;height:28px" in _brand and "border-radius" not in _brand and "#1E3A8A" not in _brand.replace(_b64.b64encode(_logo).decode(), "") and _b64.b64encode(_logo).decode() in _brand
              and "width:48px;height:48px" in _hero and "center/30px 30px" in _hero and _b64.b64encode(_logo).decode() in _hero
              and "__LOGO__" not in _us.CSS and "favicon.svg" in _app_src and "🧭" not in _app_src
              and '<div class="brand-ico"></div><div class="brand-name">졸업나침반</div>' in (ROOT / "src" / "ui_pages.py").read_text(encoding="utf-8")
              and not at.exception)
        at = nav(pick(run(), "배재", 2023, "신입"), "remaining")
        check("화면: [정리] 배재 경영 계열은 영역별 미지원 안내 없음", NO_AREA not in html(at))
        check("화면: [정리] 남은 학점 위쪽에 '졸업학점 130학점 이상'만(대학·학번·학과 반복 없음)", 'class="card-sub">졸업학점 <b>130학점 이상</b></div>' in html(at))
        # 체크리스트: 초록 체크 없음, 배지로 표시
        at = nav(pick(run(), "배재", 2025, "신입"), "remaining")
        h = html(at)
        check("화면: 체크리스트에 초록 체크(✅)가 없고 '요건/없음/확인 불가/해당 없음' 배지만 쓴다",
              "✅" not in h and "✓" not in h and "b-req" in h and "학점 외 이수 요건" in h and ("확인 불가 · 학과 확인" in h or "b-none" in h or "b-na" in h), h[:80])
        # 학사 선택 비교: 페이지 값이 S.compare 결과와 같다(하드코딩 없음)
        for u, y, d in (("배재", 2024, None), ("한남", 2023, None), ("목원", 2022, "경영학부")):
            at = pick(run(), u, y, "신입", dept=d or True)
            r = S.compare(u, y, S.BASE_DEPT[u])
            at2 = nav(at, "compare")
            h2 = html(at2)
            can_ai = S.explain_question(u, y, S.BASE_DEPT[u] if not d else d) is not None  # 설명 질문이 안 만들어지는 조건(배재 등)에는 AI 설명 버튼이 없다
            ok2 = r["ok"] and all(f"{t['total']:g}학점" in h2 for t in r["table"] if t["total"] is not None) and (not r["less"] or (r["less"] in h2 and f"{r['diff']:g}학점" in h2)) \
                and "근거 행" not in h2 and ("AI 설명 듣기" in [b.label for b in at2.button]) == can_ai
            check(f"화면: {u} {y} 비교표·결론이 S.compare 결과({r['less']} {r.get('diff')})와 같다", ok2, h2[:60])
        # ---- E19b 홈 3단계 버튼 · 세부 항목 표시 이름 ----
        at = pick(run(), "배재", 2023, "신입")
        check("화면: [E22] 시작하기 단계 2의 링크형 버튼 → 내 졸업요건 페이지(① 졸업요건이 보임), 스크롤 표시·스크롤 보조(iframe)는 없음",
              not at.exception and "go_req" in [b.key for b in at.button], "")
        at.button(key="go_req").click().run()
        check("화면: [E22] 시작하기 → 내 졸업요건 버튼 → 졸업요건 페이지", "졸업하려면 이것들을 채워야 해요" in html(at) and "scroll_to" not in at.session_state["keep"] and not at.get("iframe") and not at.exception)
        for key, want in (("go_sit_1", "학사 선택 비교"), ("go_sit_2", "규정 질문"), ("go_sit_3", "규정 질문")):
            at = pick(run(), "배재", 2023, "신입")
            at.button(key=key).click().run()
            check(f"화면: [E22] 시작하기 상황 버튼 {key} → '{want}' 페이지(질문 미리 채우기 없음)", not at.exception and at.session_state["page"] == ("compare" if want == "학사 선택 비교" else "ask")
                  and (not at.text_input or at.text_input(key="q_ask").value == ""))
        KIDS_WANT = {"배재": "영역별 학점은 학교 포털 '졸업자가진단'에서 볼 수 있어요. 모르면 비워 두세요.",
                     "충남": "영역별 학점은 학교 포털 졸업사정(졸업 자가진단) 메뉴에서 확인하세요. 모르면 비워 두세요.", "목원": "영역별 학점은 학교 포털 졸업사정(졸업 자가진단) 메뉴에서 확인하세요. 모르면 비워 두세요."}
        for u_, y_ in (("배재", 2023), ("배재", 2025), ("충남", 2024), ("목원", 2023)):
            at = nav(pick(run(), u_, y_, "신입"), "remaining")
            cx_ = f"{u_}|{y_}|{S.BASE_DEPT[u_]}"
            at.number_input(key=f"tot|{cx_}").set_value(100).run()
            at.number_input(key=f"done|{cx_}|교양").set_value(10).run()
            at.checkbox(key=f"kids_on|{cx_}").check().run()
            kid_keys = [n.key for n in at.number_input if n.key.startswith(f"kid|{cx_}|")]
            at.number_input(key=kid_keys[0]).set_value(5).run()
            labels_ = " ".join(n.label for n in at.number_input)
            dfs_ = " ".join(str(d.value.to_dict()) for d in at.dataframe)
            check(f"화면: [E19b] {u_} {y_} 세부 항목 칸·결과 표·세부 항목 보기에 '교양_'이 안 남고, 칸 위 안내 한 줄",
                  "교양_" not in labels_ and "교양_" not in dfs_ and "교양_" not in html(at) and len(kid_keys) >= 3
                  and KIDS_WANT[u_] in texts(at.caption) and not at.exception, f"{labels_[:120]}")
        at = nav(pick(run(), "배재", 2023, "신입"), "remaining")
        at.checkbox(key="kids_on|배재|2023|IT경영정보학과").check().run()
        lab_ = " ".join(n.label for n in at.number_input)
        check("화면: [E19b] 배재 2023 세부 항목 이름이 개설 과목 화면과 같다(글로벌-언어·글로벌-세계시민·글쓰기와토론·미래와기술·균형학문·비전설계)", all(k_ in lab_ for k_ in ("글로벌-언어", "글로벌-세계시민", "글쓰기와토론", "미래와기술", "균형학문", "비전설계")))
        # ---- E19 내 졸업요건: 학점을 몰라도 쓸 수 있게 ----
        def keys_of(at_):
            return [b.key for b in at_.button]
        for u_, y_ in (("배재", 2023), ("충남", 2024), ("한남", 2024), ("한밭", 2024), ("목원", 2023)):
            at = nav(pick(run(), u_, y_, "신입"), "remaining")
            h = html(at)
            i1, i2 = h.find("졸업하려면 이것들을 채워야 해요"), h.find("이수 학점을 알면 남은 학점을 계산해 드려요 (선택)")
            check(f"화면: [E19] {u_} {y_} 입력 없이 졸업학점·영역 기준 표·체크리스트가 먼저 보이고(① 제목이 ② 앞), 큰 숫자는 없고 '학점을 몰라도' 안내",
                  0 <= i1 < i2 and "졸업학점 <b>" in h and "<th>영역</th>" in h and "학점 외 이수 요건" in h and big(at) is None
                  and "학점을 몰라도 위 졸업요건은 확인할 수 있어요" in texts(at.caption) and not at.exception, f"{i1} {i2}")
        at = nav(pick(run(), "한밭", 2024, "신입"), "remaining")
        h = html(at)
        check("화면: [E19] 한밭 교양은 '졸업학점의 25% 이상'(단위가 보임), 단독 '25% 이상' 칸 없음", "졸업학점의 25% 이상" in h and "<td>25% 이상</td>" not in h)
        # [2] 영역 기준 표 화면: 단수 안내 한 줄, (단수) 제거, 상위·하위 들여쓰기, 전공 합 한 줄, % 예시(소수 그대로)
        check("화면: [2] 한밭 표 위에 '복수전공·부전공을 하지 않을 때(단수전공) 기준이에요.' 한 줄, 이름 뒤 '(단수)' 없음",
              "복수전공·부전공을 하지 않을 때(단수전공) 기준이에요." in h and "(단수)" not in h)
        check("화면: [2] 한밭 기본전공·심화전공은 전공 아래 들여쓰기(class sub), '전공 72학점 이상 = 기본전공 + 심화전공' 한 줄",
              '<td class="sub">기본전공</td>' in h and '<td class="sub">심화전공</td>' in h and '<td>전공</td>' in h and "전공 72학점 이상 = 기본전공 + 심화전공" in h)
        check("화면: [2] 한밭 % 기준은 계산 예시 '졸업학점의 25% 이상 (130학점이면 32.5학점)'(올림 없음)", "졸업학점의 25% 이상 (130학점이면 32.5학점)" in h and "33학점" not in h)
        for u_, y_, kid in (("배재", 2023, "전공필수"), ("충남", 2024, "전공핵심"), ("목원", 2024, "교양필수")):
            h2 = html(nav(pick(run(), u_, y_, "신입"), "remaining"))
            check(f"화면: [2] {u_} {y_} 세부 항목({kid})도 영역 아래 들여쓰기, 단수 안내 한 줄", f'<td class="sub">{kid}</td>' in h2 and "복수전공·부전공을 하지 않을 때(단수전공) 기준이에요." in h2)
        h3 = html(nav(pick(run(), "한남", 2024, "신입"), "remaining"))
        check("화면: [2] 한남은 융합 유형이 같이 있어 이름 뒤 이수유형(단수·융합…)을 그대로 두고 단수 안내 한 줄은 없음",
              "교양 (단수)" in h3 and "전공 (융합전공)" in h3 and "복수전공·부전공을 하지 않을 때" not in h3)
        at = nav(pick(run(), "배재", 2023, "신입"), "remaining")
        e = [x for x in at.expander if x.label == "내 이수 학점은 어디서 보나요?"]
        check("화면: [E19] 배재 이수 학점 안내(졸업자가진단·소계), 목원은 졸업사정(졸업 자가진단) 안내", len(e) == 1 and "졸업자가진단" in texts(e[0].markdown) and "소계" in texts(e[0].markdown)
              and "졸업사정(졸업 자가진단)" in texts([x for x in nav(pick(run(), "목원", 2023, "신입"), "remaining").expander if x.label == "내 이수 학점은 어디서 보나요?"][0].markdown))
        at = nav(pick(run(), "목원", 2023, "신입"), "remaining")
        at.number_input(key="tot|목원|2023|경영학부").set_value(100).run()
        check("화면: [E19] 목원(배재 외)은 개설 과목 연결 버튼 없이 '배재대에서 시범 제공 중' 한 줄", not [k for k in keys_of(at) if k.startswith("crs_go")] and "개설 과목 연결은 배재대에서 시범 제공 중이에요." in html(at))
        if not CR.available():
            skip("E19 개설 과목 연결 화면 점검: data/courses_baejae_2026-2.json 없음(build_courses.py로 생성)")
        else:
            ctx_ = "배재|2023|IT경영정보학과"
            at = nav(pick(run(), "배재", 2023, "신입"), "remaining")
            check("화면: [E19] 영역 입력 전에는 개설 과목 연결 버튼 대신 '영역별 이수 학점까지 입력하면' 안내와 전체 보기 버튼", "crs_go_all" in keys_of(at) and "영역별 이수 학점까지 입력하면" in html(at) and not [k for k in keys_of(at) if k.startswith("crs_go_") and k != "crs_go_all"])
            at.number_input(key=f"tot|{ctx_}").set_value(100).run()
            at.number_input(key=f"done|{ctx_}|교양").set_value(10).run()
            at.number_input(key=f"done|{ctx_}|전공").set_value(30).run()
            ks = keys_of(at)
            check("화면: [E19] 배재 영역 부족 → 전공 버튼과 '교양 개설 과목 보기'(세부 입력 없음이라 영역을 미리 고르지 않음) + 고르라는 안내",
                  "crs_go_전공" in ks and "crs_go_pick" in ks and "crs_go_교양필수" not in ks and "부족한 교양 영역을 골라 보세요(세부 항목까지 입력하면 바로 이어져요)" in html(at), str([k for k in ks if k.startswith("crs")]))
            at.button(key="crs_go_전공").click().run()
            check("화면: [E19] 전공 버튼 → 개설 과목 페이지에 전공 영역이 미리 선택됨, 안내 없음", at.selectbox(key="crs_area_w").value == "전공" and "부족한 교양 영역을 골라 보세요" not in html(at) and not at.exception)
            at = nav(at, "remaining")
            at.button(key="crs_go_pick").click().run()
            check("화면: [E19] 교양 버튼 → 개설 과목 페이지로 이동만(영역 미리 고르지 않음, 직전 전공 선택은 그대로), 고르라는 안내, 영역을 고르면 안내가 사라짐",
                  "부족한 교양 영역을 골라 보세요(세부 항목까지 입력하면 바로 이어져요)" in html(at) and at.session_state["keep"].get("crs_area") == "전공")
            at.selectbox(key="crs_area_w").set_value("교선").run()
            check("화면: [E19] 영역을 고르면 안내가 사라짐", "부족한 교양 영역을 골라 보세요" not in html(at))
            at = nav(at, "remaining")
            at.checkbox(key=f"kids_on|{ctx_}").check().run()
            at.number_input(key=f"kid|{ctx_}|교양필수").set_value(11).run()
            ks = keys_of(at)
            check("화면: [E19] 세부 항목까지 입력하면 부족한 교양 세부 영역 버튼(교양_글로벌언어 등)이 생기고 교양 '고르세요' 버튼은 없다", "crs_go_교양_글로벌언어" in ks and "crs_go_교양_비전설계" in ks and "crs_go_pick" not in ks and "crs_go_교양필수" not in ks, str([k for k in ks if k.startswith("crs")]))
            at.button(key="crs_go_교양_글로벌언어").click().run()
            check("화면: [E19] 교양 세부 버튼 → 그 교양 영역(글로벌-언어)이 미리 선택됨", at.selectbox(key="crs_area_w").value == "교양_글로벌언어")
            at = nav(pick(run(), "배재", 2023, "편입"), "remaining")
            at.number_input(key=f"tot|{ctx_}").set_value(126).run()
            at.number_input(key=f"done|{ctx_}|전공").set_value(40).run()
            at.number_input(key=f"done|{ctx_}|교양").set_value(10).run()
            ks = keys_of(at)
            check("화면: [E19] 배재 편입은 교양 부족이어도 교양 버튼 없이 전공(편입 기준 45) 버튼만, 참고용 안내", "crs_go_전공" in ks and "crs_go_pick" not in ks and not [k for k in ks if k.startswith("crs_go_교양")]
                  and "교양 영역별 결과가 참고용이라 교양 개설 과목 연결은 하지 않아요" in html(at), str([k for k in ks if k.startswith("crs")]))
            at = nav(pick(run(), "배재", 2023, "신입"), "courses")
            h = html(at)
            check("화면: [E19] 개설 과목 목록에 약어 툴팁(전필·전선 title)과 영역 선택 도움말", 'title="전공필수">전필</abbr>' in h and 'title="전공선택">전선</abbr>' in h and "전필=전공필수" in " ".join(str(x.help) for x in at.selectbox))
        # E24d: 개발용 표기(평가셋·행 ID·'시작 비움')는 일반 모드 화면 어디에도 안 나오고, ?dev=1에서만 나온다
        LEAK_RE = re.compile(r"평가셋|(?:BJ|MW|HB|HN|CN)-\d{3}|시작 비움|근거 행")

        def screen_text(at_):
            parts = [html(at_)] + [texts(getattr(at_, k_)) for k_ in ("info", "warning", "error", "success", "text")]
            parts += [texts(at_.sidebar.info), texts(at_.sidebar.caption), texts(at_.sidebar.markdown)]
            for d_ in at_.dataframe:
                try:
                    parts.append(d_.value.to_csv())
                except Exception:
                    pass
            return " ".join(parts)
        E24D_CASES = [("한남", 2023, "경영정보학과", "신입"), ("충남", 2023, "경영학부", "신입"), ("배재", 2023, "IT경영정보학과", "신입"), ("한밭", 2024, "융합경영학과", "신입"),
                      ("목원", 2024, "응급구조학과", "신입"), ("한남", 2022, None, "신입"), ("배재", 2025, "IT경영정보학과", "신입"), ("배재", 2023, "IT경영정보학과", "편입")]
        leaks_ = []
        for u_, y_, d_, en_ in E24D_CASES:
            at = pick(run(), u_, y_, en_, dept=d_ if d_ else False)
            for pg_ in ("home", "remaining", "compare", "courses", "ask"):
                nav(at, pg_)
                for m_ in LEAK_RE.finditer(screen_text(at)):
                    leaks_.append((u_, y_, d_, pg_, m_.group(0)))
        check("화면: [E24d] 일반 모드 — 학교 5곳·학과·편입·미선택의 시작하기·내 졸업요건·학사 비교·개설 과목·규정 질문 화면 어디에도 '평가셋'·행 ID(BJ-/MW-/HB-/HN-/CN-)·'시작 비움'·'근거 행'이 없다",
              not leaks_, str(leaks_[:4]))
        at = nav(pick(run(), "한남", 2023, "신입"), "compare")
        check("화면: [E24d] 한남 부전공↔다전공 비교 — 학생용 안내 '부전공 없이 단수 54는 선택 불가(융합교육 필수)'는 남고 '평가셋 B03·H09·H10'·'근거 행'은 없다",
              "부전공 없이 단수 54는 선택 불가(융합교육 필수)" in screen_text(at) and "평가셋" not in screen_text(at) and "근거 행" not in screen_text(at))
        at = nav(pick(run(), "충남", 2023, "신입"), "remaining")
        check("화면: [E24d] 충남 졸업 평점 근거 — 의예과 노트는 남고 '평가셋 C05·C06·X03'·'시작 비움'은 없다", "의예과 2.0" in screen_text(at) and "C05" not in screen_text(at) and "시작 비움" not in screen_text(at))
        leaks_dev = {}
        at = nav(pick(run(dev=True), "한남", 2023, "신입"), "compare")
        leaks_dev["compare"] = bool(re.search(r"근거 행: HN-\d{3}", screen_text(at)))
        at = nav(pick(run(dev=True), "한남", 2023, "신입"), "remaining")
        leaks_dev["remaining"] = bool(re.search(r"HN-\d{3}", screen_text(at)))
        check("화면: [E24d] ?dev=1에서는 학사 비교의 '근거 행: HN-…'과 내 졸업요건 근거 보기의 행 ID가 보인다", all(leaks_dev.values()), str(leaks_dev))
        Fake.badge, Fake.leak = False, True
        for dev_ in (False, True):
            at = nav(pick(run(dev=dev_), "한남", 2023, "신입"), "ask")
            at.text_input(key="q_ask").set_value("부전공은 몇 학점이야?")
            [b for b in at.button if b.label == "질문하기"][0].click()
            at.run()
            tx_ = screen_text(at)
            if not dev_:
                check("화면: [E24d] 규정 질문 답 — 일반 모드에서 답 본문의 행 ID 토큰·근거 카드 행 ID가 지워지고(표시만), 배지는 짧은 새 문구뿐이다",
                      "부전공은 54학점이에요" in tx_ and "HN-0" not in tx_ and "이 값은 잠정이에요 (학과 확인)" in tx_ and "출처마다 값이 달라요 (학과 확인)" in tx_ and "(HN" not in tx_, tx_[:200])
            else:
                check("화면: [E24d] ?dev=1에서는 답 본문 원문(행 ID 포함)·근거 카드·배지의 행 ID가 그대로 보인다",
                      "(HN-026)" in tx_ and "HN-001" in tx_ and "HN-020, HN-024" in tx_, tx_[:200])
        Fake.badge, Fake.leak = True, False
        # E24c: 개설 과목 — 학과를 바꿀 때 영역·학년 기억을 비우고, IT경영정보학과면 '전공'과 학년 선택이 보인다
        if not CR.available():
            skip("E24c 개설 과목 학과·학년 점검: data/courses_baejae_2026-2.json 없음(build_courses.py로 생성)")
        else:
            secs_ = CR.load()
            n_grade = {g_: len({x_["과목코드"] for x_ in secs_ if x_["영역"] == "전공" and x_["대상학년"] == g_}) for g_ in CR.GRADES}

            def crs_keys(at_):
                return [w_.key for w_ in list(at_.multiselect) + list(at_.selectbox) + list(at_.checkbox) if w_.key and w_.key.startswith("crs")]
            at = nav(pick(run(), "배재", 2023, "신입"), "courses")  # IT경영정보학과를 고르고 연다
            check("화면: [E24c] IT경영정보학과를 고르면 영역 기본값이 '전공'이고 대상 학년 선택(1~4학년)이 보인다",
                  at.selectbox(key="crs_area_w").value == "전공" and "crs_grades_w" in crs_keys(at) and list(at.multiselect(key="crs_grades_w").options) == list(CR.GRADES) and not at.exception)
            at.multiselect(key="crs_grades_w").set_value(["4학년"]).run()
            check(f"화면: [E24c] 학년을 4학년으로 바꾸면 목록이 줄어든다(전공 {sum(n_grade.values())}과목 → 4학년 {n_grade['4학년']}과목)",
                  f"{n_grade['4학년']}과목 · " in html(at) and f"{sum(n_grade.values())}과목 · " not in html(at) and " · 4학년" in html(at))
            at.multiselect(key="crs_grades_w").set_value(["1학년", "2학년"]).run()
            check("화면: [E24c] 학년을 다시 바꾸면 그 학년 과목 수로 바뀐다(1+2학년)", f"{n_grade['1학년'] + n_grade['2학년']}과목" in html(at))
            at = nav(pick(run(), "배재", 2023, "신입", dept=False), "courses")  # 학과 미선택으로 연다
            check("화면: [E24c] 학과 미선택이면 학년 선택 없이 '전공 과목은 IT경영정보학과만 지원해요' 안내만, 영역에 '전공'이 없다",
                  "crs_grades_w" not in crs_keys(at) and "전공 과목은 IT경영정보학과만 지원해요" in html(at) and "전공" not in at.selectbox(key="crs_area_w").options[0])
            at.sidebar.selectbox(key="dept_배재").set_value("IT경영정보학과")
            at.run()
            check("화면: [E24c] (이번 버그) 미선택으로 개설 과목을 연 뒤 IT경영정보학과를 고르면 영역이 '전공'으로 바뀌고 학년 선택이 보인다",
                  at.selectbox(key="crs_area_w").value == "전공" and "crs_grades_w" in crs_keys(at))
            at.sidebar.selectbox(key="dept_배재").set_value("경영학과")
            at.run()
            check("화면: [E24c] 다른 학과로 바꾸면 학년 선택이 없어지고 안내가 보인다(영역은 '전공' 없는 목록의 첫 영역)",
                  "crs_grades_w" not in crs_keys(at) and "전공 과목은 IT경영정보학과만 지원해요" in html(at) and "전공" not in at.selectbox(key="crs_area_w").options[0])
            at = nav(pick(run(), "배재", 2023, "신입"), "courses")
            at.selectbox(key="crs_area_w").set_value("교양필수").run()
            check("화면: [E24c] 같은 학과 안에서 영역을 직접 바꾼 선택은 그대로 유지된다", at.selectbox(key="crs_area_w").value == "교양필수" and "crs_grades_w" not in crs_keys(at))
            at.multiselect(key="crs_done_w").set_value([at.multiselect(key="crs_done_w").options[0]]).run()
            done_ = list(at.session_state["keep"].get("crs_done", []))
            at.sidebar.selectbox(key="dept_배재").set_value("경영학과")
            at.run()
            check("화면: [E24c] 같은 학교 안에서 학과만 바뀌면 이수 체크한 과목은 유지된다", bool(done_) and list(at.session_state["keep"].get("crs_done", [])) == done_ and not at.exception)
            at.sidebar.selectbox(key="univ").set_value("목원")
            at.run()
            check("화면: [E24c] 학교가 바뀌면 이수 체크·요일·영역 기억이 모두 초기화된다", not at.session_state["keep"].get("crs_done") and not at.session_state["keep"].get("crs_area") and not at.exception)
            at.sidebar.selectbox(key="univ").set_value("배재")
            at.run()
            check("화면: [E24c] 배재로 돌아오면 이전 이수 체크가 되살아나지 않는다", not at.session_state["keep"].get("crs_done"))
        # 개설 과목 페이지(배재대 2026-2, 가공본이 있을 때만)
        if not CR.available():
            skip("개설 과목 화면 점검: data/courses_baejae_2026-2.json 없음(build_courses.py로 생성)")
        else:
            at = nav(pick(run(), "배재", 2023, "신입"), "courses")
            h = html(at)
            opts = list(at.selectbox(key="crs_area_w").options)
            check("화면: [개설 과목] 배재 2023 영역에 비전설계 있고 공유혁신 없음, 기본은 전공 16과목(IT경영정보), 자료 기준일 문구, 표(dataframe) 없음",
                  "비전설계" in opts and "공유혁신" not in opts and "전공" in opts[0] and "16과목 · 16분반" in h and "11월 9일 내려받음" in h and "수강 가능 여부는 판단하지 않아요" in h and not at.dataframe and not at.exception, str(opts)[:120])
            at.selectbox(key="crs_area_w").set_value("교선").run()
            h = html(at)
            check("화면: [개설 과목] 교선은 '영역 정보가 없어요' 한 줄 + 87과목·212분반, 강한 제한 문구가 있는 분반에만 배지", "영역 정보가 없어요" in texts(at.caption) and "87과목 · 212분반" in h and h.count('class="badge b-warn">수강 제한 있음') >= 31, f"{texts(at.caption)[:2]} {'87과목 · 212분반' in h} {h.count(chr(34)+'>수강 제한 있음')}")
            at.multiselect(key="crs_days_w").set_value(["금"]).run()
            h = html(at)
            nfri = sum(1 for x in CR.load() if x["영역"] == "교선" and "금" in x["요일"])
            check(f"화면: [개설 과목] 요일 금 필터 → 교선 금요일 분반 {nfri}개만(자료 직접 세기와 일치)", f"{nfri}분반" in h and "요일 금" in h and not at.exception and "시간이 정해지지 않은 분반 135개는" in texts(at.caption), h[h.find("card-sub"):][:120] if "card-sub" in h else "")
            at.multiselect(key="crs_days_w").set_value([]).run()
            first = CR.group_courses(CR.sections_in(CR.load(), 2023, "교선"))[0]
            at.multiselect(key="crs_done_w").set_value([first["code"]]).run()
            h = html(at)
            check("화면: [개설 과목] 이수한 과목 체크 → 목록에서 빠지고 '이수 제외 1과목', 값은 session_state(keep)에만", f'<b>{first["name"]}</b>' not in h and "86과목" in h and "이수 제외 1과목" in h and at.session_state["keep"].get("crs_done") == [first["code"]])
            at.selectbox(key="crs_area_w").set_value("교양_비전설계").run()
            h = html(at)
            check("화면: [개설 과목] 2023 비전설계 영역: 22과목(진로·취창업 15 + 자기설계 7), 2025용 공유혁신 문구 없음", "22과목 · 22분반" in h and "진로·취창업 · 15과목" in h and "자기설계 · 7과목" in h and "비전설계 영역에서 1과목(3학점)을 이수해요" in h and "BJ-016" not in h)
            at = nav(pick(run(), "배재", 2023, "신입"), "courses")
            h = html(at)
            check("화면: [E18c] 전공 목록에 대상 학년이 보이고 학년 필터가 있으며, 전공 화면에는 '학년 자료가 없어요'·'강의계획서에서 확인하세요' 문구가 없다",
                  "대상 1학년" in h and "대상 4학년" in h and at.multiselect(key="crs_grades_w") is not None and "학년 자료가 없어요" not in h and "강의계획서에서 확인하세요" not in h and not at.exception)
            at.multiselect(key="crs_grades_w").set_value(["4학년"]).run()
            h = html(at)
            check("화면: [E18c] 학년 4학년 필터 → 전공 6과목(합 16 중), 3학년 과목은 빠짐", "6과목 · 6분반" in h and "대상 4학년" in h and "대상 3학년" not in h and " · 4학년</div>" in h)
            at.multiselect(key="crs_grades_w").set_value(["1학년", "3학년"]).run()
            check("화면: [E18c] 학년 1·3학년 필터 → 3 + 3 = 6과목", "6과목 · 6분반" in html(at))
            at.selectbox(key="crs_area_w").set_value("교선").run()
            h = html(at)
            check("화면: [E18c] 교양(교선)에는 학년 필터가 없고 '교양·공유혁신은 학년 자료가 없어요' 한 줄", [x for x in at.multiselect if x.key == "crs_grades_w"] == [] and "교양·공유혁신은 학년 자료가 없어요." in h)
            at = nav(pick(run(), "배재", 2025, "신입"), "courses")
            opts = list(at.selectbox(key="crs_area_w").options)
            check("화면: [개설 과목] 배재 2025 영역에 공유혁신 있고 비전설계(교양) 없음", "공유혁신" in opts and "교양_비전설계" not in opts)
            at.selectbox(key="crs_area_w").set_value("공유혁신").run()
            h = html(at)
            check("화면: [개설 과목] 공유혁신 = 전공융합설계 32 + 비전설계 22 + 혁신교육과미래설계 1 = 55과목·99분반, 공유혁신 안내(행 ID 없음), 전공탐색은 자료 없음 명시",
                  "55과목 · 99분반" in h and "전공융합설계 · 32과목" in h and "비전설계 · 진로·취창업 · 15과목" in h and '혁신교육과미래설계 (<abbr class="abbr" title="전공필수">전필</abbr>, P/F) · 1과목' in h and "전공융합설계 9학점 이상" in texts(at.caption) and not re.search(r"(?:BJ|MW|HB|HN|CN)-\d{3}", texts(at.caption)) and "찾지 못했어요" in texts(at.caption), f"{[k for k in ('55과목 · 99분반', '전공융합설계 · 32과목', '비전설계 · 진로·취창업 · 15과목', '혁신교육과미래설계 (전필, P/F) · 1과목') if k not in h]} {texts(at.caption)[:2]}")
            at = nav(pick(run(), "배재", 2023, "편입"), "courses")
            check("화면: [개설 과목] 편입이면 필수과목 면제 안내 한 줄(과목별 면제 배지 없음)", "편입생은 편입 전 학년의 교양필수·전공필수가 면제될 수 있어요. 해당 여부는 학과에서 확인하세요." in html(at) and "BJ-060" not in html(at) and "면제 가능" not in html(at))
        at = nav(pick(run(), "목원", 2023, "신입"), "courses")
        check("화면: 배재 외 대학 개설 과목은 '지원하지 않아요' 안내(목록·버튼 없음)", "개설 과목 안내를 아직 지원하지 않아요" in html(at) and 'class="crs-sec"' not in html(at) and not at.exception)
        # 규정 안내: 홈 카드에서 질문 → 근거 카드 번호·배지, 학생 화면에 비용·응답 시간 없음
        calls.clear()
        at = nav(pick(run(), "한남", 2023, "신입"), "ask")
        at.text_input(key="q_ask").set_value("졸업학점 몇 학점이야?")
        [b for b in at.button if b.label == "질문하기"][0].click()
        at.run()
        h = html(at)
        check("화면: 규정 질문 페이지 질문 처리(사이드바 값 전달)·확인 불가 노란 배지·접기", len(calls) == 1 and calls[0][1:3] == ("한남", 2023) and "callout-warn" in h and "확인 불가" in h
              and any("자세히 보기" in x.label for x in at.expander), h[:80])
        ct = h  # 규정 질문 페이지는 근거 카드를 접지 않고 바로 보여 준다(홈 카드 때는 접기였음)
        check("화면: 근거 카드에 원래 번호([1]·[3])·조항·쪽·현행·등급", '<span class="num">[1]</span>' in ct and '<span class="num">[3]</span>' in ct and "제5조" in ct and "PDF 3쪽" in ct and "현행(2026)" in ct and "A 규정 원문" in ct, ct[:80])
        check("화면: 처리 방식만 작게(기준표 조회), 학생 화면에 비용·응답 시간·실제로 보낸 질문 없음", "처리 방식: 기준표 조회" in h and "비용" not in h and "응답" not in h and "실제로 보낸 질문" not in h and "$0.0012" not in h and "900" not in h)
        check("화면: 학생 모드에는 개발자·로그 메뉴가 없다", "개발자 · 로그" not in [b.label for b in at.sidebar.button])
        check("화면: 체크리스트와 안 겹치는 질문에는 안내 줄이 안 붙는다('확인 불가' 배지가 있어도)", "체크리스트에 관련 요건" not in h)
        at = nav(pick(run(), "배재", 2025, "신입"), "ask")
        at.text_input(key="q_ask").set_value("혁신교육과미래설계 꼭 들어야 해?")
        [b for b in at.button if b.label == "질문하기"][0].click()
        at.run()
        h = html(at)
        check("화면: 규정 안내 페이지 — '확인 불가' 배지 + 겹치는 질문 → 체크리스트 안내 줄 (항목: 0학점 이수 필수), 근거 카드는 펼쳐서 표시",
              "내 졸업요건의 체크리스트에 관련 요건이 있을 수 있어요" in h and "0학점 이수 필수" in h and "근거 (2건)" in h and '<span class="num">[1]</span>' in h, h[:100])
        Fake.badge = False
        at = nav(pick(run(), "배재", 2025, "신입"), "ask")
        at.text_input(key="q_ask").set_value("혁신교육과미래설계 꼭 들어야 해?")
        [b for b in at.button if b.label == "질문하기"][0].click()
        at.run()
        check("화면: '확인 불가' 배지가 없으면 안내 줄도 없다", "체크리스트에 관련 요건" not in html(at))
        Fake.badge = True
        con = sqlite3.connect(os.environ["SERVICE_LOG_DB"])
        cols = [r[1] for r in con.execute("pragma table_info(query_log)")]
        check("화면: 로그에 질문 기록·열에 학점·평점·입학구분 없음", con.execute("select count(*) from query_log").fetchone()[0] == 3 + 2  # 3 + E24d 점검이 먼저 보낸 질문 2개
              and not any(k in c for c in cols for k in ("credit", "gpa", "entry", "학점", "평점")), str(cols))
        # 개발자 모드: 메뉴·응답 시간·비용·로그 페이지는 ?dev=1에서만
        at = pick(run(dev=True), "한남", 2023, "신입")
        check("화면: 개발자 모드(?dev=1)에는 6번째 '개발자 · 로그' 메뉴가 있다", [b.label for b in at.sidebar.button][-1] == "개발자 · 로그" and len(at.sidebar.button) == 6)
        nav(at, "ask")
        at.text_input(key="q_ask").set_value("졸업학점 몇 학점이야?")
        [b for b in at.button if b.label == "질문하기"][0].click()
        at.run()
        h = html(at)
        check("화면: 개발자 모드 답변 아래에 응답 시간·비용·실제로 보낸 질문 표시", "응답 0.9초" in h and "비용 $0.0012" in h and "실제로 보낸 질문" in h, h[-120:])
        at = nav(at, "dev")
        names = [x.label for x in at.metric]
        check("화면: 개발자 모드 로그 페이지(질문 수·총 비용·평균 응답)", "질문 수" in names and "총 비용($)" in names and "평균 응답(초)" in names and bool(at.dataframe) and not at.exception)
        at = nav(run(), "home")
        check("화면: 학생 모드에는 로그 지표가 없다(로그 기록은 계속 남는다)", not at.metric and "질문 수" not in html(at))
        at = pick(run(), "한남", "범위 밖", "신입")
        check("화면: 범위 밖 학번은 남은 학점·비교 페이지에 경고", all("2022~2026학번만 다뤄요" in html(nav(at, p)) for p in ("remaining", "compare")))

        class Boom:
            def answer(self, *a, **k):
                raise RuntimeError("boom")
        engine.Engine = Boom
        st.cache_resource.clear()
        at2 = nav(run(), "ask")
        at2.text_input(key="q_ask").set_value("아무 질문")
        [b for b in at2.button if b.label == "질문하기"][0].click()
        at2.run()
        errs = con.execute("select error from query_log where error is not null").fetchall()
        check("화면: 엔진 오류가 나도 화면 유지·오류 안내·로그 기록", not at2.exception and len(at2.error) == 1 and len(errs) == 1 and "RuntimeError" in errs[0][0])
    finally:
        engine.Engine = saved
        st.cache_resource.clear()


def cmd_cards():
    """E30: 체크리스트 카드는 위에 제목 + 결과 한 줄만, 근거 문장은 근거 보기 안에만, 메타 줄에 값 없는 라벨이 없다(일반 모드, API 비용 0)."""
    import re
    import ui_pages as P
    n, dup, empty, top_src, same = 0, [], [], [], []
    for univ, dept in S.BASE_DEPT.items():
        for year in range(2022, 2027):
            for entry in ("신입", "편입"):
                for it in S.checklist(univ, year, dept, entry, False):
                    html_ = P.checklist_html([it])
                    n += 1
                    if "ck-src" in html_:
                        top_src.append((univ, year, it["title"]))
                    head, _, det = html_.partition("<details")
                    divs = re.findall(r"<div>(.*?)</div>", det)
                    if len(divs) != len(set(divs)):
                        dup.append((univ, year, it["title"]))
                    text = P.U.esc(it["text"])
                    if text and any(text == d or (len(text) > 12 and text in d) for d in divs):
                        same.append((univ, year, it["title"]))
                    if re.search(r"(?:쪽|등급|상태|대상|판본)(?:\s*·|\s*$)", " ".join(divs)) or re.search(r"(?:^|·)\s*·", " ".join(divs)):
                        empty.append((univ, year, it["title"]))
    check(f"카드: 체크리스트 {n}개 카드 위에는 근거 문장(출처 줄)이 없다", n > 100 and not top_src, str(top_src[:3]))
    check("카드: 같은 문장이 위(결과 한 줄)와 근거 보기 안에 두 번 나오지 않고, 근거 보기 안에서도 중복 없음", not same and not dup, str((same[:3], dup[:3])))
    check("카드: 근거 보기 메타 줄에 값 없는 라벨(쪽·등급·상태)이 없다", not empty, str(empty[:3]))
    check("카드: meta_line은 빈 값 라벨을 뺀다", P.meta_line(("쪽", ""), ("등급", "A"), ("상태", "확인불가")) == "등급 A · 상태 확인불가" and P.meta_line(("쪽", "8"), ("등급", None)) == "쪽 8" and P.meta_line(("쪽", " ")) == "")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", nargs="?", default="all", choices=["all", "equiv", "logic", "citations", "app", "_snapshot"])  # _snapshot: 재시도용 내부 명령(JSON 한 줄 출력)
    ap.add_argument("--write-baseline", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if a.what == "_snapshot":
        print(json.dumps(snapshot(), ensure_ascii=False))
        return
    if a.what in ("all", "equiv"):
        cmd_equiv(a.write_baseline)
    if a.what in ("all", "logic") and not a.write_baseline:
        cmd_logic()
    if a.what in ("all", "citations") and not a.write_baseline:
        cmd_citations()
    if a.what in ("all", "app") and not a.write_baseline:
        cmd_app()
    if a.what in ("all", "app") and not a.write_baseline:
        cmd_cards()
    bad = [n for n, ok, _ in RESULTS if not ok]
    if RESULTS:
        print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} 통과" + (f", 실패 {bad}" if bad else "") + f" · SKIP {len(SKIPS)}개" + (f" {SKIPS}" if SKIPS else ""))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
