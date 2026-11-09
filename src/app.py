"""대전 지역 대학 졸업요건 안내 화면 (7단계, Streamlit).

사이드바에서 대학·학번·학과·입학 구분을 고르면 네 탭이 그 값을 쓴다.
  ① 규정 안내     질문 → 6단계 채택 파이프라인(계산 → 조회 → 규정 검색 RAG) → 답변·출처 카드·배지
  ② 남은 학점     영역별 이수 학점을 넣으면 남은 학점 계산(순수 Python, API 비용 0) + 학점 외 체크리스트
  ③ 학사 선택 비교  부전공 ↔ 복수·다전공 전공학점 비교(순수 Python, 설명 버튼만 LLM)
  ④ 로그          질문 수·비용·응답 시간·피드백
성적(이수 학점·평점·입학 구분)은 어디에도 저장하지 않는다. 질문 문장·답변·출처 ID·비용만 로그(SQLite)에 남는다.

실행
    .venv\\Scripts\\python.exe -m streamlit run src\\app.py
환경 변수
    SERVICE_LOG_DB  로그 DB 경로 (기본 data/service_log.db)
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

import engine  # noqa: E402
import service_calc as S  # noqa: E402
from service_log import DB_PATH, LogDB  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
UNIVS = list(S.BASE_DEPT)
YEAR_CHOICES = [*S.YEARS, "모름", engine.OUT_OF_RANGE]
LONG_ANSWER = 300  # 이 글자 수를 넘으면 첫 문단만 먼저 보여 주고 나머지는 접는다
EXAMPLES = ["졸업하려면 총 몇 학점이 필요해?", "부전공은 몇 학점 이수해야 해?", "재수강은 어떻게 하나요?", "부전공과 복수전공 중 어느 쪽이 전공학점이 적어?"]

st.set_page_config(page_title="대전 졸업요건 안내", page_icon="🎓", layout="wide")


def code_version():
    """코드·기준표가 바뀌면 캐시한 엔진을 다시 만든다(1차 프로젝트와 같은 방식)"""
    files = [*sorted((ROOT / "src").glob("*.py")), ROOT / "data" / "criteria.csv", ROOT / "data" / "synonyms.json"]
    return tuple(int(f.stat().st_mtime) for f in files if f.exists())


@st.cache_resource(show_spinner="엔진을 준비하는 중이에요…")
def get_engine(_version):
    return engine.Engine()


@st.cache_resource
def get_log():
    return LogDB()


# ---------- 사이드바 ----------

def sidebar():
    st.sidebar.header("내 정보")
    univ = st.sidebar.selectbox("대학", UNIVS, key="univ")
    year_choice = st.sidebar.selectbox("학번(입학년도)", YEAR_CHOICES, format_func=lambda y: f"{y}학번" if isinstance(y, int) else y, key="year")
    base = S.BASE_DEPT[univ]
    others = [t for t in S.grad_targets(univ) if t != base]
    kind = st.sidebar.radio("학과", [f"{base} (경영 계열)", "그 외 학과"], key=f"deptkind_{univ}")
    if kind.startswith(base) or not others:
        dept = base
    else:
        dept = st.sidebar.selectbox("학과·계열 선택", others, key=f"dept_{univ}")
        st.sidebar.caption("경영 계열 외 학과는 총 졸업학점까지만 계산해요. 영역별 기준은 기준표에 없어요.")
    entry = st.sidebar.radio("입학 구분", S.ENTRY_TYPES, horizontal=True, key="entry")
    teacher = False
    if S.has_teacher_rows(univ):
        teacher = st.sidebar.checkbox("사범대학 소속 또는 교직이수자", key=f"teacher_{univ}")
    st.sidebar.divider()
    st.sidebar.caption("입력한 학점·평점·입학 구분은 저장하지 않아요. 질문과 답변, 근거 ID, 비용만 로그에 남아요.")
    year = year_choice if isinstance(year_choice, int) else (engine.OUT_OF_RANGE if year_choice == engine.OUT_OF_RANGE else None)
    return {"univ": univ, "year": year, "dept": dept, "entry": entry, "teacher": teacher, "base": base}


def need_year(sc):
    """남은 학점·비교 탭은 학번이 정해져야 한다"""
    if isinstance(sc["year"], int):
        return True
    if sc["year"] == engine.OUT_OF_RANGE:
        st.warning("이 서비스는 2022~2026학번만 다뤄요. 그 밖의 학번은 확인할 수 없어요(확인 불가). 학과 사무실이나 학사 공지를 확인하세요.")
    else:
        st.info("왼쪽에서 학번을 골라 주세요. 학번마다 기준이 달라요.")
    return False


# ---------- 공통 표시 ----------

def show_badges(badges):
    for b in badges:
        if b["kind"] == "확인불가":
            st.warning(b["text"], icon="⚠️")
        elif b["kind"] == "학과확인필요":
            st.warning(b["text"], icon="🏫")
        else:
            st.info(b["text"], icon="🕒")


def show_body(text):
    """긴 답은 첫 문단만 먼저 보여 주고 나머지는 접는다"""
    paras = [p for p in text.split("\n\n") if p.strip()]
    if len(text) > LONG_ANSWER and len(paras) > 1:
        st.markdown(paras[0])
        with st.expander("자세히 보기"):
            st.markdown("\n\n".join(paras[1:]))
    else:
        st.markdown(text)


def show_sources(out):
    srcs = out.get("sources", [])
    if not srcs and not out.get("tail"):
        return
    with st.expander(f"근거 보기 ({len(srcs)}건)"):
        for s in srcs:
            tag = " ".join(f"[{n}]" for n in s.get("nums", []))  # 답 속 번호와 같은 번호(모델이 본 원래 번호, 다시 매기지 않음)
            tag = f"{tag} " if tag else ""
            if s["kind"] == "기준표":
                st.markdown(f"**{tag}{s['title']}** · `{s['id']}`  \n대상 {s['target']} · 값 **{s['value']}** · 상태 {s['status']}  \n"
                            f"{s['article']} · 쪽 {s['pages']} · 등급 {s['grade']}")
            else:
                st.markdown(f"**{tag}{s['title']}** · {s['article']}  \n{s['univ']} · {s['pages']} · 등급 {s['grade']}"
                            + (f" · 판본 {s['edition']}" if s.get("edition") else ""))
        if out.get("tail"):
            st.caption("모델이 답 끝에 적은 출처 줄: " + out["tail"].replace("\n", " "))


def show_answer(out, log_id, key):
    show_badges(out["badges"])
    show_body(out["answer"])
    if out.get("calc_text"):
        with st.expander("계산 과정"):
            st.text(out["calc_text"])
    show_sources(out)
    st.caption(f"처리 방식 {out['route']} · 응답 {out['latency_ms'] / 1000:.1f}초 · 비용 ${out['cost_usd']:.4f}"
               + (f" · 실제로 보낸 질문: {out['question_used']}" if out["question_used"] else ""))
    if log_id:
        fb = st.feedback("thumbs", key=f"fb_{key}")
        if fb is not None:
            get_log().set_feedback(log_id, 1 if fb == 1 else -1)


def ask(question, sc):
    """엔진 호출 + 로그. 반환: (out 또는 None, log_id)"""
    scope = {"univ": sc["univ"], "year": sc["year"], "dept": sc["dept"]}
    try:
        out = get_engine(code_version()).answer(question, sc["univ"], sc["year"], sc["dept"])
    except Exception as e:  # 화면은 계속 쓸 수 있게 하고 오류를 로그에 남긴다
        get_log().log(question, scope, None, error=f"{type(e).__name__}: {e}")
        st.error(f"답변을 만들다 오류가 났어요: {type(e).__name__}. 잠시 뒤 다시 시도해 주세요.")
        return None, None
    return out, get_log().log(question, scope, out)


# ---------- ① 규정 안내 ----------

def set_example(q):
    st.session_state["q_input"] = q


def tab_ask(sc):
    st.subheader("규정 안내")
    st.caption("질문하면 학칙·세칙·편람을 근거로 답하고, 근거를 함께 보여 줘요. 확인되지 않은 내용은 '확인 불가'로 알려 드려요.")
    cols = st.columns(len(EXAMPLES))
    for c, q in zip(cols, EXAMPLES):
        c.button(q, on_click=set_example, args=(q,), width="stretch", key=f"ex_{q}")
    with st.form("ask_form", clear_on_submit=False):
        q = st.text_input("질문", key="q_input", placeholder="예: 재수강은 몇 학점까지 할 수 있어?")
        go = st.form_submit_button("질문하기", type="primary")
    hist = st.session_state.setdefault("history", [])
    if go and q.strip():
        with st.spinner("규정을 찾고 답을 만드는 중이에요…"):
            out, log_id = ask(q.strip(), sc)
        if out:
            hist.insert(0, {"q": q.strip(), "out": out, "log_id": log_id, "scope": f"{sc['univ']}대 {sc['year'] if sc['year'] else '학번 모름'}"})
    for i, h in enumerate(hist[:5]):
        if i == 0:
            st.markdown(f"**Q. {h['q']}**  ·  <small>{h['scope']}</small>", unsafe_allow_html=True)
            show_answer(h["out"], h["log_id"], key=h["log_id"])
        else:
            with st.expander(f"이전 질문: {h['q']}"):
                show_answer(h["out"], None, key=f"old{h['log_id']}")


# ---------- ② 남은 학점 ----------

def num(label, key, **kw):
    return st.number_input(label, min_value=0.0, step=0.5, key=key, format="%g", **kw)


def tab_remaining(sc):
    st.subheader("남은 학점")
    if not need_year(sc):
        return
    univ, year, dept = sc["univ"], sc["year"], sc["dept"]
    plan = S.area_plan(univ, dept, year)
    ctx = f"{univ}|{year}|{dept}"
    if plan["grad"] is None:
        for n in plan["notes"]:
            st.warning(n, icon="⚠️")
    else:
        grad = plan["grad"]
        st.markdown(f"**{univ}대 {year}학번 · {dept}** — 졸업학점 **{S.fmt_value(grad)}** "
                    f"({'/'.join(x for x in (plan['method'],) if x) or '단일'} 기준, `{grad['행ID']}` {grad['출처조항']})")
        for n in plan["notes"]:
            st.info(n)
        for b in plan["badges"]:
            st.warning(b, icon="⚠️")
        done, child_done, total_override = {}, {}, None
        if plan["tier"] in ("T1", "T2"):
            st.markdown("지금까지 이수한 학점을 영역별로 넣어 주세요.")
            cols = st.columns(min(3, len(plan["areas"])))
            for i, a in enumerate(plan["areas"]):
                with cols[i % len(cols)]:
                    done[a["name"]] = num(f"{a['name']} (기준 {S.fmt_value(a['row'])})", f"done|{ctx}|{a['name']}")
            with st.expander("세부 항목별 남은 학점 보기 (선택)"):
                for a in plan["areas"]:
                    for r in a["children"]:
                        child_done[r["항목"]] = num(f"{r['항목']} (기준 {S.fmt_value(r)})", f"kid|{ctx}|{r['항목']}")
            extra = st.checkbox("총 이수 학점을 따로 입력할게요 (영역에 안 들어가는 학점이 있을 때)", key=f"tot_on|{ctx}")
            if extra:
                total_override = num("지금까지 이수한 총 학점", f"tot|{ctx}")
        else:
            if plan["tier"] == "T3":
                with st.expander("참고: 기준표의 영역별 기준 (남은 학점은 계산하지 않아요)"):
                    rows = [{"항목": r["항목"], "이수유형": r["이수유형"] or "-", "기준": S.fmt_value(r), "조건": r["조건"], "행ID": r["행ID"], "출처": r["출처조항"][:60]}
                            for r in plan["ref_rows"]]
                    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            total_override = num("지금까지 이수한 총 학점", f"tot|{ctx}")
        if plan["tier"] in ("T1", "T2") or total_override is not None:
            rem = S.remaining(plan, done, total_override, child_done if any(child_done.values()) else None)
            c1, c2 = st.columns(2)
            c1.metric("총 남은 학점", f"{rem['total_remaining']:g}", help=f"졸업학점 {rem['grad']:g} − 이수 {rem['total_done']:g}")
            if rem["areas"]:
                c2.metric("영역별 남은 학점의 합", f"{rem['area_remaining_sum']:g}", help="영역마다 부족한 학점만 더한 값. 총 남은 학점과 다를 수 있어요.")
            if rem["areas"]:
                df = pd.DataFrame([{"영역": a["name"], "기준": S.fmt_value(a["row"]), "이수": a["done"], "남은 학점": a["remaining"], "비고": a["note"]} for a in rem["areas"]])
                st.dataframe(df, hide_index=True, width="stretch")
                for a in rem["areas"]:
                    shown = [k for k in a["kids"] if k["done"] or k["remaining"]]
                    if any(k["done"] for k in a["kids"]):
                        with st.expander(f"{a['name']} 세부 항목"):
                            st.dataframe(pd.DataFrame([{"항목": k["name"], "기준": S.fmt_value(k["row"]), "이수": k["done"], "남은 학점": k["remaining"]} for k in shown]),
                                         hide_index=True, width="stretch")
                if any(a["over"] for a in rem["areas"]):
                    st.caption(S.OVER_NOTE + ".")
            if rem["unassigned"]:
                st.caption(f"{S.UNASSIGNED_NOTE} {rem['unassigned']:g}학점이 있어요. 어느 영역으로 채워도 되는지는 규정 표에 없어서 '일반선택'이라고 단정하지 않아요(학과 확인 필요).")
    st.markdown("#### 학점 외 이수 요건")
    items = S.checklist(univ, year, dept, sc["entry"], sc["teacher"])
    icon = {"요건": "✅", "없음": "➖", "확인불가": "⚠️", "해당없음": "➖"}
    if not items:
        st.caption("기준표에 이 조건의 학점 외 요건이 없어요.")
    for it in items:
        st.markdown(f"{icon.get(it['kind'], '•')} **{it['title']}** — {it['text']}")
        if it["src"]:
            s = it["src"]
            st.caption(f"`{s['id']}` · {s['source']} · 쪽 {s['pages']} · 등급 {s['grade']} · 상태 {s['status']}")
        if it.get("extra"):
            st.caption(it["extra"])
    st.divider()
    with st.container(border=True):
        st.markdown("#### 이번 학기 개설 과목 안내")
        st.caption("준비 중이에요. 남은 학점에 맞는 개설 과목을 여기에 보여 줄 예정이에요(배재대 먼저).")


# ---------- ③ 학사 선택 비교 ----------

def tab_compare(sc):
    st.subheader("학사 선택 비교: 부전공 ↔ 복수·다전공")
    if not need_year(sc):
        return
    univ, year, dept = sc["univ"], sc["year"], sc["dept"]
    r = S.compare(univ, year, dept)
    if not r["ok"]:
        st.warning("이 조건의 부전공·복수(다)전공 학점을 기준표에서 확인하지 못했어요(확인 불가). " + (r.get("why") or ""), icon="⚠️")
        return
    st.markdown(f"**{univ}대 {year}학번 · {dept}** — 전공학점 합 = 주전공 요구 학점 + 부전공·복수(다)전공 이수 학점")
    rows = []
    for t in r["table"]:
        rows.append({"선택": t["name"], "주전공 요구 학점": S.fmt_value(t["major"]) if t["major"] else "확인 불가",
                     "이수 학점": S.fmt_value(t["extra"]) if t["extra"] else "확인 불가",
                     "전공학점 합": f"{t['total']:g}학점" if t["total"] is not None else "확인 불가",
                     "근거 행": ", ".join(x["행ID"] for x in (t["major"], t["extra"]) if x)})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if r["full"]:
        if r["less"]:
            st.success(f"**{r['less']}**이 전공학점이 **{r['diff']:g}학점** 더 적어요. (전공학점만 비교한 거예요. 신청 자격·평점·교직 등은 따로 확인하세요.)")
        else:
            st.info("두 선택의 전공학점 합이 같아요.")
    else:
        st.warning("한쪽의 주전공 요구 학점이 학과별로 달라 기준표에 없어서, 합을 비교하지 않았어요(학과 확인 필요).", icon="🏫")
    for n in r["notes"]:
        st.info(n)
    for why in r["reasons"]:
        st.caption(why)
    q = S.explain_question(univ, year, dept)
    if q and st.button("이 비교 설명 듣기 (모델 호출, 약 $0.001)", key=f"explain|{univ}|{year}|{dept}"):
        with st.spinner("설명을 만드는 중이에요…"):
            out, log_id = ask(q, {**sc, "univ": None, "year": None, "dept": None})
        st.session_state["explain"] = (out, log_id) if out else None
    ex = st.session_state.get("explain")
    if ex and ex[0] and ex[0]["question_used"] == q:
        show_answer(ex[0], ex[1], key=f"explain{ex[1]}")
    if q is None:
        st.caption("이 조건은 설명 질문이 만들어지지 않아 위 표만 보여 드려요.")


# ---------- ④ 로그 ----------

def tab_log():
    st.subheader("로그")
    log = get_log()
    s = log.summary()
    cols = st.columns(5)
    for c, k in zip(cols, ("질문 수", "총 비용($)", "평균 응답(초)", "도움이 됐다", "도움이 안 됐다")):
        c.metric(k, s[k])
    st.caption(f"오류 {s['오류 수']}건 · 처리 방식별 {s['처리 방식별'] or '없음'} · DB `{DB_PATH.name}` (이수 학점·평점은 저장하지 않아요)")
    rows = log.recent(100)
    if rows:
        df = pd.DataFrame(rows).rename(columns={"ts": "시각", "univ": "대학", "year": "학번", "dept": "학과", "question": "질문", "route": "처리",
                                                 "cost_usd": "비용($)", "latency_ms": "응답(ms)", "feedback": "피드백", "error": "오류"})
        st.dataframe(df.drop(columns=["id"]), hide_index=True, width="stretch")
    else:
        st.caption("아직 질문이 없어요.")


def main():
    st.title("🎓 대전 지역 대학 졸업요건 안내")
    st.caption("배재·충남·한남·한밭·목원대 학사 규정을 근거로 답해요. 2022~2026학번 기준이며, 최종 확인은 학과 사무실에서 하세요.")
    sc = sidebar()
    t1, t2, t3, t4 = st.tabs(["규정 안내", "남은 학점", "학사 선택 비교", "로그"])
    with t1:
        tab_ask(sc)
    with t2:
        tab_remaining(sc)
    with t3:
        tab_compare(sc)
    with t4:
        tab_log()


main()
