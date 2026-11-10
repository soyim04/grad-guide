"""졸업나침반 화면 페이지(7단계 새 디자인). 계산·조회·엔진은 기존 함수를 그대로 부르고, 여기서는 배치와 표시만 한다.

페이지: 시작하기 · 규정 질문 · 내 졸업요건 · 학사 선택 비교 · 이번 학기 개설 과목 · (개발자 모드) 로그
- 사이드바 입력은 바로 적용된다(저장 버튼 없음). 이수 학점·평점은 session_state 메모리에만 두고 디스크·로그에는 쓰지 않는다.
- 페이지를 옮기면 그 페이지에서 그려지지 않은 위젯의 값은 Streamlit이 지우므로, 학점 입력은 `keep` 사전에 따로 복사해 두고 위젯 초기값으로 읽는다.
- 학생 화면에는 응답 시간·비용·로그를 보이지 않는다. 주소에 `?dev=1`이 있을 때만 보인다.
"""

import re
from pathlib import Path

import pandas as pd
import streamlit as st

import engine
import courses as CR
import service_calc as S
import ui_style as U
from service_log import DB_PATH, LogDB

ROOT = Path(__file__).resolve().parent.parent
UNIVS = list(S.BASE_DEPT)
YEAR_CHOICES = [*S.YEARS, "모름", engine.OUT_OF_RANGE]
LONG_ANSWER = 300  # 이 글자 수를 넘으면 첫 문단만 먼저 보여 주고 나머지는 접는다
EXAMPLES = ["졸업하려면 총 몇 학점이 필요해?", "부전공은 몇 학점 이수해야 해?", "재수강은 어떻게 하나요?", "부전공과 복수전공 중 어느 쪽이 전공학점이 적어?"]
PAGES = [("home", "시작하기"), ("ask", "규정 질문"), ("remaining", "내 졸업요건"), ("compare", "학사 선택 비교"), ("courses", "이번 학기 개설 과목")]
DEV_PAGE = ("dev", "개발자 · 로그")
ROUTE_LABEL = {"조회": "기준표 조회", "계산": "기준표 계산", "규정 검색": "규정 검색", "범위 밖": "범위 확인"}
KIND_BADGE = {"요건": ("req", "요건"), "없음": ("none", "없음"), "확인불가": ("warn", "확인 불가 · 학과 확인"), "해당없음": ("na", "해당 없음"), "안내": ("info", "안내")}
DISCLAIMER = "2022~2026학번 기준 · 최종 확인은 학과 사무실에서"
PLACEHOLDER_DEPT = "학과를 검색하거나 고르세요"  # E24b: 학과 selectbox는 처음에 비어 있고 이 문구만 보인다(경영 학과를 미리 골라 두지 않는다)
GENERIC_DEPT = "목록에 없는 학과 (대학 공통 기준)"
NO_AREA_NOTICE = "이 학과는 영역별 계산을 지원하지 않아요. 총 학점만 계산해요."


# ---------- 공통 ----------

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


def is_dev():
    return st.query_params.get("dev") == "1"


def goto(page):
    st.session_state["page"] = page


def keep():
    return st.session_state.setdefault("keep", {})


def num(label, kkey, wkey, **kw):
    """빈 칸(None)을 허용하는 숫자 입력. 값은 keep[kkey]에도 복사해 페이지를 옮겨도 남긴다."""
    def _sync():
        keep()[kkey] = st.session_state[wkey]
    return st.number_input(label, min_value=0.0, step=0.5, key=wkey, format="%g", value=keep().get(kkey), on_change=_sync, **kw)


def md(html_text):
    st.markdown(html_text, unsafe_allow_html=True)


def page_title(title, sub=""):
    md(f'<div class="page-title">{U.esc(title)}</div>' + (f'<div class="page-sub">{U.esc(sub)}</div>' if sub else ""))


def header(sc):
    year = sc["year"]
    yr = f"{year}학번" if isinstance(year, int) else ("학번 범위 밖" if year == engine.OUT_OF_RANGE else "학번 선택 필요")
    md(f'<div class="topbar"><div><div class="topbar-title">{U.esc(sc["univ"])}대 {U.esc(yr)} · {U.esc(dept_label(sc))}</div>'
       f'<div class="topbar-sub">{U.esc(sc["entry"])} · 왼쪽 내 정보를 바꾸면 모든 화면에 바로 적용돼요</div></div>'
       f'<div class="pill">{U.esc(DISCLAIMER)}</div></div>')


def dept_label(sc):
    """화면에 보여 줄 학과 이름(선택 전·대학 공통일 때는 dept가 None이라 글자로 따로 쓴다)"""
    return {"unselected": "학과 미선택", "generic": "목록에 없는 학과(대학 공통)"}.get(sc.get("dept_state"), sc["dept"])


def ctx_of(sc):
    """학점 입력을 기억하는 키의 조건 부분(학과가 None이면 상태로 대신한다)"""
    return f"{sc['univ']}|{sc['year']}|{sc['dept'] or sc.get('dept_state')}"


def need_dept(sc, what="내 졸업요건"):
    """학과를 아직 안 골랐으면 계산·체크리스트·비교를 숨기고 짧은 안내만 보여 준다(E24b)"""
    if sc.get("dept_state") != "unselected":
        return True
    md(U.callout("info", f"왼쪽에서 학과를 고르면 {what}이 나와요."))
    return False


def need_year(sc):
    """남은 학점·비교는 학번이 정해져야 한다"""
    if isinstance(sc["year"], int):
        return True
    if sc["year"] == engine.OUT_OF_RANGE:
        md(U.callout("warn", "이 서비스는 2022~2026학번만 다뤄요. 그 밖의 학번은 확인할 수 없어요(확인 불가). 학과 사무실이나 학사 공지를 확인하세요."))
    else:
        md(U.callout("info", "왼쪽에서 학번을 골라 주세요. 학번마다 기준이 달라요."))
    return False


# ---------- 사이드바 ----------

