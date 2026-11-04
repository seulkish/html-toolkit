import os
import csv
import re
import json
from datetime import datetime
from bs4 import BeautifulSoup

# (선택) tree-sitter: 실제 JavaScript 문법 파서
#   pip install tree-sitter tree-sitter-javascript
# 설치되어 있지 않으면 자체 토크나이저(문자열·주석·정규식 제외 괄호 검사)로 대체합니다.
try:
    from tree_sitter import Language, Parser # type: ignore
    import tree_sitter_javascript as tsjs # type: ignore
    _JS_PARSER = Parser(Language(tsjs.language()))
except Exception:
    _JS_PARSER = None

# 점검할 HTML 파일들이 모여있는 폴더 경로
TARGET_DIR = "./html_edit"
OUTPUT_DIR = "./results"

# JS로 실행되는 <script> type 값 (그 외 text/template 등은 JS 검사 제외)
JS_SCRIPT_TYPES = {
    "", "text/javascript", "application/javascript", "module",
    "text/ecmascript", "application/ecmascript",
}
JSON_SCRIPT_TYPES = {"application/json", "application/ld+json", "importmap"}


# ===================================================================
# 1. JavaScript 토크나이저 (주석 제거 + 괄호 짝 검사)
#    문자열 / 템플릿 리터럴 / 정규식 / 주석 안의 괄호는 세지 않습니다.
# ===================================================================
_PAIRS = {")": "(", "]": "[", "}": "{"}
_REGEX_PREFIX_KEYWORDS = {
    "return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
    "throw", "case", "do", "else", "yield", "await",
}
_REGEX_PREFIX_CHARS = set("(,=:[!&|?{};+-*%<>~^}")


