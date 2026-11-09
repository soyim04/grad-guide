"""졸업나침반 — 대전 지역 대학 졸업요건 안내 화면 (7단계, Streamlit).

사이드바에서 메뉴와 내 정보(대학·학번·학과·입학 구분·교직 여부)를 고르면 모든 페이지가 그 값을 쓴다.
  홈             남은 학점·규정 질문·학사 선택 비교 요약 카드 + 개설 과목 자리
  학사 규정 안내   질문 → 6단계 채택 파이프라인(계산 → 조회 → 규정 검색 RAG) → 답변·근거 카드·배지
  내 졸업요건      입력 없이 졸업학점·영역 기준·학점 외 체크리스트, 이수 학점을 알면(선택) 남은 학점 계산(순수 Python, API 비용 0)·개설 과목 연결
  학사 선택 비교   부전공 ↔ 복수·다전공 전공학점 비교(순수 Python, 설명 버튼만 LLM)
  개설 과목       자리만(준비 중)
  개발자 · 로그    주소에 ?dev=1 이 있을 때만 보임(질문 수·비용·응답 시간·피드백). 학생 화면에는 비용·응답 시간을 보이지 않는다.
성적(이수 학점·평점·입학 구분)은 어디에도 저장하지 않는다. 질문 문장·답변·출처 ID·비용만 로그(SQLite)에 남는다.

화면 구성은 ui_pages.py(페이지), ui_style.py(CSS·HTML 부품). 계산·엔진은 service_calc.py·engine.py·pipeline.py를 그대로 쓴다.

실행
    .venv\\Scripts\\python.exe -m streamlit run src\\app.py
    개발자 모드: http://localhost:8501/?dev=1
환경 변수
    SERVICE_LOG_DB  로그 DB 경로 (기본 data/service_log.db)
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ui_pages as P  # noqa: E402
import ui_style as U  # noqa: E402

st.set_page_config(page_title="졸업나침반", page_icon="🧭", layout="wide", initial_sidebar_state="expanded")


def main():
    U.inject()
    sc = P.sidebar()
    P.route(sc)


main()
