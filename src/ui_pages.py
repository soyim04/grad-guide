"""졸업나침반 화면 페이지(7단계 새 디자인). 계산·조회·엔진은 기존 함수를 그대로 부르고, 여기서는 배치와 표시만 한다.

페이지: 홈 · 학사 규정 안내 · 남은 학점 계산 · 학사 선택 비교 · 이번 학기 개설 과목 · (개발자 모드) 로그
- 사이드바 입력은 바로 적용된다(저장 버튼 없음). 이수 학점·평점은 session_state 메모리에만 두고 디스크·로그에는 쓰지 않는다.
- 페이지를 옮기면 그 페이지에서 그려지지 않은 위젯의 값은 Streamlit이 지우므로, 학점 입력은 `keep` 사전에 따로 복사해 두고 위젯 초기값으로 읽는다.
- 학생 화면에는 응답 시간·비용·로그를 보이지 않는다. 주소에 `?dev=1`이 있을 때만 보인다.
"""

import os
from pathlib import Path

import pandas as pd
import streamlit as st

import engine
import service_calc as S
import ui_style as U
from service_log import DB_PATH, LogDB

ROOT = Path(__file__).resolve().parent.parent
UNIVS = list(S.BASE_DEPT)
YEAR_CHOICES = [*S.YEARS, "모름", engine.OUT_OF_RANGE]
LONG_ANSWER = 300  # 이 글자 수를 넘으면 첫 문단만 먼저 보여 주고 나머지는 접는다
EXAMPLES = ["졸업하려면 총 몇 학점이 필요해?", "부전공은 몇 학점 이수해야 해?", "재수강은 어떻게 하나요?", "부전공과 복수전공 중 어느 쪽이 전공학점이 적어?"]
PAGES = [("home", "홈", ":material/home:"), ("ask", "학사 규정 안내", ":material/forum:"), ("remaining", "남은 학점 계산", ":material/calculate:"),
         ("compare", "학사 선택 비교", ":material/compare_arrows:"), ("courses", "이번 학기 개설 과목 · 준비 중", ":material/menu_book:")]
DEV_PAGE = ("dev", "개발자 · 로그", ":material/terminal:")
ROUTE_LABEL = {"조회": "기준표 조회", "계산": "기준표 계산", "규정 검색": "규정 검색", "범위 밖": "범위 확인"}
KIND_BADGE = {"요건": ("req", "요건"), "없음": ("none", "없음"), "확인불가": ("warn", "확인 불가 · 학과 확인"), "해당없음": ("na", "해당 없음"), "안내": ("info", "안내")}
DISCLAIMER = "2022~2026학번 기준 · 최종 확인은 학과 사무실에서"


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
    md(f'<div class="topbar"><div><div class="topbar-title">{U.esc(sc["univ"])}대 {U.esc(yr)} · {U.esc(sc["dept"])}</div>'
       f'<div class="topbar-sub">{U.esc(sc["entry"])} · 왼쪽 내 정보를 바꾸면 모든 화면에 바로 적용돼요</div></div>'
       f'<div class="pill">{U.esc(DISCLAIMER)}</div></div>')


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
    sb.markdown('<div class="brand"><div class="brand-ico">🧭</div><div class="brand-name">졸업나침반</div></div>'
                '<div class="brand-sub">5개 대학의 학사 규정을 근거로 답변해요</div>', unsafe_allow_html=True)
    pages = PAGES + ([DEV_PAGE] if is_dev() else [])
    cur = st.session_state.get("page", "home")
    if cur not in [p[0] for p in pages]:
        cur = st.session_state["page"] = "home"
    for pid, label, icon in pages:
        with sb.container(key=f"navitem_{pid}" + ("__on" if pid == cur else "")):
            st.button(label, key=f"nav_{pid}", icon=icon, on_click=goto, args=(pid,), width="stretch")
    sb.markdown('<div class="side-h">내 정보</div>', unsafe_allow_html=True)
    univ = sb.selectbox("대학", UNIVS, key="univ")
    year_choice = sb.selectbox("학번(입학년도)", YEAR_CHOICES, format_func=lambda y: f"{y}학번" if isinstance(y, int) else y, key="year")
    transfer_slot = sb.container()  # 입학 구분이 편입이면 학번 선택 바로 아래에 안내를 채운다
    base = S.BASE_DEPT[univ]
    others = [t for t in S.grad_targets(univ) if t != base]
    kind = sb.radio("학과", [f"{base} (경영 계열)", "그 외 학과"], key=f"deptkind_{univ}")
    if kind.startswith(base) or not others:
        dept = base
    else:
        dept = sb.selectbox("학과·계열 선택", others, key=f"dept_{univ}")
        sb.caption("경영 계열 외 학과는 총 졸업학점까지만 계산해요. 영역별 기준은 기준표에 없어요.")
    entry = sb.radio("입학 구분", S.ENTRY_TYPES, horizontal=True, key="entry")
    transfer_grade = None
    if entry == "편입" and S.uses_transfer_grade(univ):  # 배재 일반편입: 편입 학년에 따라 전공 기준이 다르다(E15)
        transfer_grade = sb.radio("편입 학년 (일반편입)", S.TRANSFER_GRADES, index=S.TRANSFER_GRADES.index(S.TRANSFER_DEFAULT_GRADE), horizontal=True, key="transfer_grade")
    if entry == "편입":
        note = S.transfer_note(univ, transfer_grade)
        with transfer_slot:
            st.info(note["text"], icon="🔁")
            if note["basis"]:
                with st.expander("근거 보기"):
                    for line in note["basis"]:
                        st.markdown(f"- {line}")
    teacher = False
    if S.has_teacher_rows(univ):
        teacher = sb.checkbox("사범대학 소속 또는 교직이수자", key=f"teacher_{univ}")
    sb.divider()
    sb.markdown('<div class="side-note">입력한 학점·평점은 저장하지 않아요.<br>질문 문장은 서비스 개선을 위해 기록돼요.</div>', unsafe_allow_html=True)
    year = year_choice if isinstance(year_choice, int) else (engine.OUT_OF_RANGE if year_choice == engine.OUT_OF_RANGE else None)
    return {"univ": univ, "year": year, "dept": dept, "entry": entry, "teacher": teacher, "base": base, "transfer_grade": transfer_grade}


