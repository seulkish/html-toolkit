#!/usr/bin/env python3
"""폴더 안 HTML 중 이미지가 들어 있는 파일만 골라 html_img 폴더로 복사(또는 이동)합니다.

사용 예 (Windows):
  py find_img_html.py "C:\\work\\html"
  py find_img_html.py "C:\\work\\html" --output "C:\\work\\html_img" --recursive --with-assets
  py find_img_html.py "C:\\work\\html" --move
"""
import argparse
import csv
import re
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

# ===== 여기만 수정하세요 =====
# 검사할 HTML 폴더. 경로 앞의 r은 역슬래시(\)를 그대로 쓰기 위해 필요합니다.
DEFAULT_FOLDER = r"C:\Users\DevHjj\Desktop\html-toolkit\html_qa\html_input"   # 예: r"C:\work\html_input"
# 결과 폴더. None이면 검사 폴더와 같은 위치에 html_img를 만듭니다.
DEFAULT_OUTPUT = None   # 예: r"C:\work\html_img"
# ============================

IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp",
           ".ico", ".avif", ".tif", ".tiff", ".jfif")
CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I)


def is_image_url(u: str) -> bool:
    u = u.strip()
    if u.lower().startswith("data:image"):
        return True
    path = urlsplit(u).path.lower()
    return path.endswith(IMG_EXT)


def parse_srcset(srcset: str):
    out = []
    for part in srcset.split(","):
        part = part.strip()
        if part:
            out.append(part.split()[0])
    return out


class ImageFinder(HTMLParser):
    """HTML 코드에 직접 적힌 이미지를 찾습니다 (JS로 나중에 넣는 이미지는 못 찾음)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.reasons = []      # 근거 표시용 (종류, 값)
        self.refs = []         # 로컬 이미지 복사 후보
        self._in_style = False
        self._picture = 0

    def _add(self, kind, value, is_ref=True):
        self.reasons.append((kind, value))
        if is_ref and value:
            self.refs.append(value)

    def _css(self, css_text, kind):
        for m in CSS_URL_RE.finditer(css_text):
            u = m.group(2)
            if is_image_url(u):
                self._add(kind, u)

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "img":
            self._add("img", a.get("src", "") or "(src 비어 있음)", bool(a.get("src")))
            self.refs.extend(parse_srcset(a.get("srcset", "")))
        elif tag == "picture":
            self._picture += 1
        elif tag == "source" and self._picture > 0:
            for u in parse_srcset(a.get("srcset", "")):
                self._add("picture source", u)
        elif tag == "svg":
            self._add("svg", "(인라인 SVG)", False)
        elif tag == "image":  # SVG 내부 <image>
            href = a.get("href") or a.get("xlink:href", "")
            self._add("svg image", href or "(href 없음)", bool(href))
        elif tag == "input" and a.get("type", "").lower() == "image":
            self._add("input type=image", a.get("src", ""))
        elif tag == "video" and a.get("poster"):
            self._add("video poster", a["poster"])
        elif tag == "style":
            self._in_style = True
        if "style" in a:
            self._css(a["style"], f"{tag} style 배경")

    def handle_endtag(self, tag):
        if tag == "style":
            self._in_style = False
        elif tag == "picture" and self._picture > 0:
            self._picture -= 1

    def handle_data(self, data):
        if self._in_style:
            self._css(data, "<style> 배경")


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("latin-1")


def unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    i = 1
    while True:
        cand = p.with_name(f"{p.stem}_{i}{p.suffix}")
        if not cand.exists():
            return cand
        i += 1


def copy_assets(refs, html_path: Path, root: Path, out: Path):
    copied, missing = 0, []
    for u in dict.fromkeys(refs):  # 중복 제거, 순서 유지
        s = urlsplit(u.strip())
        if s.scheme or s.netloc:      # http, data:, // 등 외부/내장 이미지는 건너뜀
            continue
        rel = unquote(s.path)
        if not rel:
            continue
        src = (root / rel.lstrip("/")) if rel.startswith("/") else (html_path.parent / rel)
        try:
            src = src.resolve()
            inside = src.is_relative_to(root)
        except (OSError, ValueError):
            inside = False
        if not inside or not src.is_file():
            missing.append(u)
            continue
        dest = out / src.relative_to(root)
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            copied += 1
    return copied, missing


def main():
    ap = argparse.ArgumentParser(description="이미지가 들어 있는 HTML만 골라 html_img 폴더로 보냅니다.")
    ap.add_argument("folder", nargs="?", default=DEFAULT_FOLDER,
                    help=f"검사할 HTML 폴더 (생략하면 코드의 DEFAULT_FOLDER: {DEFAULT_FOLDER})")
    ap.add_argument("--output", default=DEFAULT_OUTPUT,
                    help="결과 폴더 (기본: 검사 폴더와 같은 위치의 html_img)")
    ap.add_argument("--move", action="store_true", help="복사 대신 이동 (원본 폴더에서 빠짐)")
    ap.add_argument("--recursive", action="store_true", help="하위 폴더까지 검사")
    ap.add_argument("--include-htm", action="store_true", help=".htm 파일도 검사")
    ap.add_argument("--with-assets", action="store_true",
                    help="HTML이 참조하는 로컬 이미지 파일도 같은 상대 경로로 함께 복사")
    args = ap.parse_args()

    root = Path(args.folder).resolve()
    if not root.is_dir():
        sys.exit(f"폴더를 찾을 수 없습니다: {root}")
    out = Path(args.output).resolve() if args.output else root.parent / "html_img"
    out.mkdir(parents=True, exist_ok=True)   # 없으면 생성

    patterns = ["*.html"] + (["*.htm"] if args.include_htm else [])
    files = []
    for pat in patterns:
        files += root.rglob(pat) if args.recursive else root.glob(pat)
    files = sorted(f for f in files if f.is_file() and not f.resolve().is_relative_to(out))

    rows, hit = [], 0
    for f in files:
        rel = f.relative_to(root)
        try:
            finder = ImageFinder()
            finder.feed(read_text(f))
            finder.close()
        except Exception as e:  # 읽기 실패 파일도 기록
            rows.append([str(rel).replace("\\", "/"), "읽기 오류", str(e), "", "", ""])
            continue

        if not finder.reasons:
            rows.append([str(rel).replace("\\", "/"), "없음", "", "", "", ""])
            continue

        hit += 1
        assets, missing = ("", "")
        if args.with_assets:
            c, m = copy_assets(finder.refs, f, root, out)
            assets, missing = c, " | ".join(m)
        dest = unique_path(out / rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        (shutil.move if args.move else shutil.copy2)(str(f), str(dest))

        reason = " | ".join(f"{k}: {v}" for k, v in finder.reasons[:10])
        if len(finder.reasons) > 10:
            reason += f" | 외 {len(finder.reasons) - 10}건"
        rows.append([str(rel).replace("\\", "/"), "있음", reason,
                     str(dest.relative_to(out)).replace("\\", "/"), assets, missing])

    report = out / "image_check.csv"
    with open(report, "w", newline="", encoding="utf-8-sig") as fp:
        w = csv.writer(fp)
        w.writerow(["파일", "이미지", "근거(최대 10건)", "보낸 위치", "복사한 이미지 수", "찾지 못한 이미지"])
        w.writerows(rows)

    print(f"검사 {len(files)}개 / 이미지 있음 {hit}개 → {'이동' if args.move else '복사'}: {out}")
    print(f"결과표: {report}")


if __name__ == "__main__":
    main()