def scan_js(code, line_offset=0):
    """
    반환: (주석을 공백으로 바꾼 코드, [(줄번호, 메시지), ...])
    line_offset: 보고할 줄번호에 더할 값 (HTML 안 인라인 스크립트 위치 보정용)
    주석을 공백으로 치환하므로 줄번호·위치는 원본과 동일하게 유지됩니다.
    """
    out = []
    stack = []          # (여는 괄호, 위치)
    errors = []
    n = len(code)
    i = 0
    prev = ""           # 직전 유의미 토큰 (정규식 '/'와 나눗셈 '/' 구분용)

    def line_of(pos):
        return code.count("\n", 0, pos) + 1 + line_offset

    def read_template(j):
        """템플릿 리터럴 본문을 읽고 (다음 위치, 'end'|'expr'|'eof') 반환"""
        while j < n:
            ch = code[j]
            if ch == "\\":
                j += 2
                continue
            if ch == "`":
                return j + 1, "end"
            if ch == "$" and j + 1 < n and code[j + 1] == "{":
                return j + 2, "expr"
            j += 1
        return n, "eof"

    while i < n:
        c = code[i]
        nxt = code[i + 1] if i + 1 < n else ""

        # 한 줄 주석 (// 및 구형 <!-- 표기)
        if (c == "/" and nxt == "/") or code.startswith("<!--", i):
            j = code.find("\n", i)
            j = n if j == -1 else j
            out.append(" " * (j - i))
            i = j
            continue

        # 블록 주석
        if c == "/" and nxt == "*":
            j = code.find("*/", i + 2)
            if j == -1:
                errors.append((line_of(i), "닫히지 않은 블록 주석 /* */"))
                j = n
            else:
                j += 2
            out.append(re.sub(r"[^\n]", " ", code[i:j]))
            i = j
            continue

        # 일반 문자열 '...' / "..."
        if c in "'\"":
            j = i + 1
            while j < n and code[j] != c and code[j] != "\n":
                j += 2 if code[j] == "\\" else 1
            if j < n and code[j] == c:
                out.append(code[i:j + 1])
                i = j + 1
            else:
                errors.append((line_of(i), f"닫히지 않은 문자열 {c}"))
                out.append(code[i:j])
                i = j
            prev = "str"
            continue

        # 템플릿 리터럴 `...${...}...`
        if c == "`":
            j, kind = read_template(i + 1)
            out.append(code[i:j])
            if kind == "eof":
                errors.append((line_of(i), "닫히지 않은 템플릿 문자열 `"))
            elif kind == "expr":
                stack.append(("${", j - 2))
            prev = "str" if kind == "end" else "{"
            i = j
            continue

        # 닫는 괄호
        if c in ")]}":
            # 템플릿 표현식 ${ ... } 의 끝이면 템플릿 본문으로 복귀
            if c == "}" and stack and stack[-1][0] == "${":
                stack.pop()
                j, kind = read_template(i + 1)
                out.append(code[i:j])
                if kind == "eof":
                    errors.append((line_of(i), "닫히지 않은 템플릿 문자열 `"))
                elif kind == "expr":
                    stack.append(("${", j - 2))
                prev = "str" if kind == "end" else "{"
                i = j
                continue
            if not stack:
                errors.append((line_of(i), f"여는 괄호 없이 닫는 괄호 '{c}' 등장"))
            elif stack[-1][0] != _PAIRS[c]:
                op, pos = stack.pop()
                errors.append((line_of(i),
                               f"괄호 짝 불일치: {line_of(pos)}행의 '{op}'가 '{c}'로 닫힘"))
            else:
                stack.pop()
            out.append(c)
            prev = c
            i += 1
            continue

        # 여는 괄호
        if c in "([{":
            stack.append((c, i))
            out.append(c)
            prev = c
            i += 1
            continue

        # 정규식 리터럴 /.../flags
        if c == "/" and (prev == "" or prev in _REGEX_PREFIX_CHARS
                         or prev in _REGEX_PREFIX_KEYWORDS):
            j = i + 1
            in_class = False
            while j < n and code[j] != "\n":
                ch = code[j]
                if ch == "\\":
                    j += 2
                    continue
                if in_class:
                    if ch == "]":
                        in_class = False
                elif ch == "[":
                    in_class = True
                elif ch == "/":
                    break
                j += 1
            if j < n and code[j] == "/":
                j += 1
                while j < n and code[j].isalpha():
                    j += 1
                out.append(code[i:j])
                prev = "id"
                i = j
                continue
            # 정규식으로 닫히지 않으면 나눗셈으로 간주 (오탐 방지)

        # 식별자 / 키워드 / 숫자
        m = re.match(r"[A-Za-z_$][\w$]*|\d[\w.]*", code[i:i + 200])
        if m:
            word = m.group(0)
            prev = word if word in _REGEX_PREFIX_KEYWORDS else "id"
            out.append(word)
            i += len(word)
            continue

        if not c.isspace():
            prev = c
        out.append(c)
        i += 1

    for op, pos in stack:
        if op == "${":
            errors.append((line_of(pos), "닫히지 않은 템플릿 표현식 '${'"))
        else:
            errors.append((line_of(pos), f"닫히지 않은 괄호 '{op}'"))

    return "".join(out), errors


def strip_js_comments(code):
    return scan_js(code)[0]


def check_js_syntax(code, line_offset=0):
    """
    반환: (검사 방식, [(줄번호, 메시지), ...])
    tree-sitter가 있으면 실제 문법 파서로, 없으면 토크나이저로 검사합니다.
    """
    if _JS_PARSER is not None:
        raw = code.encode("utf-8")
        root = _JS_PARSER.parse(raw).root_node
        if not root.has_error:
            return "파서", []
        errs = []
        stack = [root]
        while stack and len(errs) < 5:
            node = stack.pop()
            if node.is_missing:
                errs.append((node.start_point[0] + 1 + line_offset, f"'{node.type}' 누락"))
                continue
            if node.type == "ERROR":
                snippet = raw[node.start_byte:node.end_byte].decode("utf-8", "replace")
                snippet = " ".join(snippet.split())[:30]
                errs.append((node.start_point[0] + 1 + line_offset, f"해석할 수 없는 구문: '{snippet}'"))
                continue
            if node.has_error:
                stack.extend(reversed(node.children))
        return "파서", errs
    return "토크나이저", scan_js(code, line_offset)[1]


# ===================================================================
# 2. 이벤트 바인딩 정적 분석 (addEventListener / onclick= / jQuery .on 등)
# ===================================================================
_SEL = r"""(?P<q>['"`])(?P<sel>(?:(?!(?P=q)).)*?)(?P=q)"""

