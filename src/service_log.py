"""7단계 서비스 질문 로그(SQLite). 1차 프로젝트 log_db.py의 골격을 가져와 이 서비스 열로 바꿨다.

저장하는 것: 질문, 답변 본문, 대학·학번·학과(사이드바 값), 처리 방식, 출처 행·청크 ID, 배지, 토큰·비용·응답 시간, 오류, 👍/👎.
저장하지 않는 것: 사용자가 입력한 이수 학점·평점·입학 구분(성적 저장 제외). 남은 학점·체크리스트 탭은 로그를 남기지 않는다.
DB 경로: data/service_log.db (.gitignore에 있음). 환경 변수 SERVICE_LOG_DB로 바꿀 수 있다.
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("SERVICE_LOG_DB") or ROOT / "data" / "service_log.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS query_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    univ TEXT, year TEXT, dept TEXT,
    question TEXT NOT NULL,
    question_used TEXT,
    route TEXT,
    answer TEXT,
    sources TEXT,
    badges TEXT,
    tokens_in INTEGER, tokens_out INTEGER, embed_tokens INTEGER,
    cost_usd REAL, latency_ms INTEGER,
    error TEXT,
    feedback INTEGER
);
CREATE INDEX IF NOT EXISTS idx_query_log_ts ON query_log(ts);
"""


class LogDB:
    def __init__(self, path=DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def log(self, question, scope, out=None, error=None):
        """scope: {univ, year, dept}. out: Engine.answer 결과 또는 None(오류). 로그 id를 돌려준다."""
        out = out or {}
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO query_log (ts, univ, year, dept, question, question_used, route, answer, sources, badges,"
                " tokens_in, tokens_out, embed_tokens, cost_usd, latency_ms, error) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), scope.get("univ"), str(scope.get("year")), scope.get("dept"), question,
                 out.get("question_used"), out.get("route"), out.get("answer"),
                 json.dumps([s.get("id") for s in out.get("sources", [])], ensure_ascii=False),
                 json.dumps([b.get("kind") for b in out.get("badges", [])], ensure_ascii=False),
                 out.get("tokens_in"), out.get("tokens_out"), out.get("embed_tokens"), out.get("cost_usd"), out.get("latency_ms"), error))
            return cur.lastrowid

    def set_feedback(self, log_id, value):
        """value: 1 좋아요, -1 별로예요, None 취소"""
        with self._conn() as conn:
            conn.execute("UPDATE query_log SET feedback=? WHERE id=?", (value, log_id))

    def summary(self):
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) n, COALESCE(SUM(cost_usd),0) cost, COALESCE(AVG(latency_ms),0) lat,"
                               " SUM(CASE WHEN feedback=1 THEN 1 ELSE 0 END) up, SUM(CASE WHEN feedback=-1 THEN 1 ELSE 0 END) down,"
                               " SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) err FROM query_log").fetchone()
            routes = {r["route"] or "오류": r["n"] for r in conn.execute("SELECT route, COUNT(*) n FROM query_log GROUP BY route")}
        return {"질문 수": row["n"], "총 비용($)": round(row["cost"], 4), "평균 응답(초)": round(row["lat"] / 1000, 1),
                "도움이 됐다": row["up"] or 0, "도움이 안 됐다": row["down"] or 0, "오류 수": row["err"] or 0, "처리 방식별": routes}

    def recent(self, n=100):
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT id, ts, univ, year, dept, question, route, cost_usd, latency_ms, feedback, error FROM query_log ORDER BY id DESC LIMIT ?", (n,))]
