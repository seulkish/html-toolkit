"""
CSV(id, original_filename, new_filename)에 적힌 id만 골라 HTML 파일명을 바꿉니다.
폴더에 파일이 더 있어도 CSV에 없는 id의 파일은 건드리지 않습니다.
파일명을 "_"로 나눈 맨 앞 숫자를 id로 보고 CSV의 id와 맞춥니다.
  예) 1_test_test.html -> id 1 -> CSV의 new_filename(001_20261019_sklee.html)

실행할 때마다 폴더에 결과 CSV를 남깁니다.
  rename_result_날짜_시간.csv : CSV의 모든 id 결과
  rename_failed_날짜_시간.csv : 실패·건너뜀만 (있을 때만 생성)
  status: 성공 / 실패 / 건너뜀 / 유지 / 예정(미리보기)

사용법
  실제 변경:                    python rename_html.py
  미리보기(실제로 바꾸지 않음):  python rename_html.py --dry-run
  다른 폴더/CSV를 쓸 때:         python rename_html.py <폴더> <매핑.csv>
"""
import argparse
import csv
import sys
import uuid
from datetime import datetime
from pathlib import Path

# ===== 기본 폴더 설정 =====================
HTML_FOLDER = "html"
CSV_FILE = "input_html.csv"
# ==========================================

SCRIPT_DIR = Path(__file__).resolve().parent

FIELDS = ["id", "original_filename", "new_filename", "status", "reason"]


def parse_id(text):
    """'1', '001', ' 1 ' -> 1 / 숫자가 아니면 None"""
    text = (text or "").strip()
    return int(text) if text.isdigit() else None


def load_mapping(csv_path):
    """CSV에 적힌 순서대로 (id, new_filename) 목록을 돌려줌"""
    for enc in ("utf-8-sig", "cp949"):  # 엑셀 CSV(BOM) / 한글 엑셀(cp949)
        try:
            with open(csv_path, newline="", encoding=enc) as f:
                rows = list(csv.DictReader(f))
            break
        except UnicodeDecodeError:
            continue
    else:
        sys.exit("CSV 인코딩을 읽을 수 없습니다 (utf-8 / cp949 모두 실패).")

    mapping = {}
    for line_no, row in enumerate(rows, start=2):
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        file_id = parse_id(row.get("id"))
        new_name = row.get("new_filename", "")
        if file_id is None or not new_name:
            print(f"[CSV 건너뜀] {line_no}행: id 또는 new_filename이 비어 있거나 숫자가 아님 -> {row}")
            continue
        if not new_name.lower().endswith(".html"):
            new_name += ".html"
        if file_id in mapping:
            sys.exit(f"CSV에 id {file_id}가 중복됩니다 ({line_no}행). 정리 후 다시 실행하세요.")
        mapping[file_id] = new_name
    return mapping


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", default=HTML_FOLDER)
    ap.add_argument("csv_path", nargs="?", default=CSV_FILE)
    ap.add_argument("--dry-run", action="store_true", help="미리보기만 하고 실제로 바꾸지 않음")
    args = ap.parse_args()
    args.apply = not args.dry_run

    folder = Path(args.folder)
    if not folder.is_absolute():
        folder = SCRIPT_DIR / folder
    csv_path = Path(args.csv_path)
    if not csv_path.is_absolute():
        csv_path = SCRIPT_DIR / csv_path
    if not folder.is_dir():
        sys.exit(f"폴더가 없습니다: {folder}")
    if not csv_path.is_file():
        sys.exit(f"CSV 파일이 없습니다: {csv_path}")
    mapping = load_mapping(csv_path)

    # 폴더의 HTML 파일을 id별로 묶어 둠 (매칭용 색인일 뿐, 여기서 바꾸지 않음)
    files_by_id = {}
    for path in folder.glob("*.html"):
        file_id = parse_id(path.name.split("_")[0])
        if file_id is not None:
            files_by_id.setdefault(file_id, []).append(path)

    results = []  # CSV 순서대로
    plan = {}     # 현재 경로 -> (새 경로, 결과 행)

    for file_id, new_name in mapping.items():
        row = {"id": file_id, "original_filename": "", "new_filename": new_name,
               "status": "", "reason": ""}
        results.append(row)
        matches = files_by_id.get(file_id, [])
        if not matches:
            row.update(status="실패", reason="폴더에 해당 id 파일 없음")
            continue
        if len(matches) > 1:
            names = ", ".join(sorted(p.name for p in matches))
            row.update(original_filename=names, status="건너뜀", reason="같은 id 파일이 여러 개")
            continue
        src = matches[0]
        row["original_filename"] = src.name
        if src.name == new_name:
            row.update(status="유지", reason="이미 새 이름")
            continue
        plan[src] = (folder / new_name, row)
        row["status"] = "예정"

    # 충돌 검사: 새 이름끼리 겹치거나, 이번에 바뀌지 않는 기존 파일과 겹치는 경우
    targets = [dst for dst, _ in plan.values()]
    for src, (dst, row) in list(plan.items()):
        if targets.count(dst) > 1:
            plan.pop(src)
            row.update(status="건너뜀", reason="새 이름이 다른 행과 중복")
        elif dst.exists() and dst not in plan:
            plan.pop(src)
            row.update(status="건너뜀", reason="같은 이름의 파일이 이미 있음")

    if args.apply:
        # 2단계 변경: 임시 이름을 거쳐 서로 이름이 맞물려도 덮어쓰지 않게 함
        temp = {}
        for src, (dst, row) in plan.items():
            tmp = src.with_name(f".tmp_{uuid.uuid4().hex}.html")
            try:
                src.rename(tmp)
                temp[tmp] = (src, dst, row)
            except OSError as e:
                row.update(status="실패", reason=f"변경 오류: {e}")
        for tmp, (src, dst, row) in temp.items():
            try:
                tmp.rename(dst)
                row.update(status="성공", reason="")
            except OSError as e:
                try:
                    tmp.rename(src)
                    note = "원래 이름으로 복구함"
                except OSError:
                    note = f"복구 실패, 임시 파일명: {tmp.name}"
                row.update(status="실패", reason=f"변경 오류: {e} / {note}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_path = folder / f"rename_result_{stamp}.csv"
    write_csv(result_path, results)
    failed = [r for r in results if r["status"] in ("실패", "건너뜀")]
    if failed:
        write_csv(folder / f"rename_failed_{stamp}.csv", failed)

    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        print(f"[{r['status']}] id {r['id']}: {r['original_filename'] or '-'} -> {r['new_filename']} {r['reason']}")
    print(f"\nCSV {len(mapping)}건 처리 / 요약:", ", ".join(f"{k} {v}개" for k, v in counts.items()))
    if not args.apply:
        print("미리보기입니다. 실제로 바꾸려면 --dry-run 없이 다시 실행하세요.")
    print(f"결과 CSV: {result_path}")
    if failed:
        print(f"실패·건너뜀 CSV: {folder / f'rename_failed_{stamp}.csv'}")


if __name__ == "__main__":
    main()