# 요소를 가져오는 호출: getElementById('x'), querySelector('.a'), $('#b') ...
GETTER_RE = re.compile(
    r"(?P<fn>getElementById|querySelectorAll|querySelector|getElementsByClassName"
    r"|getElementsByTagName|getElementsByName|(?<![\w$])\$|(?<![\w$])jQuery)"
    r"\s*\(\s*" + _SEL + r"\s*\)"
)
# fn -> (셀렉터 종류, 단일 요소 반환 여부: 없으면 null 이 되는 호출인가)
GETTER_KIND = {
    "getElementById": ("id", True),
    "querySelector": ("css", True),
    "querySelectorAll": ("css", False),
    "getElementsByClassName": ("class", False),
    "getElementsByTagName": ("tag", False),
    "getElementsByName": ("name", False),
    "$": ("css", False),
    "jQuery": ("css", False),
}

# 요소 바로 뒤에 붙는 이벤트 연결
_BIND = (
    r"\s*(?:\[\s*\d+\s*\]\s*)?(?P<acc>\?\.|\.)\s*"
    r"(?:addEventListener\s*\(|on[a-z]+\s*=(?!=)"
    r"|(?:on|one|bind|click|dblclick|submit|change|input|keyup|keydown|hover)\s*\(\s*(?!\)))"
)
BIND_AFTER_RE = re.compile(_BIND)
FOREACH_AFTER_RE = re.compile(r"\s*\.\s*forEach\s*\(")
BIND_ANYWHERE_RE = re.compile(r"addEventListener\s*\(|\.\s*on[a-z]+\s*=(?!=)")
ASSIGN_BEFORE_RE = re.compile(r"([A-Za-z_$][\w$]*)\s*=\s*(?:[\w$.]*\.)?\s*$")

# 이벤트 위임: e.target.matches('.btn'), closest('#x'), classList.contains('btn'), target.id === 'x'
DELEG_CSS_RE = re.compile(r"\.\s*(?:matches|closest)\s*\(\s*" + _SEL)
DELEG_CLASS_RE = re.compile(r"classList\s*\.\s*contains\s*\(\s*" + _SEL)
DELEG_ID_RE = re.compile(r"\.\s*id\s*===?\s*" + _SEL)
JQ_DELEG_RE = re.compile(r"""\.\s*on\s*\(\s*(['"`])[^'"`]*\1\s*,\s*""" + _SEL)


def _paren_region(code, open_idx):
    depth = 0
    for k in range(open_idx, len(code)):
        if code[k] == "(":
            depth += 1
        elif code[k] == ")":
            depth -= 1
            if depth == 0:
                return code[open_idx:k + 1]
    return code[open_idx:]


def _var_is_bound(code, var):
    """변수(또는 컬렉션 변수)에 이벤트가 연결되는지 확인"""
    v = re.escape(var)
    head = r"(?<![\w$.])" + v
    # btn.addEventListener(...), btn.onclick = ..., $btn.on(...)
    m = re.search(head + _BIND, code)
    if m:
        return True, m.group("acc") == "?."
    # btns.forEach(b => b.addEventListener(...)) / Array.from(btns).forEach / [...btns].forEach
    for pat in (head + r"\s*\.\s*forEach\s*\(",
                r"Array\s*\.\s*from\s*\(\s*" + v + r"\s*\)\s*\.\s*forEach\s*\(",
                r"\[\s*\.\.\.\s*" + v + r"\s*\]\s*\.\s*forEach\s*\("):
        for fm in re.finditer(pat, code):
            if BIND_ANYWHERE_RE.search(_paren_region(code, fm.end() - 1)):
                return True, False
    # for (const b of btns) { b.addEventListener(...) }
    for fm in re.finditer(r"for\s*\(\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s+of\s+"
                          + v + r"\s*\)", code):
        loop_var = re.escape(fm.group(1))
        if re.search(r"(?<![\w$.])" + loop_var + _BIND, code[fm.end():]):
            return True, False
    return False, False


