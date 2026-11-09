"""7단계 점검 (API 비용 0). 8단계 코드 동결 확인에도 쓴다.

    python src/check_service.py            # equiv + logic 모두
    python src/check_service.py equiv      # 파이프라인 동치: 개발용 51문항의 경로·검색 청크/조회 행 ID·검색 거리·필터·확장 질문·LLM에 보낸 프롬프트 해시·진행 로그가
                                           #   기준 스냅샷(eval/pipeline_snapshot.json)과 같은가
    python src/check_service.py equiv --write-baseline   # 의도한 변경 뒤 기준 스냅샷을 다시 쓴다(추출 전 코드의 스냅샷으로 처음 만들었다)
    python src/check_service.py logic      # 사이드바 우선 규칙, 영역별 계획(T1·T2·T3), 체크리스트, 학사 선택 비교, 출처 줄 분리

equiv는 OpenAI 임베딩을 질문 해시로 만든 고정 벡터로, LLM을 프롬프트 해시만 기록하는 가짜로 바꿔 run_rag.cmd_answer를 그대로 실행한다
(임베딩 API 잡음이 없고 비용이 0이다). 답변 문장·토큰·실행 시각은 비교하지 않는다. 결과 CSV·사용 로그는 쓰지 않는다.
"""

import argparse
import builtins
import hashlib
import json
import random
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import criteria_calc  # noqa: E402
import criteria_lookup as L  # noqa: E402
import engine  # noqa: E402
import query_filter as QF  # noqa: E402
import run_rag as R  # noqa: E402
import service_calc as S  # noqa: E402

BASELINE = ROOT / "eval" / "pipeline_snapshot.json"
RESULTS = []


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
    args = argparse.Namespace(chunks="", collection="", filter=True, expand=True, lookup=True, lookup_prompt="v2", calc=True, prompt="v2",
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
        if not hard and not soft and snap["log_lines"] == base["log_lines"]:
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
              "lookup-v2": R.prompt_hash(R.LOOKUP_SYSTEM_V2), "calc-v1": R.prompt_hash(R.CALC_SYSTEM), "judge-v2": R.prompt_hash(R.JUDGE_SYSTEM)}
    expected = {"answer-v1": "151fc2fa1a4b", "answer-v2": "95af4a805902", "lookup-v1": "aa2dd09cd98b", "lookup-v2": "2085142f4358",
                "calc-v1": "fa46be364a36", "judge-v2": "f06259a59823"}
    check("프롬프트 해시 6종 불변", hashes == expected, str(hashes))


# ---------- 서비스 로직 ----------

def cmd_logic():
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
    q2, used2 = engine.choose_question("부전공은 몇 학점이야?", "한남", 2023, "경영정보학과")
    check("학과를 붙이면 막히는 질문(한남 부전공)은 학과 없는 문장을 쓴다", (not used2) and engine.routable(q2) and "경영정보학과" not in q2, q2)
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
    q, used = engine.choose_question("혁신교육과미래설계 꼭 들어야 해?", "배재", 2025, "IT경영정보학과")
    check("한계 E13: 과목명 필수 여부(BJ-032 혁신교육과미래설계)는 조회 항목이 아니라 RAG로 간다(이번에 고치지 않음)", rows_of(q) is None and not engine.routable(q), q)
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
    check("영역별 계획 판정 T1 8 · T2 7 · T3 10", count == {"T1": 8, "T2": 7, "T3": 10}, str(count))
    t1_ok = all(p["areas"] and sum(a["min"] for a in p["areas"]) <= float(p["grad"]["값"]) <= sum(a["max"] for a in p["areas"]) for p in tiers.values() if p["tier"] == "T1")
    check("T1은 영역 합이 졸업학점과 맞는다", t1_ok)
    check("충남 2026 기본 방식은 심화단수 행", tiers[("충남", 2026)]["method"] == "심화단수" and tiers[("충남", 2026)]["tier"] == "T1")
    check("배재 2022~2024 교양: '합이 안 맞는 영역 있음' 배지(하위 34 ≠ 계 36)", all(tiers[("배재", y)]["badges"] and "34" in tiers[("배재", y)]["badges"][0] for y in (2022, 2023, 2024)))
    check("배재 2025~: 교양 하위 합 일치라 배지 없음, 규정 표에 영역이 지정되지 않은 학점 26", all(not tiers[("배재", y)]["badges"] and tiers[("배재", y)]["unassigned"] == 26 for y in (2025, 2026)))
    check("목원 2025·2026: 규정 표에 영역이 지정되지 않은 학점 23", all(tiers[("목원", y)]["tier"] == "T2" and tiers[("목원", y)]["unassigned"] == 23 for y in (2025, 2026)))
    check("한남·한밭은 T3(참고 표)", all(tiers[(u, y)]["tier"] == "T3" and tiers[(u, y)]["ref_rows"] for u in ("한남", "한밭") for y in S.YEARS))
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
    check("목원 졸업 평점은 '없음'(조문 인용)", ("졸업 평점", "없음") in kinds("목원", 2024) and "제47조" in kinds("목원", 2024)[("졸업 평점", "없음")]["text"])
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", nargs="?", default="all", choices=["all", "equiv", "logic", "citations", "_snapshot"])  # _snapshot: 재시도용 내부 명령(JSON 한 줄 출력)
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
    bad = [n for n, ok, _ in RESULTS if not ok]
    if RESULTS:
        print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} 통과" + (f", 실패 {bad}" if bad else ""))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
