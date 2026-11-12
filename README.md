# 대전 지역 대학 졸업요건 안내 서비스

배재대·충남대·한남대·한밭대·목원대 학사 규정을 근거로 졸업요건을 안내하는 RAG 챗봇.

- 규정 안내: "목원대 복수전공 몇 학점?" → 현행 규정 조항과 함께 답변
- 남은 학점 계산: 영역별 이수 학점을 고르면 남은 학점 표시
- 학사 선택 비교: 부전공 / 복수전공을 하면 졸업까지 무엇이 달라지는지 비교
- (확장) 남은 영역에 맞는 이번 학기 개설 과목 안내

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

## 진행 상황

- [x] 제안서
- [x] 빈손 테스트 (`eval/blank_test.csv`)
- [x] 숫자 기준표 `data/criteria.csv`
- [x] 질문셋 작성, 홀드아웃 20% 동결
- [x] 기본 RAG, 고치기 전 점수
- [x] 개선 실험
- [x] 서비스 화면
- [ ] 홀드아웃 최종 측정