def plan_for(sc):
    """영역별 계획. 배재 일반편입이면 전공 기준을 편입 행으로 바꾼다(홈·남은 학점 페이지 공용)"""
    plan = S.area_plan(sc["univ"], sc["dept"], sc["year"])
    if sc["entry"] == "편입" and sc.get("transfer_grade"):
        plan = S.apply_transfer(plan, sc["transfer_grade"])
    return plan


# ---------- 표시 부품 ----------

def checklist_html(items, limit=None):
    out = []
    for it in (items if limit is None else items[:limit]):
        cls, label = KIND_BADGE.get(it["kind"], ("na", it["kind"]))
        src = ""
        if it.get("src"):
            s = it["src"]
            src = f'<div class="ck-src">{U.esc(s["id"])} · {U.esc(s["source"])} · 쪽 {U.esc(s["pages"])} · 등급 {U.esc(s["grade"])} · 상태 {U.esc(s["status"])}</div>'
        extra = f'<div class="ck-src">{U.esc(it["extra"])}</div>' if it.get("extra") else ""
        out.append(f'<div class="ck ck-{cls}"><span class="badge b-{cls}">{U.esc(label)}</span>'
                   f'<div><b>{U.esc(it["title"])}</b><div class="ck-text">{U.esc(it["text"])}</div>{src}{extra}</div></div>')
    return "".join(out)


def show_checklist(sc, limit=None, title=True):
    items = S.checklist(sc["univ"], sc["year"], sc["dept"], sc["entry"], sc["teacher"], sc.get("transfer_grade"))
    if title:
        md('<div class="card-h" style="font-size:1rem">학점 외 이수 요건</div>')
    if not items:
        st.caption("기준표에 이 조건의 학점 외 요건이 없어요.")
        return
    md(checklist_html(items, limit))
    if limit is not None and len(items) > limit:
        st.caption(f"그 밖에 {len(items) - limit}개 요건은 '남은 학점 계산'에서 볼 수 있어요.")


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
            top = f'{nums}<span>{U.esc(s["title"])}</span>{U.badge("grade", s["grade"])}'
            meta = (f'대상 {U.esc(s["target"])} · 값 <b>{U.esc(s["value"])}</b> · 상태 {U.esc(s["status"])}<br>'
                    f'{U.esc(s["id"])} · {U.esc(s["article"])} · 쪽 {U.esc(s["pages"])}')
        else:
            ed = s.get("edition") or ""
            ed_chip = U.badge("cur" if ed.startswith("현행") else "old", ed) if ed else ""
            top = f'{nums}<span>{U.esc(s["title"])}</span><span>{U.esc(s["article"])}</span>{ed_chip}{U.badge("grade", s["grade"])}'
            meta = f'{U.esc(s["univ"])} · {U.esc(s["pages"])}'
        cards.append(f'<div class="src"><div class="src-top">{top}</div><div class="src-meta">{meta}</div></div>')
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
        md(U.callout("soft", "남은 학점 계산의 체크리스트에 관련 요건이 있을 수 있어요. (항목: " + U.esc(" · ".join(hint)) + ")"))
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
    univ, year, dept = sc["univ"], sc["year"], sc["dept"]
    ctx = f"{univ}|{year}|{dept}"
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
    return {"rem": rem, "fallback": fallback, "any_area": any_area, "areas_on": areas_on, "ctx": ctx}