def extract_bindings(code):
    """
    JS 코드(주석 제거본)에서 이벤트가 연결된 셀렉터 목록을 추출합니다.
    반환: [{kind, value, single, optional, delegated}, ...]
    """
    found = []

    for m in GETTER_RE.finditer(code):
        sel = m.group("sel").strip()
        if not sel or "${" in sel:
            continue
        kind, single = GETTER_KIND[m.group("fn")]
        rest = code[m.end():]

        # (a) 직접 체인: document.getElementById('x').addEventListener(...)
        bm = BIND_AFTER_RE.match(rest)
        if bm:
            found.append(dict(kind=kind, value=sel, single=single,
                              optional=bm.group("acc") == "?.", delegated=False))
            continue

        # (b) 체인 forEach: document.querySelectorAll('.b').forEach(b => b.addEventListener(...))
        fm = FOREACH_AFTER_RE.match(rest)
        if fm:
            region = _paren_region(code, m.end() + fm.end() - 1)
            if BIND_ANYWHERE_RE.search(region):
                found.append(dict(kind=kind, value=sel, single=False,
                                  optional=False, delegated=False))
            continue

        # (c) 변수 경유: const btn = document.getElementById('x'); btn.addEventListener(...)
        am = ASSIGN_BEFORE_RE.search(code[max(0, m.start() - 120):m.start()])
        if am:
            bound, optional = _var_is_bound(code, am.group(1))
            if bound:
                found.append(dict(kind=kind, value=sel, single=single,
                                  optional=optional, delegated=False))

    # (d) 이벤트 위임
    if BIND_ANYWHERE_RE.search(code) or ".on(" in code.replace(" ", ""):
        for rx, kind in ((DELEG_CSS_RE, "css"), (DELEG_CLASS_RE, "class"),
                         (DELEG_ID_RE, "id"), (JQ_DELEG_RE, "css")):
            for m in rx.finditer(code):
                sel = m.group("sel").strip()
                if sel and "${" not in sel:
                    found.append(dict(kind=kind, value=sel, single=False,
                                      optional=True, delegated=True))
    return found


def resolve_selector(soup, kind, value):
    """셀렉터에 해당하는 요소 목록. 해석할 수 없는 셀렉터(jQuery 전용 등)는 None"""
    try:
        if kind == "id":
            return soup.find_all(id=value)
        if kind == "class":
            classes = value.split()
            return [t for t in soup.find_all(class_=True)
                    if all(c in t.get("class", []) for c in classes)]
        if kind == "tag":
            return soup.find_all(value.lower())
        if kind == "name":
            return soup.find_all(attrs={"name": value})
        if kind == "css":
            return soup.select(value)
    except Exception:
        return None
    return None


def describe_binding(b):
    label = {"id": "getElementById", "class": "getElementsByClassName",
             "tag": "getElementsByTagName", "name": "getElementsByName",
             "css": "querySelector"}[b["kind"]]
    return f"{label}('{b['value']}')"


# ===================================================================
# 3. 파일 읽기 / 외부 스크립트
# ===================================================================
def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(path, "r", encoding="cp949") as f:
            return f.read()


def local_script_path(html_path, src):
    """로컬 스크립트 경로로 변환. 외부 URL이면 None"""
    src = src.strip()
    if re.match(r"^(?:[a-z][a-z0-9+.-]*:|//)", src, re.I):
        return None
    src = re.split(r"[?#]", src)[0]
    base = os.path.dirname(os.path.abspath(html_path))
    return os.path.normpath(os.path.join(base, src.lstrip("/") if src.startswith("/") else src))


