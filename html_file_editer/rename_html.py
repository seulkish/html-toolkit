"""
result.csv의 new_filename 열에 적힌 이름으로 HTML 파일명을 바꿉니다.
result.csv는 html_grader_functions.py가 만드는 결과 파일이고, 그 파일을 그대로 읽습니다.
  1) python html_grader_functions.py  -> result.csv 생성 (no, id, filename, new_filename, grade, ...)
     new_filename은 grader가 규칙({id 3자리}_{날짜}_{작성자}.html)대로 채움. 날짜 구간은 grader의 NEW_NAME_DATES
  2) python rename_html.py            -> 파일명 변경 + result.csv의 filename도 새 이름으로 맞춤
  new_filename이 빈칸인 행은 바꾸지 않습니다. 규칙에 없는 id는 result.csv에 새 이름을 직접 적어도 됩니다.

new_filename이 적힌 id만 골라 바꿉니다. 폴더에 파일이 더 있어도 나머지 파일은 건드리지 않습니다.
파일명을 "_"로 나눈 맨 앞 숫자를 id로 보고 CSV의 id와 맞춥니다.
  예) 1_test_test.html -> id 1 -> CSV의 new_filename(001_20261019_sklee.html)
예전 형식의 CSV(id, original_filename, new_filename)도 그대로 쓸 수 있습니다.

실행할 때마다 폴더에 결과 CSV를 남깁니다.
  rename_result_날짜_시간.csv : new_filename이 적힌 모든 id 결과
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
HTML_FOLDER = "html_input_files" # HTML 파일이 있는 폴더
CSV_FILE = "result.csv"          # html_grader_functions.py의 결과 파일 (OUTPUT_CSV와 같은 이름)
UPDATE_CSV = True                # True: 이름을 바꾼 뒤 result.csv의 filename 열도 새 이름으로 맞춤
# ==========================================

SCRIPT_DIR = Path(__file__).resolve().parent

FIELDS = ["id", "original_filename", "new_filename", "status", "reason"]


def parse_id(text):
    """'1', '001', ' 1 ' -> 1 / 숫자가 아니면 None"""
    text = (text or "").strip()
    return int(text) if text.isdecimal() else None


def load_mapping(csv_path):
    """
    CSV에 적힌 순서대로 {id: new_filename}을 돌려줌. new_filename이 빈 행은 바꾸지 않을 파일로 보고 건너뜀.
    읽을 수 있는 형식
      - html_grader_functions.py의 result.csv : no, id, filename, new_filename, grade, ...
      - 직접 만든 CSV                          : id, original_filename, new_filename
    id 열이 없으면 filename(original_filename)을 "_"로 나눈 맨 앞 숫자를 id로 봄.
    함께 돌려주는 source는 result.csv의 filename 칸을 고쳐 쓸 때 사용 (update_csv_filenames)
    """
    for enc in ("utf-8-sig", "cp949"):  # 엑셀 CSV(BOM) / 한글 엑셀(cp949)
        try:
            with open(csv_path, newline="", encoding=enc) as f:
                table = list(csv.reader(f))  # table[0] = 열 이름, table[1:] = 데이터 행
            break
        except UnicodeDecodeError:
            continue
    else:
        sys.exit("CSV 인코딩을 읽을 수 없습니다 (utf-8 / cp949 모두 실패).")

    col = {}  # 열 이름 -> 몇 번째 칸인지
    for i, name in enumerate(table[0] if table else []):
        col.setdefault(name.strip(), i)
    if "new_filename" not in col:
        sys.exit(f"CSV에 new_filename 열이 없습니다: {csv_path}\n"
                 "html_grader_functions.py를 다시 실행하면 new_filename 열이 있는 result.csv가 만들어집니다.")
    name_col = col.get("filename", col.get("original_filename"))  # 원래 파일명이 적힌 열
    if "id" not in col and name_col is None:
        sys.exit(f"CSV에 id 열도 filename 열도 없어 어떤 파일인지 알 수 없습니다: {csv_path}")

    def cell(row, i):
        return row[i].strip() if i is not None and i < len(row) else ""

    mapping = {}
    row_of = {}  # id -> table에서 몇 번째 행인지
    blank = 0
    for index, row in enumerate(table[1:], start=1):
        line_no = index + 1  # 엑셀에서 보이는 행 번호 (1행은 열 이름)
        old_name = cell(row, name_col)
        new_name = cell(row, col["new_filename"])
        if not new_name:
            if any(c.strip() for c in row):  # 완전히 빈 줄은 세지 않음
                blank += 1
            continue
        file_id = parse_id(cell(row, col["id"]) if "id" in col else old_name.split("_")[0])
        if file_id is None:
            print(f"[CSV 건너뜀] {line_no}행: id가 비어 있거나 숫자가 아님 -> {old_name or '-'} / {new_name}")
            continue
        if not new_name.lower().endswith(".html"):
            new_name += ".html"
        if file_id in mapping:
            sys.exit(f"CSV에 id {file_id}가 중복됩니다 ({line_no}행). 정리 후 다시 실행하세요.")
        mapping[file_id] = new_name
        row_of[file_id] = index
    if blank:
        print(f"[CSV] new_filename이 빈 {blank}행은 이름을 바꾸지 않고 건너뜁니다.")

    source = {"path": csv_path, "encoding": enc, "table": table, "row_of": row_of,
              "filename_col": col.get("filename")}  # filename 열은 result.csv에만 있음
    return mapping, source


def update_csv_filenames(source, results):
    """
    result.csv의 filename 칸을 실제 파일명(새 이름)으로 맞춤. 다른 칸과 다른 행은 그대로 둠.
    고친 행 수를 돌려줌. CSV가 열려 있어(엑셀 등) 저장하지 못하면 None
    """
    table, col = source["table"], source["filename_col"]
    changed = 0
    for r in results:
        if r["status"] not in ("성공", "유지"):  # 지금 그 이름의 파일이 실제로 있는 행만
            continue
        row = table[source["row_of"][r["id"]]]
        if len(row) <= col:
            row.extend([""] * (col + 1 - len(row)))
        if row[col].strip() != r["new_filename"]:
            row[col] = r["new_filename"]
            changed += 1
    if not changed:
        return 0

    # 임시 파일에 다 쓴 뒤 바꿔치기: 쓰는 도중 문제가 생겨도 원래 CSV가 망가지지 않게 함
    path = source["path"]
    tmp = path.with_name(f".tmp_{uuid.uuid4().hex}.csv")
    try:
        with open(tmp, "w", newline="", encoding=source["encoding"]) as f:
            csv.writer(f).writerows(table)
        tmp.replace(path)
    except (OSError, UnicodeError):
        if tmp.exists():
            tmp.unlink()
        return None
    return changed


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
    mapping, source = load_mapping(csv_path)
    if not mapping:
        sys.exit(f"바꿀 파일이 없습니다. {csv_path.name}의 new_filename이 모두 빈칸입니다.\n"
                 "html_grader_functions.py의 NEW_NAME_DATES에 해당 id 구간이 있는지 확인하거나, new_filename을 직접 적어 주세요.")

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

    synced = 0
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

        # result.csv의 filename도 새 이름으로 맞춤 (예전 형식 CSV에는 filename 열이 없어 하지 않음)
        if UPDATE_CSV and source["filename_col"] is not None:
            synced = update_csv_filenames(source, results)

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
    print(f"\n{csv_path.name} {len(mapping)}건 처리 / 요약:", ", ".join(f"{k} {v}개" for k, v in counts.items()))
    if not args.apply:
        print("미리보기입니다. 실제로 바꾸려면 --dry-run 없이 다시 실행하세요.")
    print(f"결과 CSV: {result_path}")
    if failed:
        print(f"실패·건너뜀 CSV: {folder / f'rename_failed_{stamp}.csv'}")
    if synced:
        print(f"{csv_path.name}의 filename {synced}건을 새 이름으로 맞췄습니다.")
    elif synced is None:
        print(f"[주의] {csv_path.name} 파일이 열려 있어(엑셀 등) filename을 새 이름으로 맞추지 못했습니다.")
        print("       파일명 변경은 끝났습니다. CSV를 닫고 이 스크립트를 한 번 더 실행하면 맞춰집니다.")


if __name__ == "__main__":
    main()