def unsupported_notice(plan):
    return U.callout("info", "<b>영역별 남은 학점은 이 조건에서 지원하지 않아요.</b> 총 졸업학점까지만 계산해요. "
                             "영역별 기준이 기준표에 없거나(경영 계열 외 학과 등) 영역 구분을 계산에 쓸 수 없는 대학이에요. 세부는 학과에 확인하세요.")


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
        st.caption("총 이수 학점을 입력하면 졸업까지 남은 학점을 알려 드려요.")


def reference_lines(plan, rem):
    """'참고' 접기에 넣을 안내(쉬운 말). 학생이 할 수 있는 일이 없는 표 불일치·영역 미지정 학점은 여기로 모은다."""
    lines = [n for n in plan["notes"]]
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


def card_remaining_home(sc):
    with st.container(key="card_home_rem"):
        md('<div class="card-h">남은 학점 계산</div>')
        if not need_year(sc):
            return
        plan = plan_for(sc)
        if plan["grad"] is None:
            for n in plan["notes"]:
                md(U.callout("warn", U.esc(n)))
            return
        ctx = f"{sc['univ']}|{sc['year']}|{sc['dept']}"
        num("지금까지 이수한 총 학점", f"tot|{ctx}", f"home_tot|{ctx}")
        stt = remaining_state(sc, plan)
        big_block(sc, stt)
        show_checklist(sc, limit=2)
        st.button("영역별 이수 현황 보기", key="home_to_rem", on_click=goto, args=("remaining",), width="stretch")


def page_remaining(sc):
    page_title("남은 학점 계산", "총 이수 학점만 넣어도 졸업까지 남은 학점을 알려 드려요. 영역별 입력은 선택이에요.")
    if not need_year(sc):
        return
    univ, year, dept = sc["univ"], sc["year"], sc["dept"]
    transfer = sc["entry"] == "편입"
    plan = plan_for(sc)
    if plan["grad"] is None:
        for n in plan["notes"]:
            md(U.callout("warn", U.esc(n)))
        with st.container(key="card_rem_check"):
            show_checklist(sc)
        return
    grad = plan["grad"]
    ctx = f"{univ}|{year}|{dept}"
    areas_on = plan["tier"] in ("T1", "T2")
    stt = remaining_state(sc, plan)
    with st.container(key="card_rem_main"):
        md(f'<div class="card-sub"><b>{U.esc(univ)}대 {year}학번 · {U.esc(dept)}</b> — 졸업학점 <b>{U.esc(S.fmt_value(grad))}</b></div>')
        with st.expander("근거 보기"):
            st.markdown(f"`{grad['행ID']}` · 이수 방식 {plan['method'] or '단일'} · {grad['출처조항']}  \n쪽 {grad['출처쪽']} · 등급 {grad['출처등급']} · 상태 {grad['상태']}")
        if transfer:
            md(U.callout("info", "편입 인정학점도 총 이수 학점에 포함해 넣어 주세요. 편입 인정학점의 영역 구분은 학과에서 확인하세요."))
            if sc.get("transfer_grade"):
                cap = S.transfer_cap_text(univ, sc["transfer_grade"], grad["값"])
                if cap:
                    md(U.callout("soft", U.esc(cap)))
        num("지금까지 이수한 총 학점", f"tot|{ctx}", f"tot|{ctx}")
        big_block(sc, stt)
        if plan.get("transfer") and stt["rem"] is not None:  # 배재 편입: 전공 기준(45·24)으로 남은 학점 한 줄
            major = next((a for a in stt["rem"]["areas"] if a["name"] == "전공"), None)
            if major and major["done"] > 0:
                md(U.callout("concl", f'전공 기준 <b>{major["min"]:g}학점</b> 중 <b>{major["remaining"]:g}학점</b> 남았어요 '
                                      f'({U.esc(plan["transfer"]["grade"])} 편입, 전적대학 인정 전공 학점 포함). 행 {U.esc(plan["transfer"]["row"]["행ID"])}'))
        if not areas_on:
            md(unsupported_notice(plan))
    with st.container(key="card_rem_check"):
        show_checklist(sc)
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
                for a in plan["areas"]:
                    for r in a["children"]:
                        k = f"kid|{ctx}|{r['항목']}"
                        num(f"{r['항목']} (기준 {S.fmt_value(r)})", k, k)
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
                        st.dataframe(pd.DataFrame([{"항목": k["name"], "기준": S.fmt_value(k["row"]), "이수": k["done"], "남은 학점": k["remaining"]} for k in shown]),
                                     hide_index=True, width="stretch")
    lines = reference_lines(plan, stt["rem"])
    if lines or plan["tier"] == "T3":
        with st.expander("참고"):
            for ln in lines:
                st.markdown(f"- {ln}")
            if plan["tier"] == "T3":
                rows = [{"항목": r["항목"], "이수유형": r["이수유형"] or "-", "기준": S.fmt_value(r), "조건": r["조건"], "행ID": r["행ID"], "출처": r["출처조항"][:60]}
                        for r in plan["ref_rows"]]
                st.markdown("기준표의 영역별 기준(남은 학점은 계산하지 않아요)")
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    card_courses(sc)


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


