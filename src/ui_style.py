"""졸업나침반 화면 스타일(7단계 새 디자인). CSS와 작은 HTML 부품만 둔다. 계산·엔진 로직은 없다.

외부 폰트·이미지는 불러오지 않는다(시스템 한글 글꼴만 사용). 스타일은 st.markdown CSS로만 넣는다.
`st.container(key=...)`가 만드는 `.st-key-<key>` 클래스를 선택자로 쓴다(Streamlit 1.66 기준).
HTML 문자열에는 빈 줄·4칸 이상 들여쓰기를 넣지 않는다(마크다운이 코드 블록으로 읽는다).
"""

import base64
import html
import re
from pathlib import Path

import streamlit as st

CSS = """
<style>
:root{--pt:#1E3A8A;--tint:#EEF1FA;--soft:#F7F7F5;--soft2:#F7F7F5;--line:#E9E9E7;--ink:#2F3437;--mute:#6B6F76;
--warn-bg:#FFF4D6;--warn-ink:#8A5A00;--warn-line:#F2DFA0;}
html,body,.stApp,button,input,textarea,select{font-family:"Pretendard","Noto Sans KR","Malgun Gothic","Apple SD Gothic Neo",sans-serif;}
.stApp{background:#fff;color:var(--ink);}
/* 도구 막대(stToolbar) 전체는 숨기지 않는다: 사이드바 펼치기 버튼(stExpandSidebarButton)이 그 안에 있다. 필요 없는 것만 개별로 숨긴다. */
[data-testid="stMainMenu"],[data-testid="stAppDeployButton"],[data-testid="stDecoration"],[data-testid="stStatusWidget"],footer,#MainMenu{display:none!important;}
[data-testid="stExpandSidebarButton"],[data-testid="stSidebarCollapseButton"]{display:flex!important;visibility:visible!important;opacity:1!important;}
[data-testid="stHeader"]{background:transparent;}
[data-testid="stMainBlockContainer"]{max-width:1100px;padding-top:1.6rem;padding-bottom:3rem;}
p,li,label,[data-testid="stMarkdownContainer"]{font-size:1rem;line-height:1.65;}
h1,h2,h3,h4{letter-spacing:-0.01em;color:var(--ink);}

/* 사이드바(너비 240px 고정) */
section[data-testid="stSidebar"]{background:#fff;border-right:1px solid var(--line);}
section[data-testid="stSidebar"][aria-expanded="true"]{width:240px!important;min-width:240px!important;}
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"]{padding-top:1.2rem;}
.brand{display:flex;gap:10px;align-items:center;margin-bottom:1rem;}
.brand-ico{flex:none;width:28px;height:28px;background:url("__LOGO__") center/contain no-repeat;}
.brand-name{font-size:19px;font-weight:800;color:var(--ink);line-height:1.2;}
.side-h{font-size:14px;font-weight:700;color:var(--ink);margin:1.1rem 0 .3rem;}
.side-note{font-size:.82rem;color:var(--mute);line-height:1.5;}
/* 사이드바 입력: 라벨 14px, 선택 상자 글씨 15px·높이 40px (실제 data-testid: stWidgetLabel·stSelectbox·stRadio·stCheckbox) */
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"],section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] label{font-size:14px!important;}
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"]>div{min-height:40px!important;}
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] *{font-size:15px!important;}
section[data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] label p,section[data-testid="stSidebar"] [data-testid="stCheckbox"] label p{font-size:15px!important;}
[class*="st-key-navitem_"] button{justify-content:flex-start;border:none;background:transparent;color:var(--ink);font-size:16px;min-height:44px;padding:.4rem .8rem;border-radius:8px;box-shadow:none;}
[class*="st-key-navitem_"] button p{font-size:16px;}
[class*="st-key-navitem_"] button:hover{background:var(--soft);color:var(--pt);}
[class*="navitem_"][class*="__on"] button{background:var(--tint);color:var(--pt);font-weight:700;}
section[data-testid="stSidebar"] [data-testid="stAlert"]{font-size:.9rem;}

/* 상단 */
.topbar{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:1.1rem;flex-wrap:wrap;}
.topbar-title{font-size:1.55rem;font-weight:800;line-height:1.3;}
.topbar-sub{font-size:.95rem;color:var(--mute);margin-top:.2rem;}
.pill{background:var(--soft);color:var(--ink);border-radius:999px;padding:.4rem .9rem;font-size:.88rem;font-weight:600;white-space:nowrap;}
.page-title{font-size:1.25rem;font-weight:800;margin:.4rem 0 .2rem;}
.page-sub{font-size:.95rem;color:var(--mute);margin-bottom:1rem;}

/* 카드(선과 8px 모서리만, 그림자 없음) */
[class*="st-key-card_"]{background:#fff;border:1px solid var(--line);border-radius:8px;padding:1.3rem 1.3rem 1.1rem;box-shadow:none;}
.st-key-card_courses_soon{background:transparent;border:1px dashed #D3D3CF;box-shadow:none;}
.card-h{display:flex;justify-content:space-between;align-items:center;font-size:1.1rem;font-weight:800;margin-bottom:.5rem;}
.card-sub{font-size:.95rem;color:var(--mute);margin-bottom:.4rem;}
.bignum{font-size:3rem;font-weight:800;color:var(--pt);line-height:1.1;margin:.2rem 0 .1rem;}
.bignum small{font-size:1.2rem;font-weight:700;margin-left:.25rem;}
.bignum-label{font-size:.95rem;color:var(--mute);font-weight:600;}
.statline{display:flex;gap:1.4rem;font-size:.95rem;color:var(--mute);margin:.3rem 0 .6rem;}
.statline b{color:var(--ink);}

/* 배지·박스(노랑은 확인 불가 성격에만) */
.badge{display:inline-block;border-radius:999px;padding:.12rem .6rem;font-size:.8rem;font-weight:700;white-space:nowrap;}
.b-req{border:1px solid var(--pt);color:var(--pt);background:#fff;}
.b-none{background:#EEEEEC;color:#5A5F66;}
.b-na{background:#F4F4F2;color:#8A8E94;}
.b-warn{background:var(--warn-bg);color:var(--warn-ink);}
.b-grade{background:var(--soft);color:var(--pt);}
.b-cur{background:var(--soft);color:var(--pt);}
.b-old{background:#EEEEEC;color:#5A5F66;}
.b-info{background:var(--soft);color:var(--pt);}
.b-soon{background:var(--soft);color:var(--pt);}
.callout{border-radius:8px;padding:.75rem 1rem;margin:.5rem 0;font-size:.97rem;line-height:1.6;}
.callout-warn{background:var(--warn-bg);color:var(--warn-ink);border:1px solid var(--warn-line);}
.callout-info{background:var(--soft);color:var(--pt);}
.callout-soft{background:var(--soft);color:var(--ink);}
.callout-concl{background:var(--soft);color:var(--ink);border-left:4px solid var(--pt);}

/* 학점 외 요건 */
.ck{display:flex;gap:.7rem;align-items:flex-start;border-radius:8px;padding:.6rem .8rem;margin:.4rem 0;background:var(--soft);}
.ck-warn{background:var(--warn-bg);}
.ck-text{font-size:.93rem;color:var(--mute);line-height:1.55;}
.ck-warn .ck-text{color:var(--warn-ink);}
.ck-src{font-size:.8rem;color:var(--mute);margin-top:.15rem;}

/* 근거 카드 */
.src{border:1px solid var(--line);border-radius:8px;padding:.7rem .9rem;margin:.45rem 0;background:#fff;}
.src-top{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;font-weight:700;}
.src .num{color:var(--pt);font-weight:800;}
.src-meta{font-size:.9rem;color:var(--mute);margin-top:.2rem;line-height:1.5;}
.route{font-size:.85rem;color:var(--mute);margin:.4rem 0 .2rem;}

/* 표 */
table.tbl{width:100%;border-collapse:collapse;font-size:.95rem;margin:.4rem 0;}
table.tbl th{background:var(--soft);color:var(--ink);text-align:left;padding:.5rem .6rem;font-weight:700;}
table.tbl td{padding:.5rem .6rem;border-bottom:1px solid var(--line);vertical-align:top;}
table.tbl td.tot{font-weight:800;color:var(--pt);}
table.tbl td.sub{padding-left:1.7rem;}
table.tbl tr.subrow td{font-size:.9rem;}

/* 질문·답 */
.q-line{font-weight:800;font-size:1.02rem;margin:.6rem 0 .3rem;}
.q-scope{font-weight:500;color:var(--mute);font-size:.85rem;margin-left:.4rem;}
[class*="st-key-ans_"]{background:var(--soft);border:1px solid var(--line);border-radius:8px;padding:1rem 1.1rem;margin:.3rem 0 .6rem;}
[class*="st-key-chips_"] button{border-radius:999px;border:1px solid var(--line);background:#fff;color:var(--ink);font-size:.9rem;padding:.25rem .8rem;min-height:2rem;}
[class*="st-key-chips_"] button:hover{border-color:var(--pt);color:var(--pt);}
.stButton>button,.stFormSubmitButton>button{border-radius:8px;font-weight:600;}
[data-testid="stExpander"]{border-radius:8px;border:1px solid var(--line);}
[data-testid="stNumberInput"] input,[data-testid="stTextInput"] input{font-size:1rem;}
/* 질문창의 영어 안내("Press Enter to submit form")는 입력 글자와 겹쳐 숨긴다 */
[data-testid="InputInstructions"]{display:none!important;}
/* 사이드바 메뉴 글자를 왼쪽 정렬(버튼 안쪽 래퍼까지 정렬) */
[class*="st-key-navitem_"] button{text-align:left;}
[class*="st-key-navitem_"] button>div,[class*="st-key-navitem_"] button [data-testid="stMarkdownContainer"]{justify-content:flex-start!important;text-align:left!important;width:100%;}
[class*="st-key-navitem_"] button [data-testid="stMarkdownContainer"] p{text-align:left!important;margin:0;}
/* 근거 보기(HTML details) */
details.det{margin-top:.25rem;font-size:.85rem;color:var(--mute);}
details.det summary{cursor:pointer;color:var(--pt);font-weight:600;}
details.det div{margin:.15rem 0 0 .2rem;line-height:1.5;}
/* 개설 과목 목록 */
details.crs{border:1px solid var(--line);border-radius:8px;background:#fff;margin:.4rem 0;padding:.55rem .85rem;}
details.crs summary{cursor:pointer;line-height:1.7;}
.crs-sec{border-top:1px solid var(--line);margin-top:.5rem;padding-top:.45rem;font-size:.93rem;line-height:1.6;}
.crs-memo{font-size:.8rem;color:var(--mute);line-height:1.5;margin-top:.1rem;word-break:keep-all;}
.crs-group{font-weight:800;color:var(--pt);margin:1rem 0 .2rem;font-size:.98rem;}
/* 약어 툴팁 */
abbr.abbr{text-decoration:underline dotted;text-underline-offset:3px;cursor:help;}
/* 시작하기 */
.hero{display:flex;gap:14px;align-items:center;margin:.2rem 0 1.6rem;}
.hero-ico{flex:none;width:48px;height:48px;border-radius:8px;background:var(--tint) url("__LOGO__") center/30px 30px no-repeat;}
.hero-title{font-size:1.7rem;font-weight:800;line-height:1.25;}
.hero-sub{font-size:1rem;color:var(--mute);margin-top:.15rem;}
.home-h{font-size:1.1rem;font-weight:800;margin:1.6rem 0 .4rem;}
[class*="st-key-hstep_"]{border-bottom:1px solid var(--line);box-sizing:border-box;min-height:76px;padding:.2rem 0 12px;margin-bottom:12px;}
[class*="st-key-hsit_"]{border-bottom:1px solid var(--line);box-sizing:border-box;min-height:52px;padding:0;display:flex;flex-direction:column;justify-content:center;}
[class*="st-key-hsit_"] [data-testid="stHorizontalBlock"]{align-items:center;}
[class*="st-key-hsit_"] [data-testid="stMarkdownContainer"] p,[class*="st-key-hsit_"] [data-testid="stElementContainer"],[class*="st-key-hsit_"] [data-testid="stButton"]{margin:0!important;}
.st-key-hstep_2 [data-testid="stButton"]{margin-left:38px;}
.st-key-hstep_2 button{padding-left:0;}
.stp{display:flex;gap:12px;align-items:flex-start;margin-bottom:.2rem;}
.stp-no{flex:none;width:26px;height:26px;border-radius:50%;border:1.5px solid var(--pt);color:var(--pt);display:flex;align-items:center;justify-content:center;font-size:.85rem;font-weight:700;margin-top:.1rem;}
.stp-no.on{background:var(--pt);color:#fff;}
.stp-t{font-weight:700;line-height:1.5;}
.stp-d{font-size:.9rem;color:var(--mute);line-height:1.55;}
.stp-tag{display:inline-block;font-size:.75rem;font-weight:700;color:var(--mute);background:var(--soft);border-radius:999px;padding:.05rem .5rem;margin-left:.4rem;vertical-align:middle;}
.sit-q{line-height:1.6;padding:0;margin:0;}
.note-box{background:var(--soft);border-radius:8px;padding:.8rem 1.1rem;margin-top:.4rem;}
.note-box ul{margin:0;padding-left:1.1rem;}
.note-box li{font-size:.93rem;color:var(--ink);line-height:1.65;}
.st-key-hstep_2 button,[class*="st-key-hsit_"] [data-testid="stColumn"]:last-child button{color:var(--pt);font-weight:700;white-space:nowrap;}
/* 입학 구분 라디오를 조각 모양으로 */
section[data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"]{gap:.35rem;}
</style>
"""

