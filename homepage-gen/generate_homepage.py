"""
캡처 이미지 + 강조할 기능 -> 단일 HTML 홈페이지 + description 생성기

[준비]
  pip install openai openpyxl python-dotenv
  실행 위치에 .env 파일을 만들고 아래 한 줄 저장 (따옴표 없이):
    OPENAI_API_KEY=sk-...
  ※ set/export로 넣은 환경변수가 있으면 그쪽이 우선합니다.
  실행 위치에 output 폴더를 미리 만들어 두세요. (결과는 ./output 에 저장)

[모드 1] 한 건씩 실행
  python generate_homepage.py --image 메인.png
  python generate_homepage.py --image 메인.png 상세.png --feature "재고 입출고 관리"

[모드 2] CSV / XLSX 파일로 여러 건 자동 실행
  python generate_homepage.py --input tasks.csv
  python generate_homepage.py --input tasks.xlsx

  입력 파일 열 구성 (첫 줄은 제목 행):
    image    : 이미지 경로. 여러 장이면 ; 로 구분 (예: 메인.png;상세.png)
    feature  : 강조할 기능
    #        : (선택) 번호. 있으면 파일명 앞에 붙음 (예: 33_smart-inventory-hub.html)
    참고사항 : (선택) 프롬프트의 '- 참고사항:' 줄에 들어감. 비우면 그 줄은 빠짐
  ※ 이미지 경로는 실행 위치 기준 상대경로 또는 절대경로
"""

import argparse
import base64
import csv
import logging
import mimetypes
import os
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import openai
from openai import OpenAI
from tqdm import tqdm

OUTPUT_DIR = Path("output")  # 실행 위치 기준. 폴더는 직접 만들어 둘 것.
LOG_DIR = Path("log")
DEFAULT_DELAY = 5             # 일괄 모드에서 한 건 끝난 뒤 쉬는 시간(초)
REASONING_EFFORT = "medium"   # 추론 강도: low / medium / high (높을수록 느리고 비쌈)
MAX_OUTPUT_TOKENS = 100000    # 출력 상한 (실제 사용량을 줄이진 않음, 넘으면 잘림)
EXPECTED_CHARS = 60000        # 진행 막대의 예상 길이(글자). 넘으면 자동으로 늘어남
MAX_RETRIES = 5               # 429·5xx·연결 오류 시 SDK 자동 재시도 횟수 (SDK 기본값 2)

# ──────────────────────────────────────────────────────────────
# 사용자가 작성한 프롬프트 원문. {feature} 자리에 입력값이 들어갑니다.
# ──────────────────────────────────────────────────────────────
USER_PROMPT_TEMPLATE = """캡쳐한 이미지를 참고해서 단일 HTML 홈페이지를 만들 예정.
제목은 캡쳐한 내용이랑 너무 똑같이 할 필요는 없음. 조금 다르게 title 만들기.

결과물:

1. 홈페이지
- 주요 기능: **{feature}기능**, 모의 데이터로 가능 제작.
{note_line}
- DEPTH 깊게 해서 클릭시 조회, 바로가기, 다운로드(필요시, 필수X) 등은 기본적으로 탑재하게 해줘.

2. description
- 3문장 정도로 정리해서 작성해주고,
- web browsing 시나리오를 생각해서 작성해주고,
- 내가 구현하려한 기능 참고로 꼭 넣어줘!
"""

# 결과를 파일로 나눠 저장하기 위한 출력 형식 지시 (프롬프트 내용과 별개)
OUTPUT_FORMAT = """
[출력 형식] 아래 구분자를 지켜서 답해줘.
<<<TITLE>>>
(제목 한 줄)
<<<FILENAME>>>
(위 제목을 영어로 옮긴 파일명. 영문 소문자·숫자·하이픈만 사용, 예: smart-inventory-hub)
<<<DESCRIPTION>>>
(description)
<<<HTML>>>
(<!DOCTYPE html>부터 </html>까지 전체 코드)
"""