def sidebar():
    sb = st.sidebar
    sb.markdown('<div class="brand"><div class="brand-ico"></div><div class="brand-name">졸업나침반</div></div>', unsafe_allow_html=True)
    pages = PAGES + ([DEV_PAGE] if is_dev() else [])
    cur = st.session_state.get("page", "home")
    if cur not in [p[0] for p in pages]:
        cur = st.session_state["page"] = "home"
    for pid, label in pages:
        with sb.container(key=f"navitem_{pid}" + ("__on" if pid == cur else "")):
            st.button(label, key=f"nav_{pid}", on_click=goto, args=(pid,), width="stretch")
    sb.markdown('<div class="side-h">내 정보</div>', unsafe_allow_html=True)
    univ = sb.selectbox("대학", UNIVS, key="univ")
    year_choice = sb.selectbox("학번(입학년도)", YEAR_CHOICES, format_func=lambda y: f"{y}학번" if isinstance(y, int) else y, key="year")
    base = S.BASE_DEPT[univ]
    # E24b: 그 학번에 기준 행이 있는 학과만(묶음 행은 학과 하나하나) 검색 가능한 selectbox 하나. 처음엔 비어 있다.
    # 목록 맨 아래: 단과대학·계열 대체 선택지, (한남 제외) '목록에 없는 학과 (대학 공통 기준)'. 한남은 대학 공통 행이 없어 계열을 대체로 쓴다.
    depts, alts = S.dept_choices(univ, year_choice if isinstance(year_choice, int) else None)
    generic_ok = univ != "한남"
    options = [*depts, *alts, *([GENERIC_DEPT] if generic_ok else [])]
    dkey = f"dept_{univ}"
    if st.session_state.get(dkey) not in (None, *options):  # 학교·학번을 바꿔 이전 학과가 새 목록에 없으면 빈칸으로(기본 학과로 되돌리지 않는다)
        st.session_state[dkey] = None
    pick = sb.selectbox("학과", options, index=None, placeholder=PLACEHOLDER_DEPT, key=dkey)
    if not generic_ok:
        sb.caption("한남은 졸업학점이 계열별로 달라요. 목록에 없는 학과는 학과가 속한 계열을 고르세요.")
    if pick is None:
        dept, dept_state = None, "unselected"
    elif pick == GENERIC_DEPT:
        dept, dept_state = None, "generic"
    else:
        dept, dept_state = pick, "picked"
    entry =sb.radio("입학 구분", S.ENTRY_TYPES, horizontal=True, key="entry")
    transfer_grade = None
    if entry == "편입" and S.uses_transfer_grade(univ):  # 배재 일반편입: 편입 학년에 따라 전공 기준이 다르다(E15)
        transfer_grade = S.TRANSFER_DEFAULT_GRADE  # 편입 학년 선택은 두지 않고 3학년 기준으로 고정(우리 선택. 시행세칙Ⅰ 제63조 ②는 3·4학년 편입 허가)
    if entry == "편입":  # 다섯 학교 모두 입학 구분 바로 아래 한 줄, 세부는 근거 보기 안(배재·한남만)
        note = S.transfer_note(univ)
        sb.info(note["text"], icon="🔁")
        if note["basis"]:
            with sb.expander("근거 보기"):
                for line in note["basis"]:
                    st.markdown(f"- {line}")
    teacher = False
    if S.has_teacher_rows(univ):
        teacher = sb.checkbox("사범대학 소속 또는 교직이수자", key=f"teacher_{univ}")
    sb.divider()
    sb.markdown('<div class="side-note">질문 문장은 서비스 개선을 위해 기록돼요.</div>', unsafe_allow_html=True)
    year = year_choice if isinstance(year_choice, int) else (engine.OUT_OF_RANGE if year_choice == engine.OUT_OF_RANGE else None)
    return {"univ": univ, "year": year, "dept": dept, "dept_state": dept_state, "entry": entry, "teacher": teacher, "base": base, "transfer_grade": transfer_grade}


def plan_for(sc):
    """영역별 계획. 배재 일반편입이면 전공 기준을 편입 행으로 바꾼다(홈·남은 학점 페이지 공용)"""
    plan = S.area_plan(sc["univ"], sc["dept"], sc["year"])
    if sc["entry"] == "편입" and sc.get("transfer_grade"):
        plan = S.apply_transfer(plan, sc["transfer_grade"])
    return plan


# ---------- 표시 부품 ----------

def short_article(text, limit=44):
    """'세칙Ⅰ 제64조 ⑤ 1호 (일반 편입생의 …; 개정 …)' → '세칙Ⅰ 제64조 ⑤ 1호'. 괄호 설명·개정 이력은 근거 보기에 둔다."""
    t = re.sub(r"(제\d+조(?:의\d+)?)\([^)]*\)", r"\1", str(text)).strip()  # 제64조(제목) → 제64조
    i = t.find(" (")
    if i > 0:
        t = t[:i]
    return t if len(t) <= limit else t[:limit].rstrip() + "…"


def short_title(name):
    """규정명 앞의 '국립한밭대학교 ' 같은 학교 이름을 뺀다"""
    return re.sub(r"^(?:국립)?[가-힣]+대학교\s+", "", str(name))


def details_html(lines, label="근거 보기"):
    lines = [x for x in lines if x]
    if not lines:
        return ""
    return f'<details class="det"><summary>{U.esc(label)}</summary>' + "".join(f"<div>{x}</div>" for x in lines) + "</details>"


def checklist_html(items, limit=None):
    out = []
    for it in (items if limit is None else items[:limit]):
        cls, label = KIND_BADGE.get(it["kind"], ("na", it["kind"]))
        short, det = "", []
        if it.get("src"):
            s = it["src"]
            short = f'<div class="ck-src">{U.esc(short_article(s["source"]))}</div>'
            det = [f'{U.esc(s["id"])} · {U.esc(s["source"])}', f'쪽 {U.esc(s["pages"])} · 등급 {U.esc(s["grade"])} · 상태 {U.esc(s["status"])}']
        if it.get("extra"):
            det.append(U.esc(it["extra"]))
        out.append(f'<div class="ck ck-{cls}"><span class="badge b-{cls}">{U.esc(label)}</span>'
                   f'<div><b>{U.esc(it["title"])}</b><div class="ck-text">{U.esc(it["text"])}</div>{short}{details_html(det)}</div></div>')
    return "".join(out)


def show_checklist(sc, limit=None, title=True):
    items = S.checklist(sc["univ"], sc["year"], sc["dept"], sc["entry"], sc["teacher"], sc.get("transfer_grade"))
    na = [x for x in items if x["kind"] == "해당없음"]  # 해당 없는 요건은 기본 숨김(맨 아래 접기)
    items = [x for x in items if x["kind"] != "해당없음"]
    if title:
        md('<div class="card-h" style="font-size:1rem">학점 외 이수 요건</div>')
    if not items:
        st.caption("기준표에 이 조건의 학점 외 요건이 없어요.")
    else:
        md(checklist_html(items, limit))
        if limit is not None and len(items) > limit:
            st.caption(f"그 밖에 {len(items) - limit}개 요건은 '내 졸업요건'에서 볼 수 있어요.")
    if na and limit is None:
        with st.expander(f"해당 없는 요건 {len(na)}개"):
            md(checklist_html(na))


def show_body(text):
    """긴 답은 첫 문단만 먼저 보여 주고 나머지는 접는다"""
    paras = [p for p in text.split("\n\n") if p.strip()]
    if len(text) > LONG_ANSWER and len(paras) > 1:
        st.markdown(paras[0])
        with st.expander("자세히 보기"):
            st.markdown("\n\n".join(paras[1:]))
    else:
        st.markdown(text)


