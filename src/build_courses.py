"""배재대 2026-2학기 개설 과목 엑셀 6개 → data/courses_baejae_2026-2.json (분반 단위, 영역·요일·제한 문구 분류까지).

원본(data/raw/baejae/개설과목_2026-2_*.xlsx)과 가공본은 둘 다 커밋하지 않는다(.gitignore). 새 패키지 없이 표준 라이브러리로 xlsx를 읽는다.
실행: .venv\\Scripts\\python.exe src\\build_courses.py        (비용 0, API 안 씀)
분류 규칙은 courses.py에 있다(화면과 점검이 같은 규칙을 쓰도록). 이 파일은 읽기·저장·보고만 한다.
"""

import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

import courses as C  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "baejae"
OUT = ROOT / "data" / C.DATA_FILE
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
FILES = ["IT경영정보", "공유혁신", "공유대학가상", "교필", "교필선", "교선"]
COLS = {"A": "이수구분", "B": "과목코드", "C": "과목명", "D": "분반", "E": "교양이수영역", "F": "담당교수", "G": "학점", "H": "시수_이론", "I": "시수_실습",
        "J": "인원제한", "K": "수강인원", "L": "시간", "M": "비고", "R": "대면"}


def read_rows(path):
    z = zipfile.ZipFile(path)
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            ss.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    sheets = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml", n))
    assert len(sheets) == 1, (path, sheets)
    rows = []
    for row in ET.fromstring(z.read(sheets[0])).iter("{%s}row" % NS["m"]):
        cells = {}
        for c in row.findall("m:c", NS):
            col = re.match(r"[A-Z]+", c.get("r")).group(0)
            v = c.find("m:v", NS)
            if v is None:
                t = c.find("m:is", NS)
                val = "".join(x.text or "" for x in t.iter("{%s}t" % NS["m"])) if t is not None else ""
            else:
                val = ss[int(v.text)] if c.get("t") == "s" else v.text
            cells[col] = (val or "").strip()
        rows.append(cells)
    return rows


def main():
    sections = []
    for name in FILES:
        path = RAW / f"개설과목_2026-2_{name}.xlsx"
        assert path.exists(), path
        rows = read_rows(path)
        assert rows[0].get("C") == "과목명" and rows[0].get("M") == "비고", (name, rows[0])  # 머리글 위치 확인(열이 밀리면 실패)
        for r in rows[2:]:  # 0행 머리글, 1행 이론·실습 소제목
            if not r.get("C"):
                continue
            rec = {v: r.get(k, "") for k, v in COLS.items()}
            rec["파일"] = name
            rec.update(C.classify(rec))
            rec["요일"] = C.parse_days(rec["시간"])
            rec["제한"] = C.is_strong_limit(rec["비고"])
            sections.append(rec)
    assert len(sections) == 659, len(sections)  # 2026-11-09 내려받은 자료의 분반 수
    OUT.write_text(json.dumps({"기준": C.DATA_NOTE, "분반": sections}, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"저장: {OUT} · 분반 {len(sections)}")
    C.report(sections)


if __name__ == "__main__":
    main()