# ───────────────────────── 입력 파일 읽기 ─────────────────────────
def read_tasks(path: Path) -> list[dict]:
    """CSV/XLSX에서 [{'image': [...], 'feature': '...'}] 목록을 만든다"""
    ext = path.suffix.lower()
    rows = []

    if ext == ".csv":
        # 엑셀에서 저장한 한글 CSV(cp949)도 읽히도록 순서대로 시도
        for enc in ("utf-8-sig", "cp949"):
            try:
                with open(path, newline="", encoding=enc) as f:
                    rows = list(csv.DictReader(f))
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError(f"CSV 인코딩을 읽을 수 없습니다: {path}")

    elif ext in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        ws = load_workbook(path, read_only=True, data_only=True).active
        values = list(ws.iter_rows(values_only=True))
        if not values:
            raise ValueError("엑셀 파일이 비어 있습니다.")
        header = [str(h).strip() if h is not None else "" for h in values[0]]
        rows = [dict(zip(header, r)) for r in values[1:]]
    else:
        raise ValueError("입력 파일은 .csv 또는 .xlsx만 지원합니다.")

    tasks = []
    for i, row in enumerate(rows, start=2):  # 2 = 제목 행 다음 줄
        row = {str(k).strip().lower(): ("" if v is None else str(v).strip()) for k, v in row.items() if k}
        if "image" not in row or "feature" not in row:
            raise ValueError("입력 파일에 image, feature 열이 있어야 합니다.")
        if not row["image"] and not row["feature"]:
            continue  # 빈 줄 건너뜀
        images = [Path(p.strip()) for p in row["image"].split(";") if p.strip()]
        note = row.get("참고사항") or row.get("note") or ""
        tasks.append({"row": i, "images": images, "feature": row["feature"],
                      "no": clean_no(row.get("#", "")), "note": note})
    return tasks


def clean_no(value: str) -> str:
    """엑셀 숫자 33.0 -> '33', 파일명에 못 쓰는 문자는 제거"""
    value = str(value).strip()
    if re.fullmatch(r"\d+\.0+", value):
        value = value.split(".")[0]
    return re.sub(r'[\\/:*?"<>|\s]+', "", value)


# ───────────────────────── GPT 호출 / 파싱 ─────────────────────────
def encode_image(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    if mime not in ("image/png", "image/jpeg", "image/webp", "image/gif"):
        raise ValueError(f"지원하지 않는 이미지 형식: {path}")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def build_prompt(feature: str, note: str = "") -> str:
    """참고사항이 있을 때만 '- 참고사항: ...' 줄을 넣음"""
    note_line = f"- 참고사항: {note}\n" if note.strip() else ""
    return USER_PROMPT_TEMPLATE.format(feature=feature, note_line=note_line) + OUTPUT_FORMAT


def call_gpt(client: OpenAI, images: list[Path], prompt: str, model: str, label: str = "") -> str:
    content = [{"type": "input_text", "text": prompt}]
    content += [{"type": "input_image", "image_url": encode_image(p), "detail": "high"} for p in images]
    stream = client.responses.create(
        model=model,
        input=[{"role": "user", "content": content}],
        reasoning={"effort": REASONING_EFFORT},
        max_output_tokens=MAX_OUTPUT_TOKENS,
        stream=True,                    # 생성되는 글자를 실시간으로 받음
    )

    chunks, final = [], None
    bar = tqdm(total=EXPECTED_CHARS, desc=f"{label} 생각 중", unit="자",
               position=1, leave=False, dynamic_ncols=True)
    stop = threading.Event()

    def tick():                         # 글자가 안 들어오는 '생각 중'에도 경과 시간 갱신
        while not stop.wait(1):
            bar.refresh()

    threading.Thread(target=tick, daemon=True).start()
    try:
        for event in stream:
            if event.type == "response.output_text.delta":
                if not chunks:
                    bar.set_description(f"{label} HTML 작성 중")
                chunks.append(event.delta)
                bar.update(len(event.delta))
                if bar.n > bar.total:   # 예상보다 길면 막대 끝을 늘림
                    bar.total = int(bar.n * 1.2)
            elif event.type in ("response.completed", "response.incomplete"):
                final = event.response
            elif event.type in ("response.failed", "error"):
                raise RuntimeError(f"생성 실패 이벤트: {event}")
    finally:
        stop.set()
        bar.close()

    # 사용량과 잘림 여부를 로그에 기록
    if final is not None:
        u = final.usage
        if u:
            log.info("토큰 사용량 | 입력=%s | 출력=%s", u.input_tokens, u.output_tokens)
        if final.status == "incomplete":
            log.warning("응답이 중간에 끊김: %s", final.incomplete_details)

    return "".join(chunks)


def parse_output(text: str) -> dict:
    m = re.search(
        r"<<<TITLE>>>\s*(.*?)\s*(?:<<<FILENAME>>>\s*(.*?)\s*)?<<<DESCRIPTION>>>\s*(.*?)\s*<<<HTML>>>\s*(.*)",
        text, re.S,
    )
    if not m:
        raise ValueError("응답 형식이 올바르지 않음 (raw_response 파일 확인)")
    html = re.sub(r"^```(?:html)?\s*|\s*```$", "", m.group(4).strip())
    return {
        "title": m.group(1).strip(),
        "filename": (m.group(2) or "").strip(),
        "description": m.group(3).strip(),
        "html": html,
    }


def to_filename(name: str, fallback: str) -> str:
    """영문 소문자·숫자·하이픈만 남긴 안전한 파일명으로 정리"""
    name = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60].strip("-")
    return name or fallback  # 영문이 하나도 없으면 날짜_순번 이름 사용