def sources_html(srcs):
    cards = []
    for s in srcs:
        nums = "".join(f'<span class="num">[{n}]</span>' for n in s.get("nums", []))
        if s["kind"] == "기준표":
            top = f'{nums}<span>{U.esc(s["title"])}</span><span>{U.esc(short_article(s["article"]))}</span>'
            meta = f'값 <b>{U.esc(s["value"])}</b>'
            det = [f'대상 {U.esc(s["target"])} · 상태 {U.esc(s["status"])}', f'{U.esc(s["id"])} · {U.esc(s["article"])}', f'쪽 {U.esc(s["pages"])} · 등급 {U.esc(s["grade"])}']
        else:
            ed = s.get("edition") or ""
            ed_chip = U.badge("cur" if ed.startswith("현행") else "old", ed.split("(")[0]) if ed else ""
            top = f'{nums}<span>{U.esc(short_title(s["title"]))}</span><span>{U.esc(short_article(s["article"]))}</span>{ed_chip}'
            meta = ""
            det = [f'{U.esc(s["title"])} · {U.esc(s["article"])}', f'{U.esc(s["univ"])} · {U.esc(s["pages"])} · 등급 {U.esc(s["grade"])}' + (f' · 판본 {U.esc(ed)}' if ed else "")]
        cards.append(f'<div class="src"><div class="src-top">{top}</div>' + (f'<div class="src-meta">{meta}</div>' if meta else "") + details_html(det) + "</div>")
    return "".join(cards)


def show_answer(out, log_id, key, hint=None, compact=False):
    for b in out["badges"]:
        if b["kind"] == "확인불가":
            md(U.callout("warn", f'<b>확인 불가</b> · {U.esc(b["text"])}'))
        elif b["kind"] == "학과확인필요":
            md(U.callout("warn", f'<b>학과 확인 필요</b> · {U.esc(b["text"])}'))
        else:
            md(U.callout("info", U.esc(b["text"])))
    if hint and any(b["kind"] == "확인불가" for b in out["badges"]):  # '확인 불가' 배지가 있을 때만(2026-11-09 승인 규칙)
        md(U.callout("soft", "내 졸업요건의 체크리스트에 관련 요건이 있을 수 있어요. (항목: " + U.esc(" · ".join(hint)) + ")"))
    with st.container(key=f"ans_{key}"):
        show_body(out["answer"])
    if out.get("calc_text"):
        with st.expander("계산 과정"):
            st.text(out["calc_text"])
    srcs = out.get("sources", [])
    if srcs or out.get("tail"):
        if compact:
            with st.expander(f"근거 보기 ({len(srcs)}건)"):
                md(sources_html(srcs))
        else:
            md(f'<div class="card-h" style="font-size:1rem;margin-top:.4rem">근거 ({len(srcs)}건)</div>' + sources_html(srcs))
    line = f"처리 방식: {ROUTE_LABEL.get(out['route'], out['route'])}"
    if is_dev():  # 개발자 모드에서만
        line += f" · 응답 {out['latency_ms'] / 1000:.1f}초 · 비용 ${out['cost_usd']:.4f}" + (f" · 실제로 보낸 질문: {out['question_used']}" if out["question_used"] else "")
        if out.get("tail"):
            line += " · 모델이 답 끝에 적은 출처 줄: " + out["tail"].replace("\n", " ")
    md(f'<div class="route">{U.esc(line)}</div>')
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


# ---------- 질문 블록(홈·규정 안내 공용) ----------

def set_example(qkey, q):
    st.session_state[qkey] = q


def qa_block(sc, prefix, compact=False):
    qkey = f"q_{prefix}"
    examples = EXAMPLES[:3] if compact else EXAMPLES
    with st.container(key=f"chips_{prefix}"):
        cols = st.columns(1 if compact else len(examples))
        for i, q in enumerate(examples):
            cols[0 if compact else i].button(q, on_click=set_example, args=(qkey, q), width="stretch", key=f"ex_{prefix}_{i}")
    with st.form(f"form_{prefix}", clear_on_submit=False, border=False):
        if compact:
            q = st.text_input("질문", key=qkey, placeholder="예: 재수강은 몇 학점까지 할 수 있어?", label_visibility="collapsed")
            go = st.form_submit_button("질문하기", type="primary", width="stretch")
        else:
            c1, c2 = st.columns([6, 1.3])
            q = c1.text_input("질문", key=qkey, placeholder="예: 재수강은 몇 학점까지 할 수 있어?", label_visibility="collapsed")
            go = c2.form_submit_button("질문하기", type="primary", width="stretch")
    if prefix == "ask":  # E27: 학과별 기준표 숫자는 RAG보다 기준표 화면이 정확하다
        st.caption("학과별 졸업 기준표는 '내 졸업요건'에서 정확히 볼 수 있어요.")
    hist = st.session_state.setdefault("history", [])
    if go and q.strip():
        with st.spinner("규정을 찾고 답을 만드는 중이에요…"):
            out, log_id = ask(q.strip(), sc)
        if out:
            hint = S.checklist_hint(q.strip(), sc["univ"], sc["year"], sc["dept"], sc["entry"], sc["teacher"])
            hist.insert(0, {"q": q.strip(), "out": out, "log_id": log_id, "hint": hint,
                            "scope": f"{sc['univ']}대 {sc['year'] if sc['year'] else '학번 모름'}"})
    return hist


def show_history(hist, prefix, compact=False):
    for i, h in enumerate(hist[: (1 if compact else 5)]):
        if i == 0:
            md(f'<div class="q-line">Q. {U.esc(h["q"])}<span class="q-scope">{U.esc(h["scope"])}</span></div>')
            show_answer(h["out"], h["log_id"], key=f"{prefix}{h['log_id']}", hint=h.get("hint"), compact=compact)
        else:
            with st.expander(f"이전 질문: {h['q']}"):
                show_answer(h["out"], None, key=f"{prefix}old{h['log_id']}", hint=h.get("hint"), compact=True)


# ---------- 남은 학점 계산(홈·전용 페이지 공용) ----------

def remaining_state(sc, plan):
    """keep에 복사된 입력으로 남은 학점을 계산한다(홈과 전용 페이지가 같은 값을 쓴다). 반환: dict(rem, fallback, any_area, areas_on)"""
    ctx = ctx_of(sc)
    kp = keep()
    areas_on = plan["tier"] in ("T1", "T2")
    total = kp.get(f"tot|{ctx}")
    done, child_done = {}, {}
    if areas_on:
        done = {a["name"]: kp.get(f"done|{ctx}|{a['name']}") or 0.0 for a in plan["areas"]}
        if kp.get(f"kids_on|{ctx}"):
            for a in plan["areas"]:
                for r in a["children"]:
                    child_done[r["항목"]] = kp.get(f"kid|{ctx}|{r['항목']}") or 0.0
    any_area = any(done.values())
    kids = child_done if any(child_done.values()) else None
    rem, fallback = None, False
    if total is not None:
        rem = S.remaining(plan, done, total, kids)
    elif any_area and sc["entry"] != "편입":
        rem, fallback = S.remaining(plan, done, None, kids), True
    return {"rem": rem, "fallback": fallback, "any_area": any_area, "areas_on": areas_on, "ctx": ctx, "kids_input": kids is not None}