# 로고(assets/logo.svg)는 파일을 base64로 CSS에 직접 넣는다(정적 파일 서빙 설정 불필요). 사이드바 28px(타일 없음)·홈 hero 박스 안 30px
LOGO_SVG = Path(__file__).resolve().parent.parent / "assets" / "logo.svg"
LOGO_URI = "data:image/svg+xml;base64," + base64.b64encode(LOGO_SVG.read_bytes()).decode("ascii")
CSS = CSS.replace("__LOGO__", LOGO_URI)


ABBR = {"교필선": "교양필수선택(영역을 골라 듣는 교양)", "교필": "교양필수", "교선": "교양선택", "전필": "전공필수", "전선": "전공선택", "일선": "일반선택"}
_ABBR_RE = re.compile(r"(?<![가-힣])(교필선|교필|교선|전필|전선|일선)(?![가-힣])")
ABBR_HELP = " · ".join(f"{k}={v}" for k, v in ABBR.items())


def abbr_html(text):
    """이스케이프한 글 속 이수구분 약어(교필·교필선·교선·전필·전선·일선)에 마우스를 올리면 풀이가 보이게 한다"""
    return _ABBR_RE.sub(lambda m: f'<abbr class="abbr" title="{esc(ABBR[m.group(1)])}">{m.group(1)}</abbr>', esc(text))


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


def table(headers, rows, total_col=None, levels=None):
    """rows: 문자열 리스트의 리스트. total_col: 강조할 열 번호. levels: 행마다 들여쓰기 단계(0=상위, 1=하위. 첫 칸만 들여씀)"""
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = ""
    for k, r in enumerate(rows):
        sub = bool(levels and levels[k])
        tds = "".join(f'<td class="tot">{esc(c)}</td>' if i == total_col else (f'<td class="sub">{esc(c)}</td>' if sub and i == 0 else f"<td>{esc(c)}</td>") for i, c in enumerate(r))
        body += f'<tr class="subrow">{tds}</tr>' if sub else f"<tr>{tds}</tr>"
    return f'<table class="tbl"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>'
