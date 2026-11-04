"""홀드아웃 분리 (4단계). 저장소 루트에서 실행한다.

  미리보기(파일 안 만듦): python split_holdout.py
  동결(파일 생성):        python split_holdout.py --write

규칙 (eval 메모·CLAUDE.md 4단계)
- 개발 고정: 빈손 15문항(B01~B15), 같은 근거 묶음·정답 값 공유 문항
- 묶음은 한쪽으로: {X02,T03,T07}, {H09,H10}
- 시드 고정 층화 무작위, 목표 13문항 (조건을 못 맞추면 12)
- 출력은 ID·대학·유형 분포만. 문항 내용은 출력하지 않는다.
"""
import argparse, collections, csv, hashlib, io, pathlib, random, re, sys

sys.stdout.reconfigure(encoding="utf-8")
SEED = 20261104
TARGET = 13

# 개발 고정 (이유별)
FIXED_BLANK = {f"B{i:02d}" for i in range(1, 16)}                        # 빈손 15문항
FIXED_BUNDLE = {"M05", "M08", "P04"}                                    # M05+M08, P04+B01+B10
FIXED_EVIDENCE = {"M01", "M02", "P02"}                                  # B08, B07과 근거·값 공유
FIXED_VALUE = {"X01", "T01", "T02", "T08", "X03", "M04", "C09", "C10", "C04", "H03"}  # 개발 문항과 정답 값 공유 (2026-11-04 점검 ①②)
FIXED_VIA_BUNDLE = {"C02", "C06", "H04", "H09", "H10"}                  # 위 문항과 묶음·값 공유라 함께 개발 (H10은 H03과 값 공유)
DEV_FIXED = FIXED_BLANK | FIXED_BUNDLE | FIXED_EVIDENCE | FIXED_VALUE | FIXED_VIA_BUNDLE

BUNDLES = [{"X02", "T03", "T07"}, {"H09", "H10"}]

# 학교별 허용 범위, 유형별 허용 범위
SCHOOL_RANGE = {"한남": (2, 3), "한밭": (2, 3), "충남": (2, 3), "목원": (1, 2), "배재": (1, 2), "공통": (1, 1)}
TYPE_RANGE = {"숫자": (4, 5), "서술": (4, 6), "계산·비교": (1, 1), "확인 불가": (1, 2)}


def type_bucket(t):
    if t.startswith("숫자"):
        return "숫자"
    if t.startswith("서술"):
        return "서술"
    if t.startswith("계산"):
        return "계산·비교"
    if t.startswith("확인"):
        return "확인 불가"
    return "기타"


def load(path):
    raw = path.read_bytes()
    bom = raw[:3] == b"\xef\xbb\xbf"
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline="")))
    return bom, rows[0], rows[1:]


def dump(bom, header, body):
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(header)
    w.writerows(body)
    return (("﻿" if bom else "") + buf.getvalue()).encode("utf-8")


def valid(chosen, info):
    sch = collections.Counter(info[i][0] for i in chosen)
    typ = collections.Counter(type_bucket(info[i][1]) for i in chosen)
    for s, (lo, hi) in SCHOOL_RANGE.items():
        if not lo <= sch.get(s, 0) <= hi:
            return False
    for t, (lo, hi) in TYPE_RANGE.items():
        if not lo <= typ.get(t, 0) <= hi:
            return False
    return typ.get("기타", 0) == 0


def draw(info, pool, target, rng):
    in_bundle = set().union(*BUNDLES)
    units = [sorted(b) for b in BUNDLES if b <= pool] + [[i] for i in sorted(pool) if i not in in_bundle]
    for attempt in range(1, 500001):
        order = units[:]
        rng.shuffle(order)
        pick, n = [], 0
        for u in order:
            if n + len(u) <= target:
                pick.append(u)
                n += len(u)
            if n == target:
                break
        if n != target:
            continue
        chosen = sorted(i for u in pick for i in u)
        if valid(chosen, info):
            return chosen, attempt
    return None, 500000


def numbers(s):
    toks = re.findall(r"\d+(?:\.\d+)?", s)
    return {t for t in toks if ("." in t or len(t) >= 2) and not re.fullmatch(r"(19|20)\d\d", t)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--root", default=".")
    a = ap.parse_args()
    root = pathlib.Path(a.root).resolve()
    dev_path, hold_path = root / "eval" / "questions_dev.csv", root / "eval" / "questions_holdout.csv"
    if hold_path.exists():
        sys.exit("이미 questions_holdout.csv가 있다. 동결 후에는 다시 만들지 않는다.")
    bom, header, body = load(dev_path)
    assert dump(bom, header, body) == dev_path.read_bytes(), "CSV 형식 보존 불가"
    H = {h: i for i, h in enumerate(header)}
    info = {r[0]: (r[H["대학"]], r[H["유형"]]) for r in body}
    assert len(body) == 64, len(body)
    assert DEV_FIXED <= set(info), DEV_FIXED - set(info)
    pool = set(info) - DEV_FIXED
    print(f"전체 {len(info)} / 개발 고정 {len(DEV_FIXED)} / 후보 {len(pool)}")
    rng = random.Random(SEED)
    for target in (TARGET, TARGET - 1):
        chosen, attempts = draw(info, pool, target, rng)
        if chosen:
            break
    if not chosen:
        sys.exit("조건을 만족하는 조합 없음")
    print(f"시드 {SEED}, 목표 {target}, 시도 {attempts}회, Python {sys.version.split()[0]}")
    print("홀드아웃 ID:", ", ".join(chosen))
    print("대학:", dict(collections.Counter(info[i][0] for i in chosen)))
    print("유형:", dict(collections.Counter(type_bucket(info[i][1]) for i in chosen)))
    print("대학x유형:")
    for k, v in sorted(collections.Counter((info[i][0], info[i][1]) for i in chosen).items()):
        print("  ", k, v)
    # 값 공유 경고: 홀드아웃 정답의 숫자(2자리 이상·소수)가 개발용 정답에 나오는지 (ID와 개수만)
    ans = {r[0]: numbers(r[H["정답"]]) for r in body}
    dev_ids = [i for i in info if i not in chosen]
    print("정답 숫자 겹침(홀드아웃 ID -> 개발 ID, 개수), 값은 출력하지 않음:")
    any_warn = False
    for h in chosen:
        hits = [(d, len(ans[h] & ans[d])) for d in dev_ids if ans[h] & ans[d]]
        if hits:
            any_warn = True
            print("  ", h, "->", ", ".join(f"{d}({n})" for d, n in hits))
    if not any_warn:
        print("   없음")
    if not a.write:
        print("[미리보기] 파일을 만들지 않았다.")
        return
    hold = [r for r in body if r[0] in chosen]
    dev = [r for r in body if r[0] not in chosen]
    assert len(hold) == len(chosen) and len(dev) == 64 - len(chosen)
    hold_path.write_bytes(dump(bom, header, hold))
    dev_path.write_bytes(dump(bom, header, dev))
    print("questions_holdout.csv", len(hold), "행 / questions_dev.csv", len(dev), "행")
    print("sha256(questions_holdout.csv):", hashlib.sha256(hold_path.read_bytes()).hexdigest())


main()