def unsupported_notice(plan):
    return U.callout("info", U.esc(NO_AREA_NOTICE))


def generic_note(sc):
    """'목록에 없는 학과'는 대학 공통 기준만 쓴다"""
    if sc.get("dept_state") == "generic":
        md(U.callout("soft", "대학 공통 기준이에요. 학과마다 다를 수 있으니 학과 사무실에서 확인하세요."))


def big_block(sc, st_):
    rem = st_["rem"]
    if rem is not None:
        md(U.bignum("졸업까지 남은 학점", f"{rem['total_remaining']:g}") +
           f'<div class="statline"><span>졸업학점 <b>{rem["grad"]:g}</b></span><span>총 이수 <b>{rem["total_done"]:g}</b></span></div>')
        if st_["fallback"]:
            st.caption(f"총 이수 학점 칸이 비어 있어 영역 입력의 합({rem['total_done']:g}학점)으로 계산했어요.")
        if rem["total_remaining"] == 0:
            md(U.callout("soft", "졸업학점을 채웠어요. 학점 외 요건과 필수 항목도 확인하세요."))
    elif sc["entry"] == "편입" and st_["any_area"]:
        md(U.callout("info", "편입생은 편입 인정학점이 영역에 안 들어가서, 총 이수 학점을 먼저 입력해야 졸업까지 남은 학점을 알려 드릴 수 있어요."))
    else:
        st.caption("총 이수 학점을 입력하면 졸업까지 남은 학점을 알려 드려요. 학점을 몰라도 위 졸업요건은 확인할 수 있어요. 입력은 건너뛰어도 돼요.")


def reference_lines(plan, rem):
    """'참고' 접기에 넣을 안내(쉬운 말). 학생이 할 수 있는 일이 없는 표 불일치·영역 미지정 학점은 여기로 모은다."""
    lines = [] if plan["tier"] == "T0" else [n for n in plan["notes"]]  # T0 안내는 본문 한 줄과 겹쳐 뺀다
    for a in plan["areas"]:
        c = a["check"]
        if c and c[0] in ("미달", "불일치") and a["min"] is not None:
            lines.append(f"규정 표에서 {a['name']} 세부 항목을 더하면 {c[1]:g}학점인데 '{a['name']} 계'는 {a['min']:g}학점으로 적혀 있어요. "
                         "표 자체가 이렇게 되어 있어서 학생이 할 일은 없어요. 궁금하면 학과에 확인하세요.")
    if plan["unassigned"]:
        parts = "·".join(f"{a['name']} {a['min']:g}" for a in plan["areas"] if a["min"] is not None)
        lines.append(f"졸업에 필요한 {float(plan['grad']['값']):g}학점 중 {parts}(으)로 정해진 학점을 빼면 {plan['unassigned']:g}학점이 남아요. "
                     f"이 {plan['unassigned']:g}학점을 어느 영역으로 채우는지는 규정 표에 나와 있지 않아요. 학과에 확인하세요.")
    if rem and any(a["over"] for a in rem["areas"]):
        lines.append(S.OVER_NOTE + ".")
    return lines


ACCESS_GUIDE = {"배재": "학교 포털 '졸업자가진단' → 이수현황 표의 '소계'를 넣으세요."}
ACCESS_GUIDE_DEFAULT = "학교 포털의 졸업사정(졸업 자가진단) 메뉴에서 확인하세요."
KIDS_GUIDE = {"배재": "영역별 학점은 학교 포털 '졸업자가진단'에서 볼 수 있어요. 모르면 비워 두세요."}
KIDS_GUIDE_DEFAULT = "영역별 학점은 학교 포털 졸업사정(졸업 자가진단) 메뉴에서 확인하세요. 모르면 비워 두세요."


SINGLE_NOTE = "복수전공·부전공을 하지 않을 때(단수전공) 기준이에요."


def _pct_example(row, grad):
    """%로 정해진 기준은 졸업학점으로 계산한 예시를 붙인다: 졸업학점의 25% 이상 (130학점이면 32.5학점). 소수 그대로"""
    base = S.fmt_basis(row)
    try:
        g, v = float(grad["값"]), float(row["값"])
    except (TypeError, ValueError):
        return base
    if row["단위"] != "%":
        return base
    return f"{base} ({g:g}학점이면 {round(g * v / 100, 4):g}학점)"


def basis_entries(plan):
    """영역 기준 표의 행: [{name, basis, level}]와 부가 정보 {note(단수 안내), sums[] ('전공 72학점 이상 = 기본전공 + 심화전공')}.
    상위·하위: T1/T2는 영역 아래에 세부 항목, T3는 전공 아래에 기본전공·심화전공(같은 이수유형). 이수유형이 모두 단수면 '(단수)'를 이름에서 빼고 표 위에 한 줄로 알린다."""
    grad = plan["grad"]
    items = []  # (이름, 행, 수준)
    if plan["tier"] in ("T1", "T2"):
        for a in plan["areas"]:
            items.append((a["name"], a["row"], 0))
            for c in a["children"]:
                items.append((CR.item_label(c["항목"]), c, 1))
    elif plan["tier"] == "T3":
        refs = plan["ref_rows"]
        parents = {(r["항목"], r["이수유형"]) for r in refs}
        for r in refs:
            child = r["항목"] in ("기본전공", "심화전공") and ("전공", r["이수유형"]) in parents
            if child:
                continue
            items.append((r["항목"], r, 0))
            if r["항목"] == "전공":
                items += [(c["항목"], c, 1) for c in refs if c["항목"] in ("기본전공", "심화전공") and c["이수유형"] == r["이수유형"]]
    single = bool(items) and all(r["이수유형"] in ("", "단수") for _, r, _ in items)
    out, sums = [], []
    for name, r, lv in items:
        label = name + (f" ({r['이수유형']})" if r["이수유형"] and r["이수유형"] != "단수" and plan["tier"] == "T3" and not (single) else "")
        if plan["tier"] == "T3" and r["이수유형"] == "단수" and not single:
            label = f"{name} (단수)"
        out.append({"name": label, "basis": _pct_example(r, grad) if grad else S.fmt_basis(r), "level": lv})
        if lv == 0 and r["항목"] == "전공" and any(i[2] == 1 and i[1]["항목"] in ("기본전공", "심화전공") for i in items):
            sums.append(f"전공 {S.fmt_value(r)} = 기본전공 + 심화전공의 합이에요.")
    return out, {"note": SINGLE_NOTE if single else "", "sums": sums}


def basis_rows(plan):
    """홈 카드 한 줄 요약용 상위 행만: [[이름, 기준]]와 빈 목록(호환용). 세부 항목은 표에서 들여써서 보여 준다"""
    entries, _ = basis_entries(plan)
    return [[e["name"], e["basis"]] for e in entries if e["level"] == 0], []