def unique_base(base: str) -> str:
    """output에 같은 이름이 있으면 -2, -3 ... 을 붙임"""
    candidate, n = base, 2
    while (OUTPUT_DIR / f"{candidate}.html").exists():
        candidate, n = f"{base}-{n}", n + 1
    return candidate


# ───────────────────────── 한 건 처리 ─────────────────────────
def run_one(client: OpenAI, images: list[Path], feature: str, model: str, tag: str,
            no: str = "", note: str = "") -> dict:
    for p in images:
        if not p.exists():
            raise FileNotFoundError(f"이미지를 찾을 수 없음: {p}")
    if not images:
        raise ValueError("이미지가 지정되지 않음")
    if not feature:
        raise ValueError("기능이 비어 있음")

    raw = call_gpt(client, images, build_prompt(feature, note), model, label=f"#{no}" if no else "")
    try:
        result = parse_output(raw)
    except ValueError:
        # 형식이 깨졌을 때만 원본 응답을 보관 (원인 확인용)
        (LOG_DIR / f"FAILED_{no + '_' if no else ''}{tag}_raw_response.txt").write_text(raw, encoding="utf-8")
        raise

    name = to_filename(result["filename"], tag)
    base = unique_base(f"{no}_{name}" if no else name)  # 예: 33_smart-inventory-hub
    html_path = OUTPUT_DIR / f"{base}.html"
    html_path.write_text(result["html"], encoding="utf-8")
    truncated = "</html>" not in result["html"].lower()
    return {**result, "html_path": str(html_path), "file_name": html_path.name, "truncated": truncated}


def is_quota_error(e: Exception) -> bool:
    """429 중 기다려도 풀리지 않는 결제·한도 소진 오류인지 판별"""
    code = getattr(e, "code", None) or ""
    return code == "insufficient_quota" or "insufficient_quota" in str(e)


def load_api_key() -> str:
    """실행 위치의 .env 파일에서 키를 읽음 (환경변수에 이미 있으면 그대로 사용)"""
    env_file = Path(".env")
    if env_file.is_file():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file, override=False)
            log.info(".env 파일 확인: %s", env_file.resolve())
        except ImportError:
            log.error("python-dotenv가 설치되지 않아 .env를 읽지 못함 (pip install python-dotenv)")
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY가 없음 (.env 파일 또는 환경변수 확인)")
    log.info("API 키 확인: %s...%s", key[:6], key[-4:])  # 전체 키는 로그에 남기지 않음
    return key


