"""졸업나침반 화면 스타일(7단계 새 디자인). CSS와 작은 HTML 부품만 둔다. 계산·엔진 로직은 없다.

외부 폰트·이미지는 불러오지 않는다(시스템 한글 글꼴만 사용). 스타일은 st.markdown CSS로만 넣는다.
`st.container(key=...)`가 만드는 `.st-key-<key>` 클래스를 선택자로 쓴다(Streamlit 1.66 기준).
HTML 문자열에는 빈 줄·4칸 이상 들여쓰기를 넣지 않는다(마크다운이 코드 블록으로 읽는다).
"""

import html

import streamlit as st

CSS = """
<style>
:root{--pt:#5B47C7;--pt-d:#4A38AD;--soft:#F1EEFB;--soft2:#F7F5FD;--line:#E6E2F5;--ink:#1F2340;--mute:#6B7089;
--blue:#2F6FED;--blue-bg:#EAF1FF;--warn-bg:#FFF4D6;--warn-ink:#8A5A00;--warn-line:#F2DFA0;}
html,body,.stApp,button,input,textarea,select{font-family:"Pretendard","Noto Sans KR","Malgun Gothic","Apple SD Gothic Neo",sans-serif;}
.stApp{background:#FAFAFE;color:var(--ink);}
/* 도구 막대(stToolbar) 전체는 숨기지 않는다: 사이드바 펼치기 버튼(stExpandSidebarButton)이 그 안에 있다. 필요 없는 것만 개별로 숨긴다. */
[data-testid="stMainMenu"],[data-testid="stAppDeployButton"],[data-testid="stDecoration"],[data-testid="stStatusWidget"],footer,#MainMenu{display:none!important;}
[data-testid="stExpandSidebarButton"],[data-testid="stSidebarCollapseButton"]{display:flex!important;visibility:visible!important;opacity:1!important;}
[data-testid="stHeader"]{background:transparent;}
[data-testid="stMainBlockContainer"]{max-width:1280px;padding-top:1.6rem;padding-bottom:3rem;}
p,li,label,[data-testid="stMarkdownContainer"]{font-size:1rem;line-height:1.65;}
h1,h2,h3,h4{letter-spacing:-0.01em;color:var(--ink);}

/* 사이드바 */
section[data-testid="stSidebar"]{background:#fff;border-right:1px solid var(--line);}
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"]{padding-top:1.2rem;}
.brand{display:flex;gap:12px;align-items:center;margin-bottom:.2rem;}
.brand-ico{width:42px;height:42px;border-radius:12px;background:var(--pt);color:#fff;display:flex;align-items:center;justify-content:center;font-size:1.4rem;}
.brand-name{font-size:1.3rem;font-weight:800;color:var(--ink);line-height:1.2;}
.brand-sub{font-size:.88rem;color:var(--mute);line-height:1.4;margin:.4rem 0 1rem;}
.side-h{font-size:.8rem;font-weight:700;color:var(--mute);letter-spacing:.04em;margin:1.1rem 0 .3rem;}
.side-note{font-size:.85rem;color:var(--mute);line-height:1.5;}
[class*="st-key-navitem_"] button{justify-content:flex-start;border:none;background:transparent;color:var(--ink);font-size:1rem;padding:.55rem .8rem;border-radius:10px;box-shadow:none;}
[class*="st-key-navitem_"] button:hover{background:var(--soft2);color:var(--pt);}
[class*="navitem_"][class*="__on"] button{background:var(--soft);color:var(--pt);font-weight:700;}
section[data-testid="stSidebar"] [data-testid="stAlert"]{font-size:.9rem;}

/* 상단 */
.topbar{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:1.1rem;flex-wrap:wrap;}
.topbar-title{font-size:1.55rem;font-weight:800;line-height:1.3;}
.topbar-sub{font-size:.95rem;color:var(--mute);margin-top:.2rem;}
.pill{background:var(--soft);color:var(--pt);border-radius:999px;padding:.4rem .9rem;font-size:.88rem;font-weight:600;white-space:nowrap;}
.page-title{font-size:1.25rem;font-weight:800;margin:.4rem 0 .2rem;}
.page-sub{font-size:.95rem;color:var(--mute);margin-bottom:1rem;}

/* 카드 */
[class*="st-key-card_"]{background:#fff;border:1px solid var(--line);border-radius:16px;padding:1.3rem 1.3rem 1.1rem;box-shadow:0 2px 12px rgba(91,71,199,.06);}
[class*="st-key-card_courses"]{background:transparent;border:1.5px dashed #CFC8EC;box-shadow:none;}
.card-h{display:flex;justify-content:space-between;align-items:center;font-size:1.1rem;font-weight:800;margin-bottom:.5rem;}
.card-sub{font-size:.95rem;color:var(--mute);margin-bottom:.4rem;}
.bignum{font-size:3rem;font-weight:800;color:var(--pt);line-height:1.1;margin:.2rem 0 .1rem;}
.bignum small{font-size:1.2rem;font-weight:700;margin-left:.25rem;}
.bignum-label{font-size:.95rem;color:var(--mute);font-weight:600;}
.statline{display:flex;gap:1.4rem;font-size:.95rem;color:var(--mute);margin:.3rem 0 .6rem;}
.statline b{color:var(--ink);}

/* 배지·박스 */
.badge{display:inline-block;border-radius:999px;padding:.12rem .6rem;font-size:.8rem;font-weight:700;white-space:nowrap;}
.b-req{border:1px solid var(--pt);color:var(--pt);background:#fff;}
.b-none{background:#EEF0F4;color:#59607A;}
.b-na{background:#F4F5F8;color:#8A90A6;}
.b-warn{background:var(--warn-bg);color:var(--warn-ink);}
.b-grade{background:var(--soft);color:var(--pt);}
.b-cur{background:var(--blue-bg);color:var(--blue);}
.b-old{background:#EEF0F4;color:#59607A;}
.b-soon{background:var(--soft);color:var(--pt);}
.callout{border-radius:12px;padding:.75rem 1rem;margin:.5rem 0;font-size:.97rem;line-height:1.6;}
.callout-warn{background:var(--warn-bg);color:var(--warn-ink);border:1px solid var(--warn-line);}
.callout-info{background:var(--blue-bg);color:#1D4FB8;}
.callout-soft{background:var(--soft);color:var(--ink);}
.callout-concl{background:var(--soft);color:var(--ink);border-left:4px solid var(--pt);}

/* 학점 외 요건 */
.ck{display:flex;gap:.7rem;align-items:flex-start;border-radius:12px;padding:.6rem .8rem;margin:.4rem 0;background:var(--soft2);}
.ck-warn{background:var(--warn-bg);}
.ck-text{font-size:.93rem;color:var(--mute);line-height:1.55;}
.ck-warn .ck-text{color:var(--warn-ink);}
.ck-src{font-size:.8rem;color:var(--mute);margin-top:.15rem;}

/* 근거 카드 */
.src{border:1px solid var(--line);border-radius:12px;padding:.7rem .9rem;margin:.45rem 0;background:#fff;}
.src-top{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;font-weight:700;}
.src .num{color:var(--pt);font-weight:800;}
.src-meta{font-size:.9rem;color:var(--mute);margin-top:.2rem;line-height:1.5;}
.route{font-size:.85rem;color:var(--mute);margin:.4rem 0 .2rem;}

/* 표 */
table.tbl{width:100%;border-collapse:collapse;font-size:.95rem;margin:.4rem 0;}
table.tbl th{background:var(--soft);color:var(--ink);text-align:left;padding:.5rem .6rem;font-weight:700;}
table.tbl td{padding:.5rem .6rem;border-bottom:1px solid var(--line);vertical-align:top;}
table.tbl td.tot{font-weight:800;color:var(--pt);}

/* 질문·답 */
.q-line{font-weight:800;font-size:1.02rem;margin:.6rem 0 .3rem;}
.q-scope{font-weight:500;color:var(--mute);font-size:.85rem;margin-left:.4rem;}
[class*="st-key-ans_"]{background:var(--soft2);border:1px solid var(--line);border-radius:12px;padding:1rem 1.1rem;margin:.3rem 0 .6rem;}
[class*="st-key-chips_"] button{border-radius:999px;border:1px solid var(--line);background:#fff;color:var(--ink);font-size:.9rem;padding:.25rem .8rem;min-height:2rem;}
[class*="st-key-chips_"] button:hover{border-color:var(--pt);color:var(--pt);}
.stButton>button,.stFormSubmitButton>button{border-radius:10px;font-weight:600;}
[data-testid="stExpander"]{border-radius:12px;border:1px solid var(--line);}
[data-testid="stNumberInput"] input,[data-testid="stTextInput"] input{font-size:1rem;}
/* 입학 구분 라디오를 조각 모양으로 */
section[data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"]{gap:.35rem;}
</style>
"""


def inject():
    st.markdown(CSS, unsafe_allow_html=True)


def esc(x):
    return html.escape(str(x), quote=True)


def badge(kind, text):
    return f'<span class="badge b-{kind}">{esc(text)}</span>'


def callout(kind, text_html):
    """text_html은 이미 이스케이프된 HTML이어야 한다"""
    return f'<div class="callout callout-{kind}">{text_html}</div>'


def bignum(label, value, unit="학점"):
    return f'<div class="bignum-label">{esc(label)}</div><div class="bignum">{esc(value)}<small>{esc(unit)}</small></div>'


def table(headers, rows, total_col=None):
    """rows: 문자열 리스트의 리스트. total_col: 강조할 열 번호"""
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = ""
    for r in rows:
        tds = "".join(f'<td class="tot">{esc(c)}</td>' if i == total_col else f"<td>{esc(c)}</td>" for i, c in enumerate(r))
        body += f"<tr>{tds}</tr>"
    return f'<table class="tbl"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>'