def basis_html(plan):
    entries, extra = basis_entries(plan)
    if not entries:
        return ""
    out = f'<div class="ck-src">{U.esc(extra["note"])}</div>' if extra["note"] else ""
    out += U.table(["영역", "기준"], [[e["name"], e["basis"]] for e in entries], levels=[e["level"] for e in entries])
    for sline in extra["sums"]:
        out += f'<div class="ck-src">{U.esc(sline)}</div>'
    return out


def access_guide(sc):
    with st.expander("내 이수 학점은 어디서 보나요?"):
        st.markdown(ACCESS_GUIDE.get(sc["univ"], ACCESS_GUIDE_DEFAULT))


def go_courses(view=None, hint=None):
    """개설 과목 페이지로 이동. view가 있으면 그 영역을 미리 고르고, hint가 있으면 안내를 띄운다(영역을 직접 고르면 사라진다)"""
    kp = keep()
    if view:
        kp["crs_area"] = view
    kp["crs_hint"] = hint
    st.session_state.pop("crs_area_w", None)
    st.session_state["page"] = "courses"


def courses_link_block(sc, stt):
    """내 졸업요건 맨 아래: 부족한 영역의 개설 과목으로 연결(배재 시범). 다른 대학은 버튼 없이 안내만"""
    if sc["univ"] != "배재":
        with st.container(key="card_courses_soon"):
            md('<div class="card-h">이번 학기 개설 과목</div>')
            st.caption("개설 과목 연결은 배재대에서 시범 제공 중이에요.")
        return
    if not CR.available():
        card_courses(sc)
        return
    with st.container(key="card_courses"):
        md('<div class="card-h">이번 학기 개설 과목</div>')
        rem = stt["rem"]
        if rem is None or not stt["any_area"]:
            st.caption("영역별 이수 학점까지 입력하면 부족한 영역의 개설 과목으로 바로 이어 드려요.")
            st.button("개설 과목 보기", key="crs_go_all", on_click=go_courses, width="stretch")
            return
        transfer = sc["entry"] == "편입"
        targets, pick = CR.deficit_targets(sc["year"], rem["areas"], transfer, stt["kids_input"])
        targets = [v for v in targets if v != "전공" or sc["dept"] == S.BASE_DEPT["배재"]]  # E23: 전공 개설 과목은 IT경영정보학과만 있다
        if targets or pick:
            st.caption("부족한 영역의 이번 학기 개설 과목 보기")
        for v in targets:
            st.button(f"{CR.AREA_LABEL[v]} 개설 과목 보기", key=f"crs_go_{v}", on_click=go_courses, args=(v,), width="stretch")
        if pick:
            st.button("교양 개설 과목 보기", key="crs_go_pick", on_click=go_courses, args=(None, CR.PICK_HINT), width="stretch")
            st.caption(CR.PICK_HINT)
        if not targets and not pick:
            st.caption("입력한 영역은 기준을 채웠어요. 궁금하면 개설 과목을 둘러볼 수 있어요.")
            st.button("개설 과목 보기", key="crs_go_all", on_click=go_courses, width="stretch")
        if transfer:
            st.caption("편입생은 교양 영역별 결과가 참고용이라 교양 개설 과목 연결은 하지 않아요. 전공만 이어 드려요.")


def page_remaining(sc):
    page_title("내 졸업요건", "정보만 고르면 졸업요건이 바로 보여요. 이수 학점을 알면 남은 학점도 계산해 드려요(선택).")
    if not need_year(sc) or not need_dept(sc):
        return
    univ, year = sc["univ"], sc["year"]
    transfer = sc["entry"] == "편입"
    plan = plan_for(sc)
    if plan["grad"] is None:
        for n in plan["notes"]:
            md(U.callout("warn", U.esc(n)))
        with st.container(key="card_rem_check"):
            show_checklist(sc)
        return
    grad = plan["grad"]
    ctx = ctx_of(sc)
    areas_on = plan["tier"] in ("T1", "T2")
    stt = remaining_state(sc, plan)
    cap_row = S.transfer_cap_row(univ, sc["transfer_grade"], grad["값"]) if transfer and sc.get("transfer_grade") else None
    # ① 입력 없이 바로 보이는 졸업요건
    with st.container(key="card_rem_req"):
        md('<div class="card-h">졸업하려면 이것들을 채워야 해요</div>')
        md(f'<div class="card-sub">졸업학점 <b>{U.esc(S.fmt_value(grad))}</b></div>')  # 대학·학번·학과는 페이지 제목에 있어 반복하지 않는다
        with st.expander("근거 보기"):
            st.markdown(f"`{grad['행ID']}` · 이수 방식 {plan['method'] or '단일'} · {grad['출처조항']}  \n쪽 {grad['출처쪽']} · 등급 {grad['출처등급']} · 상태 {grad['상태']}")
            if cap_row:
                st.markdown(S.transfer_cap_text(univ, sc["transfer_grade"], grad["값"]) + f"  \n`{cap_row['행ID']}` · {cap_row['출처조항']} · 쪽 {cap_row['출처쪽']} · 등급 {cap_row['출처등급']}")
        generic_note(sc)
        if plan["tier"] == "T3":
            md('<div class="ck-src">영역별 남은 학점은 계산하지 않고, 규정 표의 영역별 기준만 보여 드려요.</div>')
        bh = basis_html(plan)
        if bh:
            md(bh)
        show_checklist(sc)
    # ② 이수 학점을 알면(선택)
    with st.container(key="card_rem_main"):
        md('<div class="card-h">이수 학점을 알면 남은 학점을 계산해 드려요 (선택)</div>')
        if keep().pop("scroll_to", None) == "card_rem_main":
            scroll_script("card_rem_main")
        if transfer:  # 안내 상자 하나(인정학점 상한이 있으면 괄호로 함께)
            cap = f"(최대 {cap_row['값']}학점)" if cap_row else ""
            md(U.callout("info", f"편입 인정학점{cap}도 총 이수 학점에 포함해 넣어 주세요. 영역 구분은 학과에서 확인하세요."))
        num("지금까지 이수한 총 학점", f"tot|{ctx}", f"tot|{ctx}")
        big_block(sc, stt)
        if plan.get("transfer") and stt["rem"] is not None:  # 배재 편입: 전공 기준(45·24)으로 남은 학점 한 줄
            major = next((a for a in stt["rem"]["areas"] if a["name"] == "전공"), None)
            if major and major["done"] > 0:
                md(U.callout("concl", f'전공 기준 <b>{major["min"]:g}학점</b> 중 <b>{major["remaining"]:g}학점</b> 남았어요 '
                                      f'({U.esc(plan["transfer"]["grade"])} 편입, 전적대학 인정 전공 학점 포함). 행 {U.esc(plan["transfer"]["row"]["행ID"])}'))
        if not areas_on:
            md(unsupported_notice(plan))
        access_guide(sc)  # ③ 내 이수 학점은 어디서 보나요?
    if areas_on:
        with st.expander("영역별 확인 (선택)"):
            st.caption((S.TRANSFER_MAJOR_NOTE if plan.get("transfer") else
                        "참고용이에요. 편입 인정학점이 영역에 안 들어가 실제보다 크게 나올 수 있어요. 편입 인정학점의 영역 구분은 학과에서 확인하세요.")
                       if transfer else "영역별로 넣으면 영역마다 얼마나 남았는지 볼 수 있어요.")
            cols = st.columns(min(3, len(plan["areas"])))
            for i, a in enumerate(plan["areas"]):
                with cols[i % len(cols)]:
                    k = f"done|{ctx}|{a['name']}"
                    num(f"{a['name']} (기준 {S.fmt_value(a['row'])})", k, k)

            def _sync_kids():
                keep()[f"kids_on|{ctx}"] = st.session_state[f"kids_on|{ctx}"]
            if st.checkbox("세부 항목까지 보기", key=f"kids_on|{ctx}", value=bool(keep().get(f"kids_on|{ctx}")), on_change=_sync_kids):
                st.caption(KIDS_GUIDE.get(univ, KIDS_GUIDE_DEFAULT))
                for a in plan["areas"]:
                    for r in a["children"]:
                        k = f"kid|{ctx}|{r['항목']}"
                        num(f"{CR.item_label(r['항목'])} (기준 {S.fmt_value(r)})", k, k)
        rem = stt["rem"]
        if rem is not None and stt["any_area"]:
            with st.expander("영역별 결과 (참고)"):
                st.metric("영역별 남은 학점의 합(참고)", f"{rem['area_remaining_sum']:g}", help="영역마다 부족한 학점만 더한 값. 졸업까지 남은 학점과 다를 수 있어요.")
                df = pd.DataFrame([{"영역": a["name"], "기준": S.fmt_value(a["row"]), "이수": a["done"], "남은 학점": a["remaining"], "비고": a["note"]} for a in rem["areas"]])
                st.dataframe(df, hide_index=True, width="stretch")
                for a in rem["areas"]:
                    shown = [k for k in a["kids"] if k["done"] or k["remaining"]]
                    if any(k["done"] for k in a["kids"]):
                        st.markdown(f"**{a['name']} 세부 항목**")
                        st.dataframe(pd.DataFrame([{"항목": CR.item_label(k["name"]), "기준": S.fmt_value(k["row"]), "이수": k["done"], "남은 학점": k["remaining"]} for k in shown]),
                                     hide_index=True, width="stretch")
    lines = reference_lines(plan, stt["rem"])
    if lines:
        with st.expander("참고"):
            for ln in lines:
                st.markdown(f"- {ln}")
    # ④ 부족한 영역의 개설 과목으로 연결(배재 시범)
    courses_link_block(sc, stt)


