"""
HTML 파일 난이도(Grade) 평가 + 주요 기능 추출 스크립트

진행 흐름
  1. html 폴더에 있는 파일명을 읽는다.
  2. 파일을 하나씩 열어 주요 기능을 찾는다. (근거 단어도 기록)
     - 일반 HTML 태그뿐 아니라 <script> 안에서 만들어지는 화면,
       <style> 안의 반응형 CSS(@media)까지 확인한다.
  3. 평가 항목(페이지 수, 최대 Depth, 기능 수)을 센다.
     - 기능 수 = 2번에서 찾은 기능 종류 수
  4. 항목별 점수를 합산해 grade(하/중/상)를 정한다.
  5. 결과를 result.csv에 기록한다.
     (no, filename, grade, grade_memo, functions, function_evidence)

필요한 라이브러리:  pip install -r requirements.txt
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

# 기능 사전: {기능명: [이 기능이 있다고 볼 단어들]}
#   - 위에서부터 순서대로 functions 열에 적힙니다.
#   - 한글 단어는 글자가 포함되어 있으면 일치로 봅니다.
#   - 영어 단어는 단어 단위로 비교합니다. (login → login_btn, btnLogin O / blogin X)
#   - 빠진 기능이 있으면 function_evidence 열의 '분류 안 된 버튼'을 보고
#     여기에 기능이나 단어를 추가하면 됩니다.
FUNCTION_KEYWORDS = {
    # ── 기능 목록표(이미지) 기준 ──
    "회원가입": [
        "회원가입", "회원 가입", "약관 동의", "약관동의", "본인인증", "본인 인증",
        "sign up", "signup", "register",
    ],
    "로그인, 로그아웃": [
        "로그인", "로그아웃", "login", "logout", "log in", "log out",
        "sign in", "signin", "sign out", "signout",
    ],
    "검색": ["검색", "search"],
    "카테고리 관리": ["카테고리", "category", "categories"],
    "게시물, 상품, 데이터 관리": [
        "게시판", "게시물", "게시글", "글쓰기", "글 쓰기", "상품 등록",
        "board", "article",
    ],
    "파일 업로드": ["업로드", "파일 첨부", "첨부파일", "첨부 파일", "upload"],
    "파일 다운로드": ["다운로드", "내려받기", "내보내기", "자료집", "download", "export"],
    "장바구니 관리": ["장바구니", "cart", "basket"],
    "예약, 일정 관리": ["예약", "일정", "reservation", "booking", "schedule", "calendar"],
    "결제, 환불": ["결제", "환불", "주문", "구매", "payment", "checkout", "pay", "refund"],
    "신청, 접수, 제출": ["신청", "접수", "제출", "민원", "apply", "application"],
    "정보 수정, 설정": [
        "정보 수정", "정보수정", "내 정보", "내정보", "마이페이지", "비밀번호 변경",
        "환경 설정", "환경설정", "알림 설정", "설정", "알림 기준",
        "mypage", "my page", "profile", "settings", "setting",
    ],
    "댓글, 문의, 답변": ["댓글", "문의", "답변", "상담", "comment", "reply", "qna", "inquiry", "contact"],
    "좋아요, 즐겨찾기, 스크랩": [
        "좋아요", "즐겨찾기", "스크랩", "북마크", "찜", "관심",
        "like", "favorite", "favourite", "bookmark", "wishlist", "scrap",
    ],
    "알림, 상태 확인": [
        "알림", "주문 상태", "배송 조회", "배송조회", "진행 상황", "진행상황", "처리 현황",
        "notification", "notify",
    ],
    # ── 목록표 외 추가 기능 ──
    "필터, 조회": ["필터", "조회", "정렬", "초기화", "만 보기", "filter", "sort", "reset"],
    "지도 위치": ["지도", "위치", "오시는 길", "약도", "map"],
    "차트, 통계": ["차트", "그래프", "통계", "chart", "graph", "stats", "statistics"],
    "탭 전환": ["탭", "tab", "tabs"],
    "화면 크기 조정": ["확대", "축소", "글자 크기", "전체화면", "전체 화면", "zoom", "fullscreen"],
    "이용 안내, 도움말": ["가이드", "도움말", "이용 안내", "이용안내", "help", "guide", "faq"],
    "공유": ["공유", "share"],
    "인쇄": ["인쇄", "print"],
    "비교": ["비교", "compare"],
    "계산": ["계산", "calculate", "calculator"],
}

# '분류 안 된 버튼' 목록에서 제외할 단순 조작 버튼
IGNORE_LABELS = {
    "확인", "취소", "닫기", "이전", "다음", "더보기", "더 보기", "홈", "메뉴", "목록", "top", "맨위로",
    "ok", "cancel", "close", "prev", "previous", "next", "more", "home", "menu", "back",
}

# 버튼 글자 끝에서 떼어낼 말 (관심상품 확인하기 → 관심상품)
LABEL_SUFFIXES = ["바로가기", "확인하기", "하기", "보기", "가기"]


# ──────────────────────────────────────────────
# 1) 평가표 → 점수 변환 (평가 기준 이미지 그대로)
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
# 2) 페이지 수, 최대 Depth 세기
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
            depth = 1
            parent = lst.parent
            while parent is not None and parent is not root:
                if parent.name in ("ul", "ol"):
                    depth += 1
                parent = parent.parent
            max_depth = max(max_depth, depth)
    return max_depth


# ──────────────────────────────────────────────
# 3) 기능 찾기
# ──────────────────────────────────────────────
def expand_template(text, sep=" "):
    """
    자바스크립트 템플릿 안의 ${...} 부분에서 글자만 남긴다.
      '${auto ? "자동 수집 정지" : "자동 수집 시작"}' → '자동 수집 정지 자동 수집 시작'
      '${p[1]}' → '' (화면에 보일 글자가 없으면 지움)
    """
    def keep_strings(match):
        strings = re.findall(r'"([^"]*)"|\'([^\']*)\'', match.group(0))
        return " " + sep.join(a or b for a, b in strings) + " "
    return re.sub(r"\$\{[^{}]*\}", keep_strings, text)


def normalize(text):
    """비교하기 쉽게 정리: btnLogin → btn login, login_btn → login btn, 소문자로"""
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = re.sub(r"[_\-./]", " ", text)
    return re.sub(r"\s+", " ", text).lower().strip()


def has_keyword(text, keyword):
    """한글은 포함 여부, 영어는 단어 단위로 비교한다."""
    if keyword.isascii():
        return re.search(r"\b" + re.escape(keyword) + r"\b", text) is not None
    return keyword in text


def match_functions(text):
    """
    텍스트에 해당하는 기능과 그 근거 단어를 돌려준다.
      예) {"로그인, 로그아웃": ["로그인", "login"], "검색": ["search"]}
    """
    result = {}
    for name, keywords in FUNCTION_KEYWORDS.items():
        hits = [kw for kw in keywords if has_keyword(text, kw)]
        if hits:
            result[name] = hits
    return result


def collect_clue_text(soup):
    """
    기능을 짐작할 수 있는 '단서'만 모은다.
      - 제목, 메뉴, 버튼, 링크, 라벨 등의 글자
      - id, class, name, placeholder 같은 속성값
    본문 문단(<p>) 전체는 일부러 제외한다. (설명 문장 때문에 잘못 잡히는 것 방지)
    """
    clues = []
    text_tags = ["title", "h1", "h2", "h3", "h4", "h5", "h6",
                 "nav", "a", "button", "label", "legend", "option", "th", "summary"]
    for tag in soup.find_all(text_tags):
        clues.append(tag.get_text(" ", strip=True))

    attrs = ["id", "class", "name", "placeholder", "aria-label",
             "title", "value", "alt", "action", "href", "for"]
    for tag in soup.find_all(True):
        for attr in attrs:
            value = tag.get(attr)
            if isinstance(value, list):
                value = " ".join(value)
            if value:
                clues.append(value)
    return normalize(expand_template(" ".join(clues)))


def is_button_like(tag):
    """버튼처럼 동작하는 요소인지 판단한다."""
    if tag.name == "button":
        return True
    if tag.name == "input" and tag.get("type", "").lower() in ("button", "submit"):
        return True
    if tag.has_attr("onclick"):
        return True
    if tag.name == "a" and tag.get("href", "").strip().lower().startswith("javascript:"):
        return True
    return tag.get("role") in ("button", "tab")


def clean_label(label):
    """
    버튼 글자를 짧고 깔끔하게 정리한다.
      '관심상품만 보기 (0)' → '관심상품만'
      '이용 가이드 보기 ↗'  → '이용 가이드'
    """
    label = expand_template(label, sep=" / ")
    label = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", label)   # (0), [NEW] 같은 괄호 내용 제거
    label = re.sub(r"[^\w\s·/]", " ", label)              # ↗, 💬, ★ 같은 기호·이모지 제거
    label = re.sub(r"\s+", " ", label).strip()
    for suffix in LABEL_SUFFIXES:                        # '~하기', '~보기' 등 제거
        if label.endswith(suffix) and len(label) > len(suffix):
            label = label[: -len(suffix)].strip()
            break
    return label


def find_unclassified_buttons(soups):
    """기능 사전에 걸리지 않은 버튼 글자 (사전 보완용 참고 자료)"""
    result = []
    for soup in soups:
        for tag in soup.find_all(is_button_like):
            raw = tag.get_text(" ", strip=True) or tag.get("value") or tag.get("aria-label") or ""
            label = clean_label(raw)
            if not label or label.lower() in IGNORE_LABELS or label.isdigit() or len(label) > 20:
                continue
            if match_functions(normalize(label)):
                continue
            if label not in result:
                result.append(label)
    return result


def detect_functions(soup, script_soup, css_text):
    """
    주요 기능을 찾는다.
    돌려주는 값
      found        : {기능명: [근거1, 근거2, ...]}  (기능 사전 순서대로)
      unclassified : [사전에 안 걸린 버튼 글자, ...]
    """
    soups = [soup, script_soup]
    found = {}
    for s in soups:
        for name, hits in match_functions(collect_clue_text(s)).items():
            for hit in hits:
                if hit not in found.setdefault(name, []):
                    found[name].append(hit)

    def add(name, evidence):
        if evidence not in found.setdefault(name, []):
            found[name].append(evidence)

    # 태그·CSS 자체로 확실히 알 수 있는 기능 보완
    for s in soups:
        if s.find("input", type=re.compile(r"^file$", re.I)):
            add("파일 업로드", '<input type="file">')
        if s.find("a", attrs={"download": True}):
            add("파일 다운로드", "<a download>")
        if s.find("input", type=re.compile(r"^search$", re.I)):
            add("검색", '<input type="search">')
        if s.find("select"):
            add("필터, 조회", "<select> 선택 상자")
    if re.search(r"@media[^{]*\b(max|min)-width", css_text):
        add("화면 크기 조정", "@media 반응형 CSS")

    order = list(FUNCTION_KEYWORDS)
    found = dict(sorted(found.items(), key=lambda item: order.index(item[0])))
    return found, find_unclassified_buttons(soups)


def format_functions(found):
    """functions 열: 기능명 목록"""
    if not found:
        return "(감지된 기능 없음)"
    return "\n".join(f"- {name}" for name in found)


def format_evidence(found, unclassified):
    """function_evidence 열: 기능별 근거 + 사전에 없는 버튼(참고)"""
    lines = [f"- {name}: {', '.join(hits)}" for name, hits in found.items()]
    if unclassified:
        lines.append("- (참고) 분류 안 된 버튼: " + ", ".join(unclassified))
    return "\n".join(lines) if lines else "(근거 없음)"


# ──────────────────────────────────────────────
# 4) 파일 하나 평가하기
# ──────────────────────────────────────────────
def evaluate_file(filepath):
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        html = f.read()
    soup = BeautifulSoup(html, "html.parser")

    # <script> 안에서 만들어지는 화면(HTML 문자열)도 따로 읽는다.
    script_text = " ".join(s.get_text() for s in soup.find_all("script") if not s.get("src"))
    script_soup = BeautifulSoup(script_text, "html.parser")
    css_text = " ".join(s.get_text() for s in soup.find_all("style"))

    found, unclassified = detect_functions(soup, script_soup, css_text)
    features = len(found)

    pages = count_pages(soup)
    depth = count_max_depth(soup)

    p_score = score_pages(pages)
    d_score = score_depth(depth)
    f_score = score_features(features)
    total = p_score + d_score + f_score
    grade = total_to_grade(total)

    grade_memo = (
        f"페이지 수 {pages}개({p_score}점) / "
        f"최대 Depth {depth}단계({d_score}점) / "
        f"기능 수 {features}개({f_score}점) "
        f"→ 합산 {total}점 = {grade}"
    )
    return grade, grade_memo, format_functions(found), format_evidence(found, unclassified)


# ──────────────────────────────────────────────
# 5) 폴더의 파일 목록 가져오기 (1_, 2_, 10_ 순서로 정렬)
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

    # 2~4. 파일을 하나씩 평가해서 결과 모으기
    rows = []
    for no, filename in enumerate(html_files, start=1):
        filepath = os.path.join(HTML_FOLDER, filename)
        try:
            grade, grade_memo, functions, evidence = evaluate_file(filepath)
        except Exception as e:          # 파일 하나가 깨져도 나머지는 계속 진행
            grade, grade_memo, functions, evidence = "오류", f"파일 처리 실패: {e}", "", ""

        rows.append({
            "no": no,
            "filename": filename,
            "grade": grade,
            "grade_memo": grade_memo,
            "functions": functions,
            "function_evidence": evidence,
        })
        print(f"[{no}] {filename} → {grade}  ({grade_memo})")
        print("    " + functions.replace("\n", "\n    "))

    # 5. CSV 저장 (utf-8-sig: 엑셀에서 열어도 한글이 깨지지 않음)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f, fieldnames=["no", "filename", "grade", "grade_memo", "functions", "function_evidence"]
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n완료! 결과가 '{OUTPUT_CSV}'에 저장되었습니다.")