# ===================================================================
# 4. HTML 점검
# ===================================================================
def check_html_issues(file_path, ext_cache):
    issues = []
    file_name = os.path.basename(file_path)

    try:
        content = read_text(file_path)
    except UnicodeDecodeError as e:
        return [(file_name, "오류", f"인코딩 오류로 파일 읽기 실패: {str(e)}")]
    except Exception as e:
        return [(file_name, "오류", f"파일 열기 실패: {str(e)}")]

    # 1. 빈 파일 확인
    if not content.strip():
        return [(file_name, "오류", "파일 내용이 완전히 비어 있음")]

    soup = BeautifulSoup(content, "html.parser")

    # 2. 필수 뼈대 태그 누락 점검
    if not soup.find("body"):
        issues.append((file_name, "경고", "<body> 태그가 존재하지 않음"))

    # 3. 중복 ID 검사 (동작 오류, DOM 조작 충돌 유발)
    seen_ids = set()
    for tag in soup.find_all(id=True):
        tag_id = tag.get("id")
        if tag_id in seen_ids:
            issues.append((file_name, "오류", f"중복된 id 속성 발견: '{tag_id}'"))
        else:
            seen_ids.add(tag_id)

    # 4. 이미지 태그 src 누락 또는 공백 검사 (이미지 깨짐)
    for img in soup.find_all("img"):
        src = img.get("src")
        if not src or src.strip() == "":
            img_snippet = str(img)[:60]
            issues.append((file_name, "경고", f"src 속성 누락/공백 <img>: {img_snippet}"))

    # 5. 외부 리소스(스크립트/스타일) src, href 공백 점검
    for script in soup.find_all("script", src=True):
        if not script.get("src", "").strip():
            issues.append((file_name, "오류", "src가 비어있는 <script> 태그 존재"))

    for link in soup.find_all("link", rel=lambda x: x and "stylesheet" in x):
        if not link.get("href", "").strip():
            issues.append((file_name, "오류", "href가 비어있는 CSS <link> 태그 존재"))

    # 6. 하이퍼링크 href 점검 (링크 비어있거나 미완성)
    for a in soup.find_all("a"):
        href = a.get("href")
        if href is None or href.strip() == "":
            text = a.get_text(strip=True)[:20]
            issues.append((file_name, "주의", f"href 비어있는 <a> 태그 (텍스트: '{text}')"))

    # ---------------------------------------------------------------
    # 7. 스크립트 수집 + 문법 검사 (괄호 개수 비교 대신 파서/토크나이저 사용)
    # ---------------------------------------------------------------
    js_sources = []   # (코드, 인라인 여부)

    for script in soup.find_all("script"):
        stype = (script.get("type") or "").strip().lower()
        src = script.get("src")

        if src and src.strip():
            path = local_script_path(file_path, src)
            if path is None:
                continue  # CDN 등 외부 URL은 정적 분석 대상 아님
            if path not in ext_cache:
                if not os.path.isfile(path):
                    ext_cache[path] = None
                else:
                    try:
                        code = read_text(path)
                        ext_cache[path] = {"code": code, "reported": False}
                    except Exception:
                        ext_cache[path] = None
            entry = ext_cache[path]
            if entry is None:
                issues.append((file_name, "경고", f"로컬 스크립트 파일을 찾을 수 없음: {src}"))
                continue
            js_sources.append((entry["code"], False))
            # 공용 JS 파일의 문법 오류는 최초 1회만 보고
            if not entry["reported"]:
                entry["reported"] = True
                method, errs = check_js_syntax(entry["code"])
                for line, msg in errs:
                    issues.append((file_name, "오류",
                                   f"[{method}] 외부 스크립트 {src} {line}행: {msg}"))
            continue

        code = script.get_text()
        if not code.strip():
            continue

        # JSON 계열 스크립트는 JSON 문법으로 검사
        if stype in JSON_SCRIPT_TYPES:
            try:
                json.loads(code)
            except json.JSONDecodeError as e:
                issues.append((file_name, "오류",
                               f"<script type='{stype}'> JSON 문법 오류: {e.msg} (블록 내 {e.lineno}행)"))
            continue

        # 템플릿 등 JS가 아닌 스크립트는 건너뜀 (기존 오탐 원인)
        if stype not in JS_SCRIPT_TYPES:
            continue

        js_sources.append((code, True))
        base_line = getattr(script, "sourceline", None)
        method, errs = check_js_syntax(code, (base_line - 1) if base_line else 0)
        prefix = "HTML " if base_line else "스크립트 내 "
        for line, msg in errs:
            issues.append((file_name, "오류",
                           f"[{method}] 인라인 스크립트 문법 오류 ({prefix}{line}행 부근): {msg}"))

    # ---------------------------------------------------------------
    # 8. 이벤트 바인딩 분석 (addEventListener 등을 코드만 보고 판별)
    # ---------------------------------------------------------------
    bound = set()           # 이벤트가 연결된 요소의 id(객체)
    reported_missing = set()
    for code, is_inline in js_sources:
        clean = strip_js_comments(code)   # 주석 처리된 addEventListener는 무시
        for b in extract_bindings(clean):
            elems = resolve_selector(soup, b["kind"], b["value"])
            if elems:
                bound.update(id(e) for e in elems)
                continue
            # 대상 요소 없음: getElementById/querySelector 직접 연결은 null 참조 오류 위험
            # (공용 외부 JS, 위임, ?. 사용, 컬렉션 반환 호출은 보고하지 않음)
            if (elems is not None and is_inline and b["single"]
                    and not b["optional"] and not b["delegated"]):
                key = describe_binding(b)
                if key not in reported_missing:
                    reported_missing.add(key)
                    issues.append((file_name, "경고",
                                   f"이벤트 연결 대상 요소를 HTML에서 찾을 수 없음: {key} "
                                   f"(동적 생성 요소가 아니라면 null.addEventListener 오류 가능)"))

    def is_js_bound(tag):
        # 자신 또는 조상 요소에 리스너가 있으면 이벤트 버블링으로 동작 가능
        if id(tag) in bound:
            return True
        return any(id(p) in bound for p in tag.parents)

    def has_inline_handler(tag):
        return any(attr.lower().startswith("on") for attr in tag.attrs)

    # 9. 버튼 및 폼 전송 결함 점검
    for form in soup.find_all("form"):
        if (not form.get("action") and not form.get("onsubmit")
                and id(form) not in bound):
            issues.append((file_name, "주의",
                           "action·onsubmit·submit 리스너가 모두 없는 <form> 태그 (전송 대상 불명)"))

    for btn in soup.find_all("button"):
        btype = (btn.get("type") or "submit").strip().lower()
        in_form = btn.find_parent("form") is not None or bool(btn.get("form"))

        if has_inline_handler(btn):
            continue
        if btype in ("submit", "reset") and in_form:
            continue
        if is_js_bound(btn):
            continue

        btn_text = btn.get_text(strip=True)
        btn_id = btn.get("id", "")
        btn_class = " ".join(btn.get("class", []))

        details = []
        if btn_text:
            details.append(f"버튼명: '{btn_text}'")
        if btn_id:
            details.append(f"id: '{btn_id}'")
        if btn_class:
            details.append(f"class: '{btn_class}'")
        detail_str = ", ".join(details) if details else f"코드: {str(btn)[:50]}"
        issues.append((file_name, "주의",
                       f"동작 연결 없는 <button> (onclick·addEventListener·form 전송 모두 없음, {detail_str})"))

    # 문제가 없을 경우 정상 기록
    if not issues:
        issues.append((file_name, "정상", "기능적 결함 없음"))

    return issues