# ---------- 학사 선택 비교 ----------

def compare_table_html(r):
    rows = []
    for t in r["table"]:
        rows.append([t["name"], S.fmt_value(t["major"]) if t["major"] else "확인 불가", S.fmt_value(t["extra"]) if t["extra"] else "확인 불가",
                     f"{t['total']:g}학점" if t["total"] is not None else "확인 불가"])
    return U.table(["선택", "주전공 요구 학점", "추가 이수", "전공학점 합"], rows, total_col=3)


def compare_conclusion_html(r):
    if r["full"]:
        if r["less"]:
            return U.callout("concl", f'<b>{U.esc(r["less"])}</b>이 전공학점이 <b>{r["diff"]:g}학점</b> 더 적어요. '
                                      "전공학점만 비교한 거예요. 신청 자격·평점·교직 등은 따로 확인하세요.")
        return U.callout("concl", "두 선택의 전공학점 합이 같아요.")
    return U.callout("warn", "한쪽의 주전공 요구 학점이 학과별로 달라 기준표에 없어서, 합을 비교하지 않았어요(학과 확인 필요).")


def page_compare(sc):
    page_title("학사 선택 비교", "부전공 ↔ 복수·다전공. 전공학점 합 = 주전공 요구 학점 + 추가로 이수할 학점")
    if not need_year(sc) or not need_dept(sc, "비교 결과"):
        return
    univ, year, dept = sc["univ"], sc["year"], sc["dept"]
    generic_note(sc)
    r = S.compare(univ, year, dept)
    if not r["ok"]:
        md(U.callout("warn", "이 조건의 부전공·복수(다)전공 학점을 기준표에서 확인하지 못했어요(확인 불가). " + U.esc(r.get("why") or "")))
        return
    with st.container(key="card_cmp_main"):
        md(compare_table_html(r))
        md(compare_conclusion_html(r))
        if r.get("floor_note"):
            md(U.callout("info", U.esc(r["floor_note"])))
        for n in r["notes"]:
            md(U.callout("info", U.esc(n)))
        md(f'<div class="ck-src">근거 행: {U.esc(", ".join(x["행ID"] for x in r["rows"]))}</div>')
        for why in r["reasons"]:
            st.caption(why)
    q = S.explain_question(univ, year, dept)
    if q and st.button("AI 설명 듣기", key=f"explain|{univ}|{year}|{dept}", type="primary"):
        with st.spinner("설명을 만드는 중이에요…"):
            out, log_id = ask(q, {**sc, "univ": None, "year": None, "dept": None})
        st.session_state["explain"] = (out, log_id) if out else None
    ex = st.session_state.get("explain")
    if ex and ex[0] and ex[0]["question_used"] == q:
        show_answer(ex[0], ex[1], key=f"explain{ex[1]}")
    if q is None:
        st.caption("이 조건은 설명 질문이 만들어지지 않아 위 표만 보여 드려요.")


# ---------- 이번 학기 개설 과목(자리만) ----------

def card_courses(sc, full=False):
    """배재대 개설 과목 안내. full=False(홈·남은 학점)는 요약+이동 버튼, full=True(개설 과목 페이지)는 영역·요일 필터와 목록"""
    if sc["univ"] != "배재":
        with st.container(key="card_courses_soon"):
            md(f'<div class="card-h">이번 학기 개설 과목 {U.badge("soon", "준비 중")}</div>')
            st.caption(f"{sc['univ']}대는 개설 과목 안내를 아직 지원하지 않아요. 배재대부터 준비하고 있어요.")
        return
    if not CR.available():
        with st.container(key="card_courses_soon"):
            md('<div class="card-h">이번 학기 개설 과목</div>')
            st.caption("개설 과목 자료 파일(data/courses_baejae_2026-2.json)이 없어요. src/build_courses.py로 만들어 주세요.")
        return
    if not full:
        with st.container(key="card_courses"):
            md('<div class="card-h">이번 학기 개설 과목</div>')
            st.caption("배재대 2026-2학기 교양·전공 개설 과목을 영역과 요일로 찾아볼 수 있어요.")
            st.button("개설 과목 보기", key="to_courses", on_click=goto, args=("courses",), width="stretch")
        return
    show_courses(sc)


