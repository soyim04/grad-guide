# 대전 지역 대학 졸업요건 안내 서비스

배재대·충남대·한남대·한밭대·목원대 학사 규정을 근거로 졸업요건을 안내하는 서비스입니다. 학교·학번·학과만 고르면 졸업학점과 교양·전공 기준을 보여 주고, 부전공·복수전공을 비교하며, 화면에 없는 규칙은 학칙 조항을 근거로 답합니다. 근거가 없으면 지어내지 않고 "확인 불가"로 답합니다.

화면 메뉴 (Streamlit):

- **시작하기**: 사용 순서와 상황별 이동 버튼
- **규정 질문**: "목원대 복수전공 몇 학점?" → 현행 규정 조항과 함께 답변
- **내 졸업요건**: 학교·학번·학과만 고르면 졸업학점, 영역별 기준, 필수 요건 체크리스트. 이수 학점을 넣으면 남은 학점도 계산(선택)
- **학사 선택 비교**: 부전공 / 복수전공을 하면 전공 학점이 어떻게 달라지는지 비교
- **이번 학기 개설 과목**: 배재대 2026-2학기 개설 과목 (시범)

## 진행 현황

| 단계 | 상태 | 문서 |
|---|---|---|
| 1. 주제 확정 | ✅ 완료 | [제안서](docs/proposal.pdf) |
| 2. 데이터 구축 | ✅ 완료 | [데이터 카드](data/README.md) |
| 3. 기준표·정답 대조 | ✅ 완료 | [기준표 스키마](data/criteria_schema.md) |
| 4. 평가셋 동결 | ✅ 완료 | [평가셋 설명](eval/README.md) · [채점 기준](eval/grading_rubric.md) |
| 5. 청킹·기본 RAG·오답노트 | ✅ 완료 | [정제·청킹](docs/step5_chunking.md) · [오답노트](eval/error_notes.md) |
| 6. 개선 | ✅ 완료 | [실험 로그](eval/experiments.md) |
| 7. 서비스화 | ✅ 완료 | [최종 리포트 8절](docs/step8_final_report.md#8-서비스화) |
| 8. 최종 측정·리포트 | ✅ 완료 | [최종 리포트](docs/step8_final_report.md) |

## 최종 결과

같은 15문항으로 비교했습니다 (GPT 빈손 = gpt-6-luna, 자료 없이).

| | GPT 빈손 | 고치기 전 RAG | 고친 후 RAG |
|---|---|---|---|
| 정답 / 15 | 3 (20%) | 6 (40%) | 11 (73%) |

동결 후 처음 보는 문항으로 한 번만 쟀습니다 (정답 1·부분 0.5).

| | 정답·부분·확인 불가·틀린 단정 | 점수 |
|---|---|---|
| 홀드아웃 A (13문항) | 5·6·2·0 | 62% |
| 홀드아웃 B (12문항) | 9·0·3·0 | 75% |

A·B 모두 틀린 내용을 단정한 답은 0건입니다. 개발 문항(51)은 45% → 86%이지만 낙관 편향이 있습니다. 자세한 내용은 [최종 리포트](docs/step8_final_report.md)를 보세요.

## 문제 정의

- 졸업요건은 학교·학번·학과마다 다르고, 정보가 학교 포털과 규정집 여러 곳에 흩어져 있습니다. 졸업 필수 과목 하나를 놓쳐 한 학기를 더 다니는 경우도 있습니다.
- 일반 AI는 다른 학교의 숫자를 섞거나, 규정집 표 속 학번·학과별 숫자를 찾지 못하거나, 있는 규정을 없다고 단정합니다. 로그인 없는 무료 ChatGPT(웹 검색 사용)에 10문항을 물어 원문과 대조했더니 6문항에서 문제가 확인됐습니다(최종 리포트 1절).

## 타겟

졸업요건을 아직 아무것도 모르는 학생. 이수 학점을 넣지 않아도 학번과 학과만으로 졸업요건을 먼저 보여 주고, 학점 계산과 개설 과목 조회는 필요한 사람만 쓰도록 했습니다.

## 처리 흐름

질문 하나는 아래 순서로 처리합니다(계산 → 기준표 조회 → RAG). 사이드바에서 고른 학교·학번·학과는 질문에 없을 때만 붙입니다.

1. **계산**: 부전공·복수전공 전공학점 비교 같은 질문은 Python(`criteria_calc.py`)이 계산하고, LLM은 설명만 합니다.
2. **기준표 조회**: 졸업학점·전공 학점 같은 숫자 질문은 `data/criteria.csv`에서 학교·학번·학과에 맞는 행을 찾아 근거(규정명·조항·쪽)와 함께 답합니다.
3. **RAG**: 그 밖의 규칙(휴학, 재수강, 전과 등)은 규정 검색으로 답합니다.
   - 질문에서 학교·학번을 뽑아 메타데이터 필터로 검색 범위 제한
   - 동의어표(`data/synonyms.json`)로 학교별 용어를 정규화해 질문 확장
   - 벡터 검색 상위 5 + BM25(단어 검색) 상위 4 중 새 조항 덧붙임
   - 검색된 조항만 근거로 LLM 답변 생성
4. 근거가 없으면 "확인 불가", 일부만 있으면 "일부 확인 불가"로 표시하고, 서비스 범위 밖 학번(2022~2026학번 밖)은 LLM 없이 확인 불가로 답합니다.

규정 원문은 조항 단위로 잘라(`src/build_chunks.py`, [정제·청킹](docs/step5_chunking.md)) `text-embedding-3-small`로 임베딩해 ChromaDB에 저장합니다.

## 기술 스택

- Language: Python 3.13
- Vector DB: ChromaDB
- Embedding: OpenAI `text-embedding-3-small`
- LLM(답변·채점): OpenAI `gpt-6-luna`
- PDF 글자 추출: pdfplumber
- 화면: Streamlit · 질문 로그: SQLite

## 폴더 구조

```
├── docs/
│   ├── proposal.pdf             # 제안서
│   ├── step5_chunking.md        # 정제·청킹 기록
│   ├── step8_final_report.md    # 최종 리포트 (전체 과정 정리)
│   └── figures/                 # 그래프
├── eval/
│   ├── README.md                # 평가셋 설명
│   ├── grading_rubric.md        # 답변 프롬프트·판정·지표 정의
│   ├── blank_test.csv           # 빈손 테스트 15문항
│   ├── questions_dev.csv        # 개발 51문항
│   ├── questions_holdout.csv    # 홀드아웃 A 13문항 (동결)
│   ├── holdout_b.csv            # 홀드아웃 B 12문항 (잠금)
│   ├── error_notes.md           # 오답노트
│   ├── experiments.md / .csv    # 실험 로그
│   ├── results/                 # 답변·판정 결과
│   └── usage_log.csv            # API 사용량과 비용 기록
├── data/
│   ├── README.md                # 데이터 카드 (자료 목록, 출처 등급)
│   ├── criteria.csv             # 숫자 기준표
│   ├── criteria_schema.md       # 기준표 스키마와 작성 규칙
│   ├── synonyms.json            # 동의어표
│   ├── raw/                     # 규정·편람 원본 (비공개)
│   └── chunks.jsonl             # 청크 (비공개)
├── src/
│   ├── build_chunks.py          # 규정 원문 → 조항 단위 청크
│   ├── build_index.py           # 임베딩과 ChromaDB 색인
│   ├── pipeline.py              # 질문 하나 처리 (계산 → 조회 → RAG)
│   ├── criteria_calc.py         # 계산·비교 (Python)
│   ├── criteria_lookup.py       # 기준표 조회
│   ├── query_filter.py          # 질문에서 학교·학번 추출, 검색 필터
│   ├── query_expand.py          # 동의어 질문 확장
│   ├── lexical.py               # BM25 어휘 검색
│   ├── engine.py                # 서비스 엔진 (출처 카드·배지)
│   ├── service_calc.py          # 남은 학점·체크리스트·학사 비교
│   ├── build_courses.py, courses.py  # 배재 개설 과목
│   ├── app.py, ui_pages.py, ui_style.py  # Streamlit 화면
│   ├── run_rag.py               # 개발 문항 답변·판정 (평가용)
│   ├── eval_holdout.py          # 홀드아웃 측정
│   └── check_service.py         # 서비스 점검
├── scripts/                     # 기준표 행 생성 스크립트
├── .streamlit/config.toml       # 화면 테마
└── requirements.txt, requirements-lock.txt
```

## 데이터 출처 및 이용

- 출처: 배재대·충남대·한남대·한밭대·목원대가 공개한 학칙, 학칙 시행세칙, 학사운영규정, 복수·부전공 규정, 교육과정 편람·책자 등 자료를 국비교육 과정의 비상업 학습 목적으로 사용했습니다. 학번 범위는 2022~2026학번입니다.
- 출처 등급: A 현행 규정 원문 > B 교육과정 편람 > C 학사안내 페이지 > D 입학·공지.
- 원문 PDF와 원문이 들어 있는 청크·색인(`data/raw/`, `data/chunks*.jsonl`, `chroma_db/`)은 저장소에 올리지 않았습니다.
- 배재대 개설 과목 엑셀은 학생 포털에서 내려받은 자료라 원본·가공본(`data/courses_baejae_2026-2.json`) 모두 올리지 않았습니다.
- 대전대는 사이트가 자동 접근을 막아 제외했습니다.
- 자세한 자료 목록은 [데이터 카드](data/README.md)를 참고하세요.

## 실행 준비

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt   # 정확히 같은 버전은 requirements-lock.txt
copy .env.example .env   # 키 입력
```

## 다른 컴퓨터에서 설치

Python 3.13(개발 환경은 3.13.15, Windows)이 설치돼 있어야 해요. 패키지 버전은 `requirements-lock.txt`에 정확히 고정돼 있어요(`requirements.txt`는 직접 쓰는 패키지만 적은 목록).

**1. 프로젝트 폴더 가져오기** (둘 중 하나)

- 폴더 복사: 프로젝트 폴더를 통째로 복사하되 `.venv`는 빼요(컴퓨터마다 새로 만들어요).
- git clone: `git clone <저장소 주소>` 후 2번의 파일을 복사해요.

**2. git에 없는 파일 복사** (폴더 복사로 가져왔다면 이미 들어 있어요)

| 파일·폴더 | 내용 |
|---|---|
| `.env` | API 키 (원본 PC에서 복사. 키가 들어 있으니 공개 저장소·메신저에 올리지 마세요) |
| `chroma_db/` | 규정 검색 색인 |
| `data/raw/` | 규정·편람 원본, 개설 과목 엑셀(`data/raw/baejae/개설과목_2026-2_*.xlsx` 10개 포함) |
| `data/chunks*.jsonl` | 조항 단위로 자른 규정 원문 |

`data/chunks.jsonl`은 `src\build_chunks.py`로, `chroma_db/`는 `src\build_index.py`로 다시 만들 수 있지만 색인은 API 비용(약 $0.02)이 들고 검색 결과의 마지막 순위가 조금 달라질 수 있어서, 원본 PC의 폴더를 복사하는 걸 권해요.

**3. 환경 만들기와 확인** (명령 프롬프트, 프로젝트 폴더에서)

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-lock.txt
.venv\Scripts\python.exe src\build_courses.py
.venv\Scripts\python.exe src\check_service.py
```

- `build_courses.py`: 개설 과목 가공본(`data/courses_baejae_2026-2.json`)을 만들어요(API 비용 0). 엑셀 파일이 빠졌거나 학년별 파일과 과목코드가 다르면 여기서 멈춰요.
- `check_service.py`: 끝 요약에 `N/N 통과 · SKIP 0개`가 나와야 해요. 실패가 없고 SKIP이 0개일 때만 같은 환경이에요. SKIP이 있으면 빠진 자료 파일이 있다는 뜻이에요(가공본이 없으면 개설 과목 점검이 건너뛰어져요).
- 검색이 거리가 거의 같은 마지막 순위에서 가끔 흔들려 점검이 재시도 안내(`시도 N`)를 내는 것은 정상이에요.

**4. 실행**

```
.venv\Scripts\python.exe -m streamlit run src\app.py
```

개발자 모드(비용·응답 시간·로그)는 주소 끝에 `?dev=1`을 붙여요.

## 지원 범위

화면(시작하기)에서 뺀 표를 여기에 둬요. 영역별 계산 지원 대학은 `area_plan` 단계로 확인한 값이에요(배재·충남·목원 T1/T2, 한남·한밭 T3).

| 기능 | 경영 계열 학과 | 그 외 학과 |
| --- | --- | --- |
| 규정 질문 | 지원 | 지원 |
| 졸업요건 확인 (학점 입력 없이) | 지원 | 지원 |
| 남은 학점 계산 (선택) | 지원 | 지원 |
| 학점 외 요건 | 지원 | 지원 |
| 영역별 남은 학점 | 지원 (각주 1) | 지원 안 함 |
| 학사 선택 비교 | 지원 | 일부 (각주 2) |
| 이번 학기 개설 과목 | 배재대만 (각주 3) | 배재대 교양만 (각주 3) |

1. 한남·한밭은 경영 계열도 영역별 계산이 없고 총 학점만 계산해요.
2. 학과마다 주전공 학점이 달라 기준표에 없으면 "학과 확인 필요"로 안내해요.
3. 배재대 IT경영정보학과 전공과 교양을 지원하고, 다른 대학은 준비 중이에요.