# ───────────────────────── 로그 설정 ─────────────────────────
log = logging.getLogger("homepage")

class TqdmHandler(logging.Handler):
    """로그를 진행 막대 위에 출력"""
    def emit(self, record):
        try:
            tqdm.write(self.format(record))
        except Exception:
            self.handleError(record)


def setup_logging(stamp: str) -> Path:
    """log/run_날짜.log 파일에 기록 + 화면에도 진행 상황 표시"""
    log_file = LOG_DIR / f"run_{stamp}.log"
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(fmt)
    console_handler = TqdmHandler() # 진행 막대를 깨지 않고 화면에 출력
    console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    log.addHandler(file_handler)
    log.addHandler(console_handler)
    return log_file

DESC_HEADER = ["#", "제목", "파일명", "강조 기능", "참고사항", "description"]

def init_desc_file(stamp: str) -> Path:
    """이번 실행의 description을 모두 모을 CSV (엑셀에서 바로 열림)"""
    path = OUTPUT_DIR / f"descriptions_{stamp}.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerow(DESC_HEADER)
    return path

def append_desc(path: Path, no: str, r: dict, feature: str, note: str) -> None:
    """한 건 끝날 때마다 바로 추가 (중간에 멈춰도 그때까지는 저장됨)"""
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerow([no, r["title"], r["file_name"], feature, note, r["description"]])