def _kept_widget(kind, label, kkey, wkey, **kw):
    """페이지를 옮겨도 값이 남는 multiselect/checkbox(session_state 메모리만, 저장 안 함)"""
    def _sync():
        keep()[kkey] = st.session_state[wkey]
    if kind == "multi":
        return st.multiselect(label, default=keep().get(kkey, []), key=wkey, on_change=_sync, **kw)
    return st.checkbox(label, value=keep().get(kkey, False), key=wkey, on_change=_sync, **kw)


def course_html(c, days, show_grade=False):
    """과목 하나(분반 목록은 접기). 강한 제한 문구가 있는 분반 수는 배지로, 비고 원문은 모두 작은 글씨로 보여 준다"""
    secs = CR.filter_sections(c, days)
    nlim = CR.remaining_count(secs)
    head = f'<b>{U.esc(c["name"])}</b> · {U.esc(c["credit"])}학점' + (f' · {U.abbr_html(c["kind"])}' if c["kind"] in ("전필", "전선") else "") + f' · 분반 {len(secs)}개'
    if show_grade and c.get("grade"):
        head += f' · 대상 {U.esc(c["grade"])}'
    if nlim:
        head += " " + U.badge("warn", "수강 제한 있음" if nlim == len(secs) else f"수강 제한 있음 {nlim}개")
    rows = ""
    for s in secs:
        t = U.esc(s["시간"]) if s["요일"] else "시간 미정"
        cap = f'수강 {U.esc(s["수강인원"])}명 / 정원 {U.esc(s["인원제한"])}명' if s["인원제한"] else f'수강 {U.esc(s["수강인원"])}명'
        lim = " " + U.badge("warn", "수강 제한 있음") if s["제한"] else ""
        memo = f'<div class="crs-memo">비고: {U.esc(s["비고"])}</div>' if s["비고"] else ""
        rows += f'<div class="crs-sec"><b>{U.esc(s["분반"])}분반</b> · {U.esc(s["담당교수"] or "교수 미정")} · {t} · {cap}{lim}{memo}</div>'
    return f'<details class="crs"><summary>{head}</summary>{rows}</details>'


def subgroup_label(sec, view):
    if view == "공유혁신":
        part = sec["영역"].split("_", 1)[1]
        return {"혁신교육과미래설계": "혁신교육과미래설계 (전필, P/F)", "전공융합설계": "전공융합설계", "비전설계": "비전설계 · " + sec["하위"]}[part]
    if view == "전공":
        return {"전필": "전공필수", "전선": "전공선택"}.get(sec["하위"], sec["하위"])
    return sec["하위"]


COURSE_NOTES = {
    "교선": "교선은 영역 정보가 없어요. 교선 전체 목록이에요.",
    "교양_비전설계": "비전설계 영역에서 1과목(3학점)을 이수해요(기준표 BJ-016).",
    "공유혁신": "공유혁신은 전공융합설계 9학점 이상(BJ-034), 비전설계(진로·취창업) 1과목 3학점(BJ-035), 혁신교육과미래설계 P/F 필수(BJ-032)예요. "
              "자기설계 영역 과목이 비전설계 3학점에 들어가는지는 학과에 확인하세요. 전공탐색(0.5학점×2, BJ-033)은 개설 자료에서 과목을 찾지 못했어요.",
    "공유혁신_기타": "AI융합전공 공통·마이크로디그리 편성 과목이에요. 어느 졸업 영역에 들어가는지는 자료에 없어요.",
    "교양_영역미표시": "교필선인데 비고에 영역 표시가 없는 과목이에요.",
    "타학과전공": "다른 학과 학생 전용이 많아요. 비고를 꼭 확인하세요.",
    "교양필수": "AI와SW 영역 등은 학과별로 분반이 나뉘어요. 비고의 해당 학과를 확인하세요.",
}


def show_courses(sc):
    secs_all = CR.load()
    year = sc["year"]
    if not isinstance(year, int) or not CR.view_areas(year):
        md(U.callout("info", "왼쪽에서 2022~2026학번을 골라 주세요. 학번마다 영역이 달라요."))
        return
    with st.container(key="card_courses"):
        md('<div class="card-h">이번 학기 개설 과목 (배재대)</div>')
        if keep().get("crs_hint"):
            md(U.callout("info", U.esc(keep()["crs_hint"])))
        is_base = sc["dept"] == S.BASE_DEPT["배재"]
        views = [v for v in CR.view_areas(year) if v != "전공" or is_base]
        c1, c2 = st.columns([1, 1])
        with c1:
            if _kept_widget("check", "다른 학과 전공(공유대학 가상) 과목도 보기", "crs_virtual", "crs_virtual_w"):
                views = views + ["타학과전공"]
            kept = keep().get("crs_area")
            def _sync_area():
                keep()["crs_area"] = st.session_state["crs_area_w"]
                keep()["crs_hint"] = None
            view = st.selectbox("영역", views, index=views.index(kept) if kept in views else 0, format_func=lambda v: CR.AREA_LABEL[v], key="crs_area_w",
                                on_change=_sync_area, help=U.ABBR_HELP)
        with c2:
            days = _kept_widget("multi", "요일 (고르지 않으면 전체)", "crs_days", "crs_days_w", options=list(CR.DAYS[:6]) + ["시간 미정"])
            grades = _kept_widget("multi", "대상 학년 (전공만, 고르지 않으면 전체)", "crs_grades", "crs_grades_w", options=CR.GRADES) if view == "전공" else []
        if not is_base:
            st.caption("전공 과목은 IT경영정보학과만 지원해요. 교양 영역은 모든 학과에 같이 보여 드려요.")
        if sc["entry"] == "편입":
            md(U.callout("info", "편입생은 편입 전 학년의 교양필수·전공필수가 면제될 수 있어요(기준표 BJ-060). 해당 여부는 학과에서 확인하세요."))
        pool = CR.sections_in(secs_all, year, view)
        names = {s["과목코드"]: s["과목명"] for s in pool}
        if pool:
            opts = sorted(names, key=lambda k: names[k])

            def _sync_done():  # 다른 영역에서 체크한 과목은 그대로 두고 이 영역 선택분만 갈아 끼운다
                keep()["crs_done"] = [c for c in keep().get("crs_done", []) if c not in names] + list(st.session_state["crs_done_w"])
            st.multiselect("이미 이수한 과목(목록에서 뺄게요)", options=opts, default=[c for c in keep().get("crs_done", []) if c in names], key=f"crs_done_w", on_change=_sync_done,
                           format_func=lambda k: names.get(k, k))
        done_all = set(keep().get("crs_done", []))
        courses = [c for c in CR.group_courses([s for s in pool if s["과목코드"] not in done_all]) if CR.filter_sections(c, days) and (not grades or c["grade"] in grades)]
        nsec = sum(len(CR.filter_sections(c, days)) for c in courses)
        nexcl = len(set(names) & done_all)
        md(f'<div class="card-sub"><b>{U.abbr_html(CR.AREA_LABEL[view])}</b> · {len(courses)}과목 · {nsec}분반'
           + (f' · 요일 {U.esc(", ".join(days))}' if days else "") + (f' · {U.esc(", ".join(grades))}' if grades else "") + (f' · 이수 제외 {nexcl}과목' if nexcl else "") + "</div>")
        if view in COURSE_NOTES:
            st.caption(COURSE_NOTES[view])
        if days and "시간 미정" not in days:
            hidden = sum(1 for s_ in pool if not s_["요일"] and s_["과목코드"] not in done_all)
            if hidden:
                st.caption(f"시간이 정해지지 않은 분반 {hidden}개는 요일을 고르면 빠져요. '시간 미정'을 같이 고르면 볼 수 있어요.")
        if not courses:
            st.info("조건에 맞는 개설 과목이 없어요. 요일이나 영역을 바꿔 보세요.")
        groups = {}
        for c in courses:
            groups.setdefault(subgroup_label(c["sections"][0], view), []).append(c)
        parts = ""
        for g, cs in groups.items():
            if g and (len(groups) > 1 or view in ("공유혁신", "전공")):
                parts += f'<div class="crs-group">{U.abbr_html(g)} · {len(cs)}과목</div>'
            parts += "".join(course_html(c, days, view == "전공") for c in cs)
        if parts:
            md(parts)
        md(f'<div class="ck-src" style="margin-top:.8rem">{U.esc(CR.FOOTER)}{" " + U.esc(CR.GRADE_LINE) if view != "전공" else ""} 수강 가능 여부는 판단하지 않아요. 비고의 제한 문구는 꼭 직접 확인하세요. 이수한 과목 표시는 이 화면을 닫으면 사라져요.</div>')


