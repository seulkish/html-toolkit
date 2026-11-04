"""
HTML 파일 난이도(Grade) 평가 스크립트

진행 흐름
  1. html 폴더에 있는 파일명을 읽는다.
  2. 파일을 하나씩 열어 평가 항목(페이지 수, 최대 Depth, 기능 수)을 센다.
  3. 항목별 점수를 합산해 grade(하/중/상)를 정하고 result.csv에 기록한다.

필요한 라이브러리:  pip install beautifulsoup4
"""

import csv
import os
import re

from bs4 import BeautifulSoup

# ──────────────────────────────────────────────
# 설정값 (필요하면 여기만 바꾸면 됩니다)
# ──────────────────────────────────────────────
HTML_FOLDER = "html"          # HTML 파일이 들어 있는 폴더
OUTPUT_CSV = "result.csv"     # 결과 CSV 파일명


# ──────────────────────────────────────────────
# 1) 평가표 → 점수 변환 (이미지의 표 그대로)
# ──────────────────────────────────────────────
def score_pages(count):
    """페이지 수: 1~3개=1점, 4~7개=2점, 8개 이상=3점"""
    if count <= 3:
        return 1
    if count <= 7:
        return 2
    return 3


def score_depth(depth):
    """최대 Depth: 1~2단계=1점, 3단계=2점, 4단계 이상=3점"""
    if depth <= 2:
        return 1
    if depth == 3:
        return 2
    return 3


def score_features(count):
    """기능 수: 1~4개=1점, 5~9개=2점, 10개 이상=3점"""
    if count <= 4:
        return 1
    if count <= 9:
        return 2
    return 3


def total_to_grade(total):
    """합산 점수: 3~4점=하, 5~7점=중, 8~9점=상"""
    if total <= 4:
        return "하"
    if total <= 7:
        return "중"
    return "상"


# ──────────────────────────────────────────────
# 2) HTML에서 평가 항목 세기
#    ※ HTML 구조에 따라 기준이 달라질 수 있으니
#      실제 파일에 맞게 이 부분을 조정하세요.
# ──────────────────────────────────────────────
def count_pages(soup):
    """
    페이지 수를 센다.
      ① data-page 속성이 있는 요소
      ② class가 정확히 'page' 또는 'screen'인 요소
      ③ 위 둘이 없으면 <section> 태그 수
      ④ 아무것도 없으면 1페이지로 본다
    """
    pages = soup.select("[data-page]")
    if not pages:
        pages = [
            tag for tag in soup.find_all(class_=True)
            if {"page", "screen"} & set(tag.get("class", []))
        ]
    if not pages:
        pages = soup.find_all("section")
    return max(len(pages), 1)


def count_max_depth(soup):
    """
    메뉴의 최대 Depth를 센다.
      <nav> 안의 <ul>/<ol>이 몇 단계로 중첩되어 있는지 확인한다.
      <nav>가 없으면 문서 전체의 목록 중첩을 본다.
      목록이 하나도 없으면 1단계로 본다.
    """
    roots = soup.find_all("nav") or [soup]
    max_depth = 1
    for root in roots:
        for lst in root.find_all(["ul", "ol"]):
            # 자기 자신 + 위쪽에 있는 ul/ol 개수 = 현재 단계
            depth = 1
            parent = lst.parent
            while parent is not None and parent is not root:
                if parent.name in ("ul", "ol"):
                    depth += 1
                parent = parent.parent
            max_depth = max(max_depth, depth)
    return max_depth


def count_features(soup):
    """
    기능 수를 센다. (사용자가 조작할 수 있는 요소)
      button, select, textarea, input(hidden 제외),
      onclick 속성이 있는 요소, href="javascript:..." 링크
    같은 요소는 한 번만 센다.
    """
    features = set()
    for tag in soup.find_all(["button", "select", "textarea"]):
        features.add(id(tag))
    for tag in soup.find_all("input"):
        if tag.get("type", "text").lower() != "hidden":
            features.add(id(tag))
    for tag in soup.find_all(attrs={"onclick": True}):
        features.add(id(tag))
    for tag in soup.find_all("a", href=re.compile(r"^\s*javascript:", re.I)):
        features.add(id(tag))
    return len(features)


# ──────────────────────────────────────────────
# 3) 파일 하나 평가하기
# ──────────────────────────────────────────────
def evaluate_file(filepath):
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    pages = count_pages(soup)
    depth = count_max_depth(soup)
    features = count_features(soup)

    p_score = score_pages(pages)
    d_score = score_depth(depth)
    f_score = score_features(features)
    total = p_score + d_score + f_score
    grade = total_to_grade(total)

    memo = (
        f"페이지 수 {pages}개({p_score}점) / "
        f"최대 Depth {depth}단계({d_score}점) / "
        f"기능 수 {features}개({f_score}점) "
        f"→ 합산 {total}점 = {grade}"
    )
    return grade, memo


# ──────────────────────────────────────────────
# 4) 폴더의 파일 목록 가져오기 (1_, 2_, 10_ 순서로 정렬)
# ──────────────────────────────────────────────
def natural_key(filename):
    """'10_a.html'이 '2_a.html'보다 뒤에 오도록 앞 숫자 기준 정렬"""
    match = re.match(r"(\d+)", filename)
    return (int(match.group(1)) if match else float("inf"), filename)


def get_html_files(folder):
    files = [
        name for name in os.listdir(folder)
        if name.lower().endswith((".html", ".htm"))
    ]
    return sorted(files, key=natural_key)


# ──────────────────────────────────────────────
# 실행 부분
# ──────────────────────────────────────────────
if __name__ == "__main__":
    # 1. 폴더 확인 및 파일명 읽기
    if not os.path.isdir(HTML_FOLDER):
        print(f"[오류] '{HTML_FOLDER}' 폴더를 찾을 수 없습니다.")
        raise SystemExit(1)

    html_files = get_html_files(HTML_FOLDER)
    print(f"'{HTML_FOLDER}' 폴더에서 HTML 파일 {len(html_files)}개를 찾았습니다.\n")

    # 2~3. 파일을 하나씩 평가해서 결과 모으기
    rows = []
    for no, filename in enumerate(html_files, start=1):
        filepath = os.path.join(HTML_FOLDER, filename)
        try:
            grade, memo = evaluate_file(filepath)
        except Exception as e:          # 파일 하나가 깨져도 나머지는 계속 진행
            grade, memo = "오류", f"파일 처리 실패: {e}"

        rows.append({"no": no, "filename": filename, "grade": grade, "memo": memo})
        print(f"[{no}] {filename} → {grade}  ({memo})")

    # 4. CSV 저장 (utf-8-sig: 엑셀에서 열어도 한글이 깨지지 않음)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["no", "filename", "grade", "memo"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n완료! 결과가 '{OUTPUT_CSV}'에 저장되었습니다.")
