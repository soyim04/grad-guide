"""6단계 실험용 청크 파일 만들기: 기준선 data/chunks.jsonl에 규칙 하나를 전체 청크에 같은 방식으로 적용한다.

  exp1a  PUA(사용자 지정 영역) 글머리·기호 문자를 모든 청크의 text·embed_text에서 제거
         - 대상: U+E000~F8FF, U+F0000~FFFFD, U+100000~10FFFD (PDF 글꼴 기호가 글자로 빠져나온 것)
         - 줄이 PUA 기호로 시작하면 그 뒤 공백 하나도 함께 지운다 ("\uf000 이수유형1" → "이수유형1").
           그 밖의 공백·줄바꿈은 건드리지 않는다
         - 청크 경계·ID·메타데이터는 그대로 (기준선과 1:1 대응)

사용법
    .venv\\Scripts\\python.exe src\\exp_variants.py exp1a
출력: data/chunks_exp1a.jsonl (원문 텍스트가 있어 .gitignore). 바뀐 청크 수와 sha256을 출력한다.
"""

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "data" / "chunks.jsonl"
BASE_SHA256 = "35c2070b351069414a5d3489e7615f18a86e17938a610c556d4832ccff054ab8"

PUA = "[-\U000f0000-\U000ffffd\U00100000-\U0010fffd]"
PUA_RE = re.compile(PUA)
PUA_LEAD_RE = re.compile(rf"^([ \t]*){PUA}+[ \t]?", re.MULTILINE)


def strip_pua(text):
    text = PUA_LEAD_RE.sub(r"\1", text)
    return PUA_RE.sub("", text)


VARIANTS = {"exp1a": strip_pua}


def sha256(path):
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name not in VARIANTS:
        sys.exit(f"사용법: exp_variants.py {{{'|'.join(VARIANTS)}}}")
    if sha256(BASE) != BASE_SHA256:
        sys.exit("기준선 chunks.jsonl sha256이 기록과 다릅니다.")
    fn = VARIANTS[name]
    out_path = ROOT / "data" / f"chunks_{name}.jsonl"
    changed, per_univ, removed, base_changed = [], Counter(), Counter(), 0
    with BASE.open(encoding="utf-8") as f, out_path.open("w", encoding="utf-8", newline="\n") as o:
        for line in f:
            c = json.loads(line)
            new_text, new_embed = fn(c["text"]), fn(c["embed_text"])
            if new_text != c["text"] or new_embed != c["embed_text"]:
                changed.append(c["id"])
                per_univ[c["대학"]] += 1
                removed[c["대학"]] += len(c["text"]) - len(new_text)
                base_changed += c["기본색인"]
                c["text"], c["embed_text"], c["글자수"] = new_text, new_embed, len(new_text)
            o.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"변형 {name}: 바뀐 청크 {len(changed)}개 (기본 색인 {base_changed}개), 대학별 {dict(per_univ)}, 지운 글자 {dict(removed)}")
    print(f"출력: {out_path.relative_to(ROOT)}  sha256 {sha256(out_path)}")
    (ROOT / "data" / f"chunks_{name}.changed.txt").write_text("\n".join(changed), encoding="utf-8")


if __name__ == "__main__":
    main()