def main():
    if not os.path.exists(TARGET_DIR):
        print(f"디렉토리가 존재하지 않습니다: {TARGET_DIR}")
        return

    # results 폴더가 없으면 자동 생성
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    all_results = []
    ext_cache = {}   # 외부 JS 파일 캐시 (여러 HTML이 같은 파일을 쓰는 경우)

    # 디렉토리 내 모든 html 파일 수집
    html_files = [f for f in os.listdir(TARGET_DIR) if f.lower().endswith((".html", ".htm"))]
    print(f"총 {len(html_files)}개의 HTML 파일을 검사합니다.")
    print("JS 문법 검사 방식: " + ("tree-sitter 파서" if _JS_PARSER else
                                "토크나이저 (tree-sitter 미설치)"))

    for file_name in sorted(html_files):
        full_path = os.path.join(TARGET_DIR, file_name)
        all_results.extend(check_html_issues(full_path, ext_cache))

    # 파일명 형식: result_{YYMMDD}_{HHMMSS}.csv (실행 시점 기준)
    now = datetime.now()
    current_date = now.strftime("%y%m%d")
    current_time = now.strftime("%H%M%S")
    output_filename = os.path.join(OUTPUT_DIR, f"result_{current_date}_{current_time}.csv")

    # CSV 파일 작성
    with open(output_filename, "w", newline="", encoding="utf-8-sig") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["파일명", "구분", "내용"])
        writer.writerows(all_results)

    print(f"검사 완료! 결과 파일이 생성되었습니다: {output_filename}")


if __name__ == "__main__":
    main()