def card_compare_home(sc):
    with st.container(key="card_home_cmp"):
        md('<div class="card-h">학사 선택 비교</div>')
        if not need_year(sc):
            return
        r = S.compare(sc["univ"], sc["year"], sc["dept"])
        if not r["ok"]:
            md(U.callout("warn", "이 조건의 부전공·복수(다)전공 학점을 기준표에서 확인하지 못했어요(확인 불가). " + U.esc(r.get("why") or "")))
            return
        md(compare_table_html(r))
        md(compare_conclusion_html(r))
        md(f'<div class="ck-src">근거 행: {U.esc(", ".join(x["행ID"] for x in r["rows"]))}</div>')
        if S.explain_question(sc["univ"], sc["year"], sc["dept"]):  # 설명 질문이 만들어지는 조건에서만(한남 2023~·목원 등)
            st.button("AI 설명 듣기", key="home_to_cmp", on_click=goto, args=("compare",), width="stretch")
        else:
            st.button("비교 자세히 보기", key="home_to_cmp", on_click=goto, args=("compare",), width="stretch")


def page_compare(sc):
    page_title("학사 선택 비교", "부전공 ↔ 복수·다전공. 전공학점 합 = 주전공 요구 학점 + 추가로 이수할 학점")
    if not need_year(sc):
        return
    univ, year, dept = sc["univ"], sc["year"], sc["dept"]
    r = S.compare(univ, year, dept)
    if not r["ok"]:
        md(U.callout("warn", "이 조건의 부전공·복수(다)전공 학점을 기준표에서 확인하지 못했어요(확인 불가). " + U.esc(r.get("why") or "")))
        return
    with st.container(key="card_cmp_main"):
        md(compare_table_html(r))
        md(compare_conclusion_html(r))
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

def card_courses(sc):
    with st.container(key="card_courses"):
        if sc["univ"] == "배재":
            md(f'<div class="card-h">이번 학기 개설 과목 {U.badge("soon", "준비 중")}</div>')
            st.caption("남은 학점에 맞는 개설 과목을 여기에 보여 줄 예정이에요(배재대 먼저).")
        else:
            md(f'<div class="card-h">이번 학기 개설 과목 {U.badge("soon", "준비 중")}</div>')
            st.caption(f"{sc['univ']}대는 개설 과목 안내를 아직 지원하지 않아요. 배재대부터 준비하고 있어요.")


def page_courses(sc):
    page_title("이번 학기 개설 과목", "남은 영역에 맞는 개설 과목을 알려 주는 기능이에요.")
    card_courses(sc)


# ---------- 홈·규정 안내 ----------

def page_home(sc):
    c1, c2, c3 = st.columns(3, gap="medium")
    with c1:
        card_remaining_home(sc)
    with c2:
        with st.container(key="card_home_ask"):
            md('<div class="card-h">학사 규정 질문</div>')
            hist = qa_block(sc, "home", compact=True)
            if hist:
                show_history(hist, "h", compact=True)
                st.button("규정 안내에서 이어서 보기", key="home_to_ask", on_click=goto, args=("ask",), width="stretch")
    with c3:
        card_compare_home(sc)
    card_courses(sc)


def page_ask(sc):
    page_title("학사 규정 안내", "학칙·세칙·편람을 근거로 답하고, 근거를 함께 보여 줘요. 확인되지 않은 내용은 '확인 불가'로 알려 드려요.")
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
    header(sc)
    page = st.session_state.get("page", "home")
    if page == "dev" and not is_dev():
        page = "home"
    {"home": lambda: page_home(sc), "ask": lambda: page_ask(sc), "remaining": lambda: page_remaining(sc), "compare": lambda: page_compare(sc),
     "courses": lambda: page_courses(sc), "dev": page_dev}.get(page, lambda: page_home(sc))()
