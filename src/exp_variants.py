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


# ---------- exp5a: 긴 청크 분할 ----------
CAP = 600
MIN_PIECE = 80
HEAD_MAX_LINES, HEAD_MAX_CHARS = 6, 200
TABLE_KINDS = ("표", "별표", "별지", "졸업학점표")
BOUNDARY_RE = re.compile(
    r"^[ \t]*(?:\d+[.)]|\(\d+\)|[가-하][.)]|[①-⑳㉑-㉟]|[○●■□◆◇▶▷▪※\-·ㆍ◦]|제\d+조|<|\[)")
NUM_TOKEN_RE = re.compile(r"^\d+(?:\.\d+)?$")


def split_head_lines(text):
    """표 성격 청크의 머리줄: 맨 앞에서 '숫자가 2개 이상 든 줄(데이터 줄)'이 나오기 전까지, 최대 6줄·200자."""
    lines, head, size = text.split("\n"), [], 0
    for ln in lines:
        toks = [t for t in re.split(r"[\s|]+", ln.strip()) if t]
        if sum(bool(NUM_TOKEN_RE.match(t)) for t in toks) >= 2:
            break
        if len(head) >= HEAD_MAX_LINES or size + len(ln) + 1 > HEAD_MAX_CHARS:
            break
        head.append(ln)
        size += len(ln) + 1
    return "\n".join(head)


def candidate_cuts(body):
    """(위치, 등급): 등급 0=번호·기호 줄 앞, 1=아무 줄 앞, 2=문장 끝 뒤, 3=공백 뒤"""
    cuts, pos = [], 0
    for ln in body.split("\n")[:-1]:
        pos += len(ln) + 1
        cuts.append((pos, 0 if BOUNDARY_RE.match(body[pos:body.find("\n", pos) if body.find("\n", pos) >= 0 else len(body)]) else 1))
    for m in re.finditer(r"[.다요음함][ \t]+(?=\S)", body):
        cuts.append((m.end(), 2))
    for m in re.finditer(r"[ \t]+(?=\S)", body):
        cuts.append((m.end(), 3))
    return cuts


def split_body(body):
    n = len(body)
    m = -(-n // CAP)
    while True:
        cuts, prev, ok = [], 0, True
        cand = candidate_cuts(body)
        for j in range(1, m):
            target = j * n / m
            lo, hi = max(prev + MIN_PIECE, n - CAP * (m - j)), prev + CAP
            pick = None
            for tier in range(4):
                opts = [(abs(p - target), p) for p, t in cand if t == tier and lo <= p <= hi]
                if opts:
                    pick = min(opts)[1]
                    break
            if pick is None:
                ok = False
                break
            cuts.append(pick)
            prev = pick
        pieces = [body[a:b] for a, b in zip([0] + cuts, cuts + [n])]
        if ok and all(len(x.strip()) <= CAP for x in pieces):
            return [x.strip("\n") for x in pieces]
        m += 1
        if m > 20:
            return [body[i:i + CAP] for i in range(0, n, CAP)]


def split_chunk(c):
    """기본 색인 청크 하나 → 조각 리스트 (600자 이하면 그대로 1개)"""
    if not c["기본색인"] or len(c["text"]) <= CAP:
        return [c]
    head = split_head_lines(c["text"]) if c["구분"] in TABLE_KINDS else ""
    rest = c["text"][len(head):].lstrip("\n") if head else c["text"]
    if len(rest) <= CAP:  # 머리줄을 빼면 600자 이하: 그래도 나눔 기준은 전체 text이므로 균등 분할
        rest = c["text"]
        head = ""
    parts = split_body(rest)
    m = len(parts)
    first_line, _, embed_body = c["embed_text"].partition("\n")
    out = []
    for k, part in enumerate(parts, 1):
        tag = f"조각 {k}/{m}" if c.get("부분") else f"{k}/{m}"
        header = (first_line[:-1] + f" ({tag})]") if first_line.endswith("]") else first_line + f" ({tag})"
        prefix = head + "\n" if head else ""
        text = prefix + part
        d = dict(c)
        d.update({"id": f"{c['id']}.{k}", "부모id": c["id"], "조각": f"{k}/{m}", "text": text,
                  "embed_text": header + "\n" + text, "글자수": len(text)})
        out.append(d)
    return out


VARIANTS = {"exp1a": strip_pua, "exp5a": None}


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
    out_path = ROOT / "data" / f"chunks_{name}.jsonl"
    if name == "exp5a":
        main_5a(out_path)
        return
    fn = VARIANTS[name]
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


def main_5a(out_path):
    n_split = n_pieces = n_base = 0
    after = []
    with BASE.open(encoding="utf-8") as f, out_path.open("w", encoding="utf-8", newline="\n") as o:
        for line in f:
            c = json.loads(line)
            n_base += c["기본색인"]
            parts = split_chunk(c)
            if len(parts) > 1:
                n_split += 1
                n_pieces += len(parts)
                c["기본색인"], c["제외사유"] = False, "분할됨(조각으로 대체)"
            o.write(json.dumps(c, ensure_ascii=False) + "\n")
            if len(parts) > 1:
                for p in parts:
                    o.write(json.dumps(p, ensure_ascii=False) + "\n")
            after.extend(len(p["text"]) for p in parts if p["기본색인"])
    after.sort()
    print(f"exp5a: 나뉜 청크 {n_split}개 -> 조각 {n_pieces}개, 기본 색인 {n_base}개 -> {len(after)}개")
    print(f"기본 색인 text 글자수: 최대 {after[-1]}, 중앙값 {after[len(after)//2]}, 600자 초과 {sum(x > CAP for x in after)}개 (표 머리줄 반복분 포함)")
    print(f"출력: {out_path.relative_to(ROOT)}  sha256 {sha256(out_path)}")


if __name__ == "__main__":
    main()