def page_courses(sc):
    page_title("이번 학기 개설 과목", "영역과 요일로 개설 과목을 찾아보는 기능이에요. 지금은 배재대만 지원해요.")
    card_courses(sc, full=True)


# ---------- 홈·규정 안내 ----------

def scroll_script(key):
    """st.container(key=...) 위치로 부드럽게 스크롤(브라우저에서만 동작하는 보조 기능, 실패해도 페이지 이동은 그대로).
    우리가 만든 고정 문자열만 st.iframe에 넣는다(사용자 입력은 넣지 않는다)."""
    try:
        st.iframe("<script>setTimeout(function(){var t=window.parent.document.querySelector('.st-key-" + key + "');"
                  "if(t){t.scrollIntoView({behavior:'smooth',block:'start'});}},350);</script>", height=1)
    except Exception:
        pass


HOME_STEPS = [
    (1, True, "왼쪽에서 내 정보를 골라요", "대학·학번·학과·입학 구분을 골라요. 편입생은 편입 연도보다 2년 앞 학번을 골라요.", "", None),
    (2, True, "내 졸업요건을 확인해요", "학점을 몰라도 돼요. 졸업학점, 영역별 기준, 학점 말고 필요한 요건이 먼저 보여요.", "", ("내 졸업요건 보기 →", "remaining")),
    (3, False, "이수 학점을 넣으면 남은 학점이 보여요", "포털의 졸업사정 메뉴(배재대는 '졸업자가진단')에서 이수 학점을 확인할 수 있어요.", "선택", None),
    (4, False, "부족한 영역의 이번 학기 과목을 찾아요", "2026-2학기 개설 과목을 영역과 요일로 찾아볼 수 있어요.", "배재대", None),
]
HOME_SITUATIONS = [
    ("부전공이랑 복수전공 중에 뭐가 덜 힘들지?", "학사 선택 비교 →", "compare"),
    ("휴학은 몇 학기까지 되지? 재수강은?", "규정 질문 →", "ask"),
    ("편입하면 몇 학점 인정받고, 뭘 더 들어야 하지?", "규정 질문 →", "ask"),
]


def page_home():
    """시작하기: 서비스 소개와 쓰는 순서만 보여 준다. 계산·질문은 각 메뉴에서 하고, 여기서는 이동 버튼만 둔다."""
    md('<div class="hero"><div class="hero-ico"></div><div><div class="hero-title">졸업나침반 시작하기</div>'
       '<div class="hero-sub">대전 5개 대학의 졸업요건을, 학칙·세칙 근거와 함께 확인하는 곳이에요.</div></div></div>')
    md('<div class="home-h">이렇게 써 보세요</div>')
    for n, filled, title, desc, tag, btn in HOME_STEPS:
        with st.container(key=f"hstep_{n}"):
            tag_html = f'<span class="stp-tag">{U.esc(tag)}</span>' if tag else ""
            md(f'<div class="stp"><div class="stp-no{" on" if filled else ""}">{n}</div>'
               f'<div><div class="stp-t">{U.esc(title)}{tag_html}</div><div class="stp-d">{U.esc(desc)}</div></div></div>')
            if btn:  # 설명 바로 아래 줄, 글자 시작 위치에 맞춤(CSS)
                st.button(btn[0], key="go_req", type="tertiary", on_click=goto, args=(btn[1],))
    md('<div class="home-h">이럴 때 쓰세요</div>')
    for i, (q, label, page) in enumerate(HOME_SITUATIONS, 1):
        with st.container(key=f"hsit_{i}"):
            left, right = st.columns([7, 2], vertical_alignment="center")
            with left:
                md(f'<div class="sit-q">“{U.esc(q)}”</div>')
            with right:
                st.button(label, key=f"go_sit_{i}", type="tertiary", on_click=goto, args=(page,))
    md('<div class="home-h">알아 두세요</div>')
    md('<div class="note-box"><ul>'
       "<li>답마다 [1]처럼 근거 조항이 붙어요. '근거 보기'에서 규정명·조항·쪽을 볼 수 있어요.</li>"
       f"<li>규정에서 못 찾은 건 지어내지 않고 {U.badge('warn', '확인 불가')}로 알려 줘요.</li>"
       "<li>2022~2026학번 기준이에요. 최종 확인은 학과 사무실에서 하세요. 입력한 학점은 저장하지 않아요.</li>"
       "</ul></div>")


def page_ask(sc):
    page_title("규정 질문", "학칙·세칙·편람을 근거로 답하고, 근거를 함께 보여 줘요. 확인되지 않은 내용은 '확인 불가'로 알려 드려요.")
    with st.container(key="card_ask_main"):
        hist = qa_block(sc, "ask")
        show_history(hist, "a")
        if not hist:
            st.caption("질문을 입력하거나 위 예시를 눌러 보세요.")


# ---------- 개발자 모드 ----------

def page_dev():
    page_title("개발자 · 로그", "개발자 모드(?dev=1)에서만 보여요.")
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


def route(sc):
    page = st.session_state.get("page", "home")
    if page == "dev" and not is_dev():
        page = "home"
    if page != "home":
        header(sc)
    {"home": page_home, "ask": lambda: page_ask(sc), "remaining": lambda: page_remaining(sc), "compare": lambda: page_compare(sc),
     "courses": lambda: page_courses(sc), "dev": page_dev}.get(page, page_home)()