# ───────────────────────── 메인 ─────────────────────────
def main():
    parser = argparse.ArgumentParser(description="캡처 기반 HTML 홈페이지 생성기")
    parser.add_argument("--input", help="일괄 처리용 CSV/XLSX 파일")
    parser.add_argument("--image", nargs="+", help="캡처 이미지 경로 (한 건 모드)")
    parser.add_argument("--feature", help="강조할 기능 (한 건 모드, 생략하면 입력받음)")
    parser.add_argument("--no", default="", help="파일명 앞에 붙일 번호 (한 건 모드, 선택)")
    parser.add_argument("--note", help="참고사항 (한 건 모드, 생략하면 입력받음. Enter로 건너뛰기)")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-6.1-sol"))
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="일괄 모드 건 사이 대기(초)")
    args = parser.parse_args()

    # output 폴더가 없으면 로그 파일도 만들 수 없으므로 여기서만 바로 종료
    if not OUTPUT_DIR.is_dir():
        sys.exit(f"'{OUTPUT_DIR}' 폴더가 없습니다. 실행 위치({Path.cwd()})에 output 폴더를 만들어 주세요.")
    if not LOG_DIR.is_dir():
        sys.exit(f"'{LOG_DIR}' 폴더가 없습니다. 실행 위치({Path.cwd()})에 log 폴더를 만들어 주세요.")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = setup_logging(stamp)
    log.info("실행 시작 | 모델=%s | 작업폴더=%s", args.model, Path.cwd())

    try:
        client = OpenAI(api_key=load_api_key(), max_retries=MAX_RETRIES, timeout=1800)
    except Exception:
        log.exception("OpenAI 클라이언트 생성 실패 (.env 파일의 OPENAI_API_KEY 확인)")
        sys.exit(1)

    # ── 모드 2: 파일 일괄 처리 ──
    if args.input:
        try:
            tasks = read_tasks(Path(args.input))
        except Exception:
            log.exception("입력 파일을 읽지 못함: %s", args.input)
            sys.exit(1)

        log.info("총 %d건 처리 시작 (입력파일=%s, 대기=%s초, 재시도=%d회)",
                 len(tasks), args.input, args.delay, MAX_RETRIES)
        desc_file = init_desc_file(stamp)
        results = []
        overall = tqdm(total=len(tasks), desc="전체", unit="건", position=0, dynamic_ncols=True)
        for n, t in enumerate(tasks, start=1):
            tag = f"{stamp}_{n:03d}"
            log.info("[%d/%d] 입력파일 %d행 | #=%s | 기능=%s | 참고사항=%s | 이미지=%s",
                     n, len(tasks), t["row"], t["no"] or "-", t["feature"], t["note"] or "-",
                     ";".join(map(str, t["images"])))
            try:
                r = run_one(client, t["images"], t["feature"], args.model, tag, t["no"], t["note"])
                append_desc(desc_file, t["no"], r, t["feature"], t["note"])
                if r["truncated"]:
                    status = "잘림 의심"
                    log.warning("[%d/%d] HTML이 잘린 것 같음: %s", n, len(tasks), r["html_path"])
                else:
                    status = "성공"
                    log.info("[%d/%d] 성공 | 제목=%s | %s", n, len(tasks), r["title"], r["html_path"])
                results.append([t["row"], t["no"], t["feature"], status, r["title"], r["html_path"], ""])
            except openai.RateLimitError as e:
                if is_quota_error(e):  # 크레딧·한도 소진: 기다려도 해결 안 되므로 중단
                    log.error("[%d/%d] 크레딧/사용 한도 소진으로 일괄 처리 중단 | %s", n, len(tasks), e)
                    results.append([t["row"], t["no"], t["feature"], "실패", "", "", "크레딧/한도 소진"])
                    for rest in tasks[n:]:
                        results.append([rest["row"], rest["no"], rest["feature"], "미실행", "", "", "중단으로 미실행"])
                    break
                log.exception("[%d/%d] 요청 한도 초과(재시도 %d회 후에도 실패) | #=%s",
                              n, len(tasks), MAX_RETRIES, t["no"] or "-")
                results.append([t["row"], t["no"], t["feature"], "실패", "", "", str(e)])
            except Exception as e:  # 한 건이 실패해도 다음 건 계속, 상세 오류는 로그에 기록
                log.exception("[%d/%d] 실패 | 입력파일 %d행 | #=%s | 기능=%s",
                              n, len(tasks), t["row"], t["no"] or "-", t["feature"])
                results.append([t["row"], t["no"], t["feature"], "실패", "", "", str(e)])

            overall.update(1)
            if n < len(tasks) and args.delay > 0:  # 마지막 건 뒤에는 쉬지 않음
                log.info("다음 건까지 %s초 대기", args.delay)
                time.sleep(args.delay)

        overall.close()
        result_csv = LOG_DIR / f"{stamp}_result_log.csv"
        with open(result_csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["입력행", "#", "기능", "상태", "제목", "HTML", "오류"])
            w.writerows(results)
        ok = sum(1 for r in results if r[3] == "성공")
        log.info("완료 | 성공 %d / 전체 %d | description 모음=%s | 결과표=%s | 로그=%s",
                ok, len(results), desc_file, result_csv, log_file)
        return

    # ── 모드 1: 한 건 처리 ──
    if not args.image:
        log.error("--image 또는 --input 중 하나를 지정해야 함")
        sys.exit(1)
    feature = args.feature
    while not feature:
        feature = input("강조할 기능을 입력하세요 (예: 회의실 예약 현황 조회): ").strip()

    note = args.note if args.note is not None else input("참고사항을 입력하세요 (없으면 Enter): ").strip()

    log.info("기능=%s | 참고사항=%s | 이미지=%s", feature, note or "-", ";".join(args.image))
    log.info("전송할 프롬프트:\n%s", build_prompt(feature, note))
    log.info("생성 중... (1~3분 걸릴 수 있음)")
    try:
        r = run_one(client, [Path(p) for p in args.image], feature, args.model, stamp, clean_no(args.no), note)
    except Exception:
        log.exception("생성 실패 | 기능=%s", feature)
        sys.exit(1)

    if r["truncated"]:
        log.warning("HTML이 잘린 것 같음. max_output_tokens를 늘려 다시 시도: %s", r["html_path"])
    desc_file = init_desc_file(stamp)
    append_desc(desc_file, clean_no(args.no), r, feature, note)
    log.info("완료 | 제목=%s | HTML=%s | description 모음=%s", r["title"], r["html_path"], desc_file)

if __name__ == "__main__":
    main()