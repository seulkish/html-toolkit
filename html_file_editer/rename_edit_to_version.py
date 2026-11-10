"""HTML 파일명의 _v2_edit 또는 _edit 를 _v3 로 한 번에 바꿉니다.

예) 011_20261101_sklee_edit.html     -> 011_20261101_sklee_v3.html
    011_20261101_sklee_v2_edit.html  -> 011_20261101_sklee_v3.html

확인 질문 없이 바로 변경하며, tqdm 진행 막대로 진행 상황을 표시합니다.
"""
import argparse
import re
import sys
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:
    print("[오류] tqdm이 설치되어 있지 않습니다.")
    print("  설치: .venv\\Scripts\\python.exe -m pip install tqdm")
    sys.exit(1)

# ▼ 기본 입력 폴더 (여기만 고치면 됩니다)
DEFAULT_DIR = r"C:\Users\DevHjj\Desktop\html-toolkit\html_file_editer\html_input_files"

# ▼ 이 글자까지만 남기고, 뒤는 모두 지운 뒤 _v3 를 붙입니다.
KEYWORD = "sklee"

# KEYWORD 바로 뒤에 영문/숫자가 붙은 경우(skleeA 등)는 다른 이름으로 보고 건드리지 않습니다.
PATTERN = re.compile(rf"^(.*?{re.escape(KEYWORD)})(?![A-Za-z0-9]).*$")


def new_name_for(path: Path) -> str | None:
    m = PATTERN.match(path.stem)
    if m is None:
        return None                      # sklee 가 없는 파일은 건너뜀
    new_stem = m.group(1) + "_v3"
    if new_stem == path.stem:
        return None                      # 이미 ..._sklee_v3.html 이면 그대로
    return new_stem + path.suffix

def main() -> int:
    parser = argparse.ArgumentParser(description="_v2_edit / _edit -> _v3 파일명 일괄 변경")
    parser.add_argument("folder", nargs="?", default=DEFAULT_DIR, help=f"대상 폴더 (기본: {DEFAULT_DIR})")
    parser.add_argument("--recursive", action="store_true", help="하위 폴더까지 포함")
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"[오류] 폴더가 없습니다: {folder}")
        return 1

    files = folder.rglob("*") if args.recursive else folder.glob("*")
    html_files = sorted(p for p in files if p.is_file() and p.suffix.lower() == ".html")

    # 1단계: 바꿀 목록 만들기 (겹치는 이름은 미리 걸러 냄)
    plans, skipped = [], []
    planned_targets = set()
    for src in html_files:
        name = new_name_for(src)
        if name is None:
            continue
        dst = src.with_name(name)
        key = str(dst).lower()  # Windows는 대소문자 구분 없음
        if dst.exists():
            skipped.append((src, dst, "같은 이름의 파일이 이미 있음"))
        elif key in planned_targets:
            skipped.append((src, dst, "다른 파일이 같은 이름으로 바뀔 예정"))
        else:
            planned_targets.add(key)
            plans.append((src, dst))

    if not plans and not skipped:
        print("바꿀 파일이 없습니다.")
        return 0

    # 2단계: 확인 없이 한 번에 변경 + 진행 막대
    done, failed = [], []
    with tqdm(total=len(plans), desc="이름 변경", unit="개", ncols=90) as bar:
        for src, dst in plans:
            bar.set_postfix_str(src.name[:30])
            try:
                src.rename(dst)
                done.append((src, dst))
            except OSError as e:
                failed.append((src, dst, str(e)))
            bar.update(1)

    # 3단계: 결과 요약
    print(f"\n[완료] {len(done)}개")
    for src, dst in done:
        print(f"  {src.relative_to(folder)}  ->  {dst.name}")
    if skipped:
        print(f"\n[건너뜀] {len(skipped)}개")
        for src, dst, why in skipped:
            print(f"  {src.relative_to(folder)}  ->  {dst.name}  ({why})")
    if failed:
        print(f"\n[실패] {len(failed)}개")
        for src, dst, why in failed:
            print(f"  {src.relative_to(folder)}  ->  {dst.name}  ({why})")
    return 0


if __name__ == "__main__":
    sys.exit(main())