"""빈손 테스트: blank_test.csv의 질문만 모델에 보내고 답을 저장한다. 기본은 웹검색 끔, --web을 주면 켬.

- 입력  : eval/blank_test.csv (id, 질문 열만 읽는다. 정답·근거는 모델에 보내지 않는다)
- 출력  : eval/results/<날짜>_blank_web-off_<모델>.csv  (id, 질문, 답변, 모델, 실행시각)
          --web이면 <날짜>_blank_web-on_<모델>.csv  (+ 인용URL, 검색호출수)
- 기록  : eval/usage_log.csv 에 토큰과 비용을 한 줄 덧붙인다
- 도구·검색·자료 없이 시스템 프롬프트 한 줄과 질문만 보낸다. (--web일 때만 Responses API의 web_search 도구를 켠다)

실행: .venv\\Scripts\\python.exe src\\blank_test.py          (웹검색 끔)
      .venv\\Scripts\\python.exe src\\blank_test.py --web    (웹검색 켬)
"""
import csv
import sys
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = ROOT / "eval" / "blank_test.csv"
RESULTS_DIR = ROOT / "eval" / "results"
USAGE_LOG = ROOT / "eval" / "usage_log.csv"

MODEL = "gpt-6-luna"  # 1차 프로젝트와 같은 모델
PRICE_IN, PRICE_OUT = 0.10, 0.50  # 달러 / 100만 토큰 (1차 run_eval.py PRICES)
SYSTEM = "한국어로 답하고, 모르면 모른다고 답하세요."
MAX_TOOL_CALLS = 5  # --web: 문항당 검색 호출 상한(도구 호출료 상한용)


def log_usage(row):
    is_new = not USAGE_LOG.exists()
    with USAGE_LOG.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row))
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def ask_web(client, question):
    """웹검색 켬: (답변, 입력토큰, 출력토큰, 인용URL 목록, 검색호출수)"""
    res = client.responses.create(
        model=MODEL,
        instructions=SYSTEM,
        input=question,
        tools=[{"type": "web_search"}],
        max_tool_calls=MAX_TOOL_CALLS,
    )
    urls, n_search = [], 0
    for it in res.output:
        kind = getattr(it, "type", "")
        if kind == "web_search_call":
            n_search += 1
        elif kind == "message":
            for c in it.content:
                for a in getattr(c, "annotations", None) or []:
                    if getattr(a, "type", "") == "url_citation" and a.url not in urls:
                        urls.append(a.url)
    return res.output_text or "", res.usage.input_tokens, res.usage.output_tokens, urls, n_search


def main():
    web = "--web" in sys.argv[1:]
    load_dotenv(ROOT / ".env")
    out = RESULTS_DIR / f"{date.today().isoformat()}_blank_web-{'on' if web else 'off'}_{MODEL}.csv"
    if out.exists():
        sys.exit(f"이미 있는 결과 파일이라 덮어쓰지 않고 멈춥니다: {out.name}")

    with QUESTIONS.open(encoding="utf-8-sig", newline="") as f:
        items = [{"id": r["id"], "질문": r["질문"]} for r in csv.DictReader(f)]

    client = OpenAI()
    rows, t_in, t_out, n_search_total = [], 0, 0, 0
    for item in items:
        answer, urls, n_search = "", [], 0
        try:
            if web:
                answer, a_in, a_out, urls, n_search = ask_web(client, item["질문"])
                t_in += a_in
                t_out += a_out
                n_search_total += n_search
            else:
                res = client.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": item["질문"]}],
                )
                answer = res.choices[0].message.content or ""
                t_in += res.usage.prompt_tokens
                t_out += res.usage.completion_tokens
        except Exception as e:
            print(f"  {item['id']} 실패: {e}")
        row = {"id": item["id"], "질문": item["질문"], "답변": answer, "모델": MODEL,
               "실행시각": datetime.now().isoformat(timespec="seconds")}
        if web:
            row["인용URL"] = "\n".join(urls)
            row["검색호출수"] = n_search
        rows.append(row)
        print(f"  {item['id']} 완료" + (f" (검색 {n_search}회, 인용 {len(urls)}개)" if web else ""))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["id", "질문", "답변", "모델", "실행시각"] + (["인용URL", "검색호출수"] if web else [])
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    cost = t_in / 1e6 * PRICE_IN + t_out / 1e6 * PRICE_OUT
    failed = sum(1 for r in rows if not r["답변"])
    log_usage({
        "시각": datetime.now().isoformat(timespec="seconds"),
        "작업": "blank_test",
        "모델": MODEL,
        "입력 토큰": t_in,
        "출력 토큰": t_out,
        "비용(달러)": f"{cost:.5f}",
        "메모": (f"웹검색 켬(max_tool_calls={MAX_TOOL_CALLS}), {len(items)}문항, 검색 호출 {n_search_total}회, 도구 호출료 별도(비용 열은 토큰 비용만)"
                 if web else f"웹검색 끔, {len(items)}문항") + (f", 실패 {failed}" if failed else ""),
    })
    print(f"저장: {out.relative_to(ROOT).as_posix()}")
    print(f"토큰 입력 {t_in:,} / 출력 {t_out:,}, 비용 약 ${cost:.5f} → {USAGE_LOG.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
