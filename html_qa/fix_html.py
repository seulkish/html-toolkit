#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTML 점검 결과(테스트 리포트)에 나온 문제를 자동으로 수정하는 프로그램.

처리하는 항목
  1) action / onsubmit / submit 리스너가 없는 <form>   -> onsubmit="return false;" 추가
  2) 동작 연결이 없는 <button>                         -> type="button" 추가 (동작 자체는 수동 확인 대상으로 기록)
  3) <body> 태그가 없는 문서                           -> <body> ... </body> 삽입
  4) HTML에 없는 id를 getElementById(...).addEventListener  -> ?. (옵셔널 체이닝)으로 null 오류 방지

저장 규칙
  - 원본은 그대로 두고, 복사본을 ./html_edit/ 에 저장 (폴더가 없으면 자동 생성)
    수정할 내용이 없는 파일도 그대로 복사됨
  - 파일명 끝에 _v2 를 붙이고, 이미 있으면 _v3, _v4 ... 로 증가
    (원본 이름이 이미 _v2 로 끝나면 _v3 부터 시작)
  - 수정 내역은 ./results/result_YYMMDD_HHMMSS.csv 로 저장
    열: 파일명 / 구분(수정 완료·수정 불가) / 내용(수정한 위치 또는 못 고친 위치, 원본 기준 줄 번호)

사용법
  python fix_html.py --report result_261030_190151.csv   # 파일명만 써도 results 폴더에서 찾음
  python fix_html.py --report 점검결과.xlsx          # 리포트의 [파일명] 열에 있는 파일만 처리
  python fix_html.py --report 점검결과.csv --src html
  python fix_html.py                                # 리포트 없이 html 폴더의 모든 HTML 처리

  --src    HTML 파일이 있는 폴더 (기본: html)
  --actions 버튼 동작표 (.csv/.xlsx, 열: 파일명 / 버튼id / 버튼명 / 동작코드)
  --report 점검 결과표 (.xlsx 또는 .csv, 열 이름: 파일명 / 구분 / 내용)
           [구분]이 "정상"인 행은 건너뜀 (그 파일의 모든 행이 정상이면 복사·수정 안 함)
"""

import argparse
import csv
import io
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:  # tqdm 미설치 시에도 동작하도록 최소 대체 클래스 사용
    print("[안내] 진행률 표시를 쓰려면 'pip install tqdm' 을 실행하세요.")

    class tqdm:  # noqa: N801
        def __init__(self, total=None, desc="", **kw):
            self.total, self.n = total, 0

        def update(self, n=1):
            self.n += n

        def reset(self, total=None):
            self.n = 0
            self.total = total if total is not None else self.total

        def set_description(self, desc=""):
            pass

        def close(self):
            pass

        @staticmethod
        def write(msg):
            print(msg)

OUT_DIR_NAME = "html_edit"
RESULT_DIR_NAME = "results"

# 입력으로 쓸 점검 결과 파일명을 여기에 적어 두면 매번 옵션을 안 써도 됩니다.
# (비워 두면 --report 옵션 또는 실행 중 입력창을 사용)  예: "result_261030_190151.csv"
REPORT_FILE = ""

# 리포트의 [구분] 값이 이 값이면 그 행은 수정 대상에서 제외 (파일의 모든 행이 이 값이면 파일 자체를 건너뜀)
SKIP_STATUS = "정상"

# 동작표(csv/xlsx) 파일명. 비워 두면 --actions 옵션 사용. 열: 파일명 / 버튼id / 버튼명 / 동작코드
ACTIONS_FILE = ""

# 모달 안의 '확인' 계열 버튼에 연결할 함수를 못 찾았을 때, 최소 동작(모달 닫기)이라도 넣을지 여부
GUESS_CONFIRM_AS_CLOSE = True

SCRIPT_RE = re.compile(r"(<script\b[^>]*>)(.*?)(</script\s*>)", re.S | re.I)
STYLE_RE = re.compile(r"(<style\b[^>]*>)(.*?)(</style\s*>)", re.S | re.I)
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
SUBMIT_LISTENER_RE = re.compile(
    r"""addEventListener\(\s*['"]submit['"]|\.onsubmit\s*=|\.submit\s*\(|\bon\(\s*['"]submit['"]""",
    re.I,
)
GET_BY_ID_RE = re.compile(
    r"""getElementById\(\s*(['"])(?P<id>[^'"]+)\1\s*\)(?P<gap>\s*)(?P<dot>\.)\s*addEventListener"""
)
GET_BY_ID_ANY_RE = re.compile(r"""getElementById\(\s*(['"])(?P<id>[^'"]+)\1\s*\)""")


# ------------------------------------------------------------------ 입출력
def read_text(path: Path):
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    for enc in ("utf-8", "cp949"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("unknown", raw, 0, 1, "지원하지 않는 인코딩")


def write_text(path: Path, text: str, enc: str):
    with open(path, "w", encoding=enc, newline="") as f:
        f.write(text)


# ------------------------------------------------------------------ 분석 도구
def blank(m):
    return re.sub(r"[^\n]", " ", m.group(0))


def make_masked(text: str) -> str:
    """주석·script·style 내부를 공백으로 바꿔(길이 유지) 태그 탐색 시 오탐을 막는다."""
    t = COMMENT_RE.sub(blank, text)
    for rx in (SCRIPT_RE, STYLE_RE):
        t = rx.sub(lambda m: m.group(1) + re.sub(r"[^\n]", " ", m.group(2)) + m.group(3), t)
    return t


def has_attr(tag: str, name: str) -> bool:
    return re.search(rf"(?<![\w-]){name}\s*=", tag, re.I) is not None


def get_attr(tag: str, name: str):
    m = re.search(
        rf"""(?<![\w-]){name}\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", tag, re.I
    )
    if not m:
        return None
    return next(g for g in m.groups() if g is not None)


def tag_insert_pos(m) -> int:
    """여는 태그의 '>' (또는 '/>') 바로 앞 위치."""
    s = m.group(0)
    return m.end() - (2 if s.endswith("/>") else 1)


def script_blocks(text: str):
    """(본문 시작 위치, 본문) 목록."""
    return [(m.start(2), m.group(2)) for m in SCRIPT_RE.finditer(text)]


def id_referenced_in_js(js: str, el_id: str) -> bool:
    return re.search(r"""(?:["']|#)%s(?:["'\s).,:\[>]|$)""" % re.escape(el_id), js) is not None


def class_referenced_in_js(js: str, cls: str) -> bool:
    return re.search(r"""[.'"\s]%s(?![\w-])""" % re.escape(cls), js) is not None


# ------------------------------------------------------------------ 핵심 처리

# ------------------------------------------------------------------ 버튼 동작 추정
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
TAG_RE = re.compile(r"<(/?)([a-zA-Z][\w:-]*)([^>]*)>")
MODAL_RE = re.compile(r"modal|dialog|popup|pop-up|layer|overlay|lightbox", re.I)
CANCEL_RE = re.compile(r"취소|돌아가기|닫기|뒤로|아니[오요]|cancel|close|dismiss|back", re.I)
BACK_RE = re.compile(r"돌아가기|뒤로|back", re.I)
CONFIRM_TEXTS = {"예", "네", "확인", "저장", "완료", "동의", "승인", "적용", "ok", "yes"}
CONFIRM_RE = re.compile(r"confirm|accept|apply|submit|save|ok\b|yes|확인|저장|동의|승인", re.I)
VISIBLE_CLASSES = ("show", "open", "opened", "active", "is-open", "is-active", "visible", "is-visible", "shown", "on")
FUNC_PATTERNS = [
    r"function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)",
    r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?function\s*\(([^)]*)\)",
    r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>",
]


def button_ancestors(masked: str):
    """각 <button> 시작 위치 -> 조상 태그 목록 [(태그, 속성문자열), ...]"""
    stack, result = [], {}
    for m in TAG_RE.finditer(masked):
        closing, tag, attrs = m.group(1), m.group(2).lower(), m.group(3)
        if closing:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == tag:
                    del stack[i:]
                    break
            continue
        if tag == "button":
            result[m.start()] = list(stack)
        if tag in VOID_TAGS or attrs.rstrip().endswith("/"):
            continue
        stack.append((tag, attrs))
    return result


def find_modal(ancestors):
    """가장 바깥쪽의 모달 후보 조상을 (태그, id, 클래스목록)으로 반환. 없으면 None."""
    found = None
    for tag, attrs in ancestors:
        if tag in ("html", "body", "main"):
            continue
        el_id = get_attr(attrs, "id") or ""
        cls = (get_attr(attrs, "class") or "").split()
        role = (get_attr(attrs, "role") or "").lower()
        if tag == "dialog" or role in ("dialog", "alertdialog") or MODAL_RE.search(el_id) \
                or any(MODAL_RE.search(c) for c in cls):
            found = (tag, el_id, cls)
            break
    return found


def style_and_script_text(text: str) -> str:
    parts = [m.group(2) for m in STYLE_RE.finditer(text)] + [m.group(2) for m in SCRIPT_RE.finditer(text)]
    return "\n".join(parts)


def global_functions(text: str):
    """인자 없이 호출 가능한 전역 함수 이름 집합 (module 스크립트·중괄호 안 함수는 제외)."""
    funcs = set()
    for sm in SCRIPT_RE.finditer(text):
        if re.search(r"type\s*=\s*['\"]?module", sm.group(1), re.I):
            continue
        body = sm.group(2)
        for p in FUNC_PATTERNS:
            for m in re.finditer(p, body):
                if m.group(2).strip():
                    continue
                before = body[:m.start()]
                if before.count("{") - before.count("}") == 0:
                    funcs.add(m.group(1))
    return funcs


def find_function(funcs, el_id, kind):
    idl = (el_id or "").lower()
    if len(idl) >= 4:
        for n in sorted(funcs):
            if idl in n.lower():
                return n
    if kind == "cancel":
        for n in sorted(funcs):
            l = n.lower()
            if re.search(r"close|cancel|dismiss|hide", l) and re.search(r"modal|dialog|popup", l):
                return n
    if kind == "confirm":
        for n in sorted(funcs):
            if re.search(r"confirm|accept", n.lower()):
                return n
    return None


def modal_close_code(modal, css_js):
    tag, el_id, cls = modal
    if tag == "dialog":
        return "this.closest('dialog').close()", "dialog.close()"
    if el_id:
        sel = f"#{el_id}"
    else:
        c = next((c for c in cls if MODAL_RE.search(c)), None)
        if not c:
            return None
        sel = f".{c}"
    if "'" in sel or '"' in sel:
        return None
    get = f"var m=this.closest('{sel}');"
    for cand in VISIBLE_CLASSES:
        pat_js = rf"""classList\.(?:add|toggle)\(\s*['"]{re.escape(cand)}['"]"""
        pat_css = rf"(?:modal|dialog|popup|overlay|layer)[\w-]*\.{re.escape(cand)}(?![\w-])"
        if re.search(pat_js, css_js) or re.search(pat_css, css_js, re.I):
            return f"{get}if(m){{m.classList.remove('{cand}');}}", f"{sel}에서 '{cand}' 클래스 제거"
    if re.search(r"""\.hidden\s*=|removeAttribute\(\s*['"]hidden""", css_js):
        return f"{get}if(m){{m.hidden=true;}}", f"{sel} hidden 처리"
    return f"{get}if(m){{m.style.display='none';}}", f"{sel} display:none 처리"


def infer_button_action(file_name, name, el_id, classes, ancestors, funcs, css_js, actions):
    """(동작 코드, 근거) 또는 None"""
    for a in actions:
        if a["file"] and a["file"] != file_name:
            continue
        if (a["id"] and a["id"] == el_id) or (a["name"] and a["name"] == name):
            return a["code"], "사용자 동작표"

    idc = f"{el_id or ''} {' '.join(classes)}"
    if CANCEL_RE.search(name) or CANCEL_RE.search(idc):
        kind = "cancel"
    elif name.strip().lower() in CONFIRM_TEXTS or CONFIRM_RE.search(idc):
        kind = "confirm"
    else:
        kind = None

    modal = find_modal(ancestors)
    fn = find_function(funcs, el_id, kind)
    if fn:
        return f"{fn}()", f"기존 전역 함수 {fn}() 연결 - 추정"
    if kind == "cancel" and modal:
        res = modal_close_code(modal, css_js)
        if res:
            return res[0], f"취소 계열 버튼으로 판단해 모달 닫기({res[1]}) - 추정"
    if kind == "confirm" and modal and GUESS_CONFIRM_AS_CLOSE:
        res = modal_close_code(modal, css_js)
        if res:
            return res[0], f"확인 계열 버튼: 모달 닫기만 수행({res[1]}), 실제 처리 로직은 확인 필요 - 추정"
    if not modal and BACK_RE.search(name):
        return "history.back()", "이전 페이지로 이동 - 추정"
    return None


def process_html(text: str, on_step=None, actions=None, unresolved=None, file_name=""):
    """
    반환: (삽입 목록 [(위치, 문자열)], 내역 [(구분, 항목, 내용)])
    구분: '수정' 또는 '수동확인'
    """
    step = on_step or (lambda label: None)
    inserts = []
    rows = []

    masked = make_masked(text)

    def ln(pos):  # 원본 기준 줄 번호
        return text.count("\n", 0, pos) + 1

    blocks = script_blocks(text)
    js_all = "\n".join(b for _, b in blocks)

    # ---- 1) <form>
    form_spans = []
    for m in re.finditer(r"<form\b[^>]*>", masked, re.I):
        close = re.search(r"</form\s*>", masked[m.end():], re.I)
        end = m.end() + close.end() if close else len(masked)
        form_spans.append((m.start(), end))

    has_submit_listener = SUBMIT_LISTENER_RE.search(js_all) is not None
    for m in re.finditer(r"<form\b[^>]*>", masked, re.I):
        tag = text[m.start():m.end()]
        if has_attr(tag, "action") or has_attr(tag, "onsubmit"):
            continue
        label = get_attr(tag, "id") or get_attr(tag, "name") or "(id/name 없음)"
        if has_submit_listener:
            rows.append(("수동확인", "form 전송 처리",
                         f"{ln(m.start())}행 <form> {label}: 스크립트에 submit 처리 코드가 있어 자동 수정 생략"))
            continue
        inserts.append((tag_insert_pos(m), ' onsubmit="return false;"'))
        rows.append(("수정", "form 전송 처리",
                     f'{ln(m.start())}행 <form> {label}: onsubmit="return false;" 추가 (전송 동작이 필요하면 action 또는 submit 핸들러를 직접 연결)'))

    step("form 검사")

    # ---- 2) <button>
    actions = actions or []
    anc_map = button_ancestors(masked)
    funcs = global_functions(text)
    css_js = style_and_script_text(text)
    for m in re.finditer(r"<button\b[^>]*>", masked, re.I):
        tag = text[m.start():m.end()]
        if has_attr(tag, "onclick") or has_attr(tag, "formaction"):
            continue
        btn_type = (get_attr(tag, "type") or "").lower()
        in_form = any(s <= m.start() < e for s, e in form_spans)
        if in_form and btn_type in ("", "submit"):
            continue  # form 안의 submit 버튼은 form 이 처리

        el_id = get_attr(tag, "id")
        classes = (get_attr(tag, "class") or "").split()
        if el_id:
            if id_referenced_in_js(js_all, el_id):
                continue
        elif any(class_referenced_in_js(js_all, c) for c in classes):
            continue

        cap = re.search(r"(.*?)</button", text[m.end():], re.S | re.I)
        name = " ".join(re.sub(r"<[^>]+>", "", cap.group(1)).split()) if cap else ""
        label = f"버튼명: '{name}', id: '{el_id}'" if el_id else f"버튼명: '{name}'"
        pre = f"{ln(m.start())}행 <button> {label}"
        pos = tag_insert_pos(m)

        action = infer_button_action(file_name, name, el_id, classes, anc_map.get(m.start(), []),
                                     funcs, css_js, actions)
        if action:
            code, why = action
            attr = "" if btn_type else ' type="button"'
            attr += ' onclick="' + code.replace('"', "&quot;") + '"'
            inserts.append((pos, attr))
            rows.append(("수정", "button 동작 연결", f"{pre}: onclick 추가 -> {code}  [{why}]"))
            continue

        if btn_type:
            rows.append(("수동확인", "button 동작 연결",
                         f"{pre}: 동작 연결 코드 없음 (type='{btn_type}'은 유지). 동작표(--actions)에 지정하면 자동 반영"))
        else:
            inserts.append((pos, ' type="button"'))
            rows.append(("수정", "button 동작 연결",
                         f'{pre}: type="button" 추가 (의도치 않은 전송 방지)'))
            rows.append(("수동확인", "button 동작 연결",
                         f"{pre}: 클릭 시 실행할 동작을 파일에서 추정하지 못함. 동작표(--actions)에 지정하면 자동 반영"))
        if unresolved is not None:
            unresolved.append({"파일명": file_name, "버튼id": el_id or "", "버튼명": name, "줄": ln(m.start())})

    step("button 검사")

    # ---- 3) <body> 없음
    if not re.search(r"<body\b", masked, re.I):
        head_close = re.search(r"</head\s*>", masked, re.I)
        html_open = re.search(r"<html\b[^>]*>", masked, re.I)
        doctype = re.search(r"<!doctype[^>]*>", masked, re.I)
        if head_close:
            pos = head_close.end()
        elif html_open:
            pos = html_open.end()
        elif doctype:
            pos = doctype.end()
        else:
            pos = 0
        inserts.append((pos, "\n<body>"))

        if not re.search(r"</body\s*>", masked, re.I):
            html_close = list(re.finditer(r"</html\s*>", masked, re.I))
            if html_close:
                inserts.append((html_close[-1].start(), "</body>\n"))
            else:
                inserts.append((len(text), "\n</body>\n"))
        rows.append(("수정", "body 태그", f"<body> 시작·종료 태그 삽입 (시작 태그 위치: {ln(pos)}행 부근)"))

    step("body 검사")

    # ---- 4) HTML에 없는 id 에 이벤트 연결
    existing_ids = set(re.findall(r"""\bid\s*=\s*["']?([^\s"'>]+)""", text, re.I))
    existing_ids |= set(re.findall(r"""\.id\s*=\s*["']([^"']+)""", text))
    existing_ids |= set(re.findall(r"""setAttribute\(\s*["']id["']\s*,\s*["']([^"']+)""", text))

    fixed_ids = set()
    for offset, body in blocks:
        for m in GET_BY_ID_RE.finditer(body):
            el_id = m.group("id")
            if el_id in existing_ids:
                continue
            inserts.append((offset + m.start("dot"), "?"))
            fixed_ids.add(el_id)
            rows.append(("수정", "존재하지 않는 요소 이벤트 연결",
                         f"{ln(offset + m.start('dot'))}행 getElementById('{el_id}')?.addEventListener 로 변경 (null 오류 방지, 요소가 없으면 이벤트도 연결되지 않음)"))

    reported = set()
    for offset, body in blocks:
        for m in GET_BY_ID_ANY_RE.finditer(body):
            el_id = m.group("id")
            if el_id in existing_ids or el_id in fixed_ids or el_id in reported:
                continue
            reported.add(el_id)
            rows.append(("수동확인", "존재하지 않는 요소 참조",
                         f"{ln(offset + m.start())}행 getElementById('{el_id}'): HTML에서 id를 찾을 수 없음 (자동 수정 불가)"))

    step("요소(id) 검사")
    return inserts, rows


def apply_inserts(text: str, inserts):
    for pos, s in sorted(inserts, key=lambda x: x[0], reverse=True):
        text = text[:pos] + s + text[pos:]
    return text


# ------------------------------------------------------------------ 파일명 규칙
def next_output_path(src: Path, out_dir: Path) -> Path:
    m = re.match(r"^(.*)_v(\d+)$", src.stem)
    base, ver = (m.group(1), int(m.group(2)) + 1) if m else (src.stem, 2)
    while (out_dir / f"{base}_v{ver}{src.suffix}").exists():
        ver += 1
    return out_dir / f"{base}_v{ver}{src.suffix}"


def resolve_report(name: str, label: str = "점검 결과 파일") -> Path:
    """파일명만 입력하면 현재 폴더 -> results 폴더 순서로 찾는다. 확장자를 생략하면 .csv 도 시도한다."""
    p = Path(name.strip().strip('"').strip("'"))
    cands = [p]
    if p.suffix == "":
        cands.append(p.with_suffix(".csv"))
    if p.parent == Path("."):
        cands += [Path(RESULT_DIR_NAME) / c.name for c in list(cands)]
    for c in cands:
        if c.is_file():
            return c
    tried = "\n  ".join(str(c) for c in cands)
    sys.exit(f"{label}을(를) 찾을 수 없습니다. 확인한 경로:\n  {tried}")


def _load_matrix(path: Path):
    """csv/xlsx 를 문자열 2차원 목록으로 읽는다."""
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        try:
            from openpyxl import load_workbook
        except ImportError:
            sys.exit("xlsx를 읽으려면 'pip install openpyxl'이 필요합니다. (또는 csv로 저장해서 사용)")
        ws = load_workbook(path, read_only=True, data_only=True).active
        return [["" if c is None else str(c).strip() for c in r] for r in ws.iter_rows(values_only=True)]
    text, _ = read_text(path)
    return [[c.strip() for c in r] for r in csv.reader(io.StringIO(text))]


def read_actions(path: Path):
    """동작표: 열 [파일명(선택) / 버튼id / 버튼명 / 동작코드]"""
    data = _load_matrix(path)
    hi = next((i for i, r in enumerate(data) if "동작코드" in r), None)
    if hi is None:
        sys.exit("동작표에서 '동작코드' 열을 찾을 수 없습니다.")
    header = data[hi]

    def g(r, col):
        i = header.index(col) if col in header else None
        return r[i].strip() if i is not None and len(r) > i else ""

    out = []
    for r in data[hi + 1:]:
        code = g(r, "동작코드")
        a = {"file": g(r, "파일명"), "id": g(r, "버튼id"), "name": g(r, "버튼명"), "code": code}
        if code and (a["id"] or a["name"]):
            out.append(a)
    return out


def read_report(path: Path):
    """점검 결과표(csv/xlsx)에서 [파일명, 구분, 내용] 행을 읽는다. 숨겨진(필터된) 행도 포함된다."""
    data = _load_matrix(path)

    header_idx = next((i for i, r in enumerate(data) if "파일명" in r), None)
    if header_idx is None:
        sys.exit("리포트에서 '파일명' 열을 찾을 수 없습니다.")
    header = data[header_idx]
    col = {name: header.index(name) for name in ("파일명", "구분", "내용") if name in header}

    result = []
    for r in data[header_idx + 1:]:
        name = r[col["파일명"]] if len(r) > col["파일명"] else ""
        if not name:
            continue
        result.append({
            "파일명": name,
            "구분": r[col["구분"]] if "구분" in col and len(r) > col["구분"] else "",
            "내용": r[col["내용"]] if "내용" in col and len(r) > col["내용"] else "",
        })
    return result


def report_category(content: str):
    if "<form" in content:
        return "form"
    if "<button" in content:
        return "button"
    if "<body" in content:
        return "body"
    if "getElementById" in content:
        return "요소"
    return None


ITEM_TO_CATEGORY = {
    "form 전송 처리": "form",
    "button 동작 연결": "button",
    "body 태그": "body",
    "존재하지 않는 요소 이벤트 연결": "요소",
    "존재하지 않는 요소 참조": "요소",
}


def build_ai_prompt(unresolved, texts):
    """동작을 추정하지 못한 버튼을 채팅 AI에 붙여 넣을 수 있는 질문문으로 만든다."""
    head = (
        "아래는 웹페이지 HTML의 일부입니다. 각 버튼은 클릭했을 때 실행할 동작이 연결되어 있지 않습니다.\n"
        "버튼 주변 코드와 스크립트를 보고 알맞은 동작을 추정해서, 버튼마다 자바스크립트 한 줄을 만들어 주세요.\n\n"
        "[규칙]\n"
        "- 만든 코드는 HTML의 onclick=\"...\" 안에 그대로 들어갑니다.\n"
        "- 반드시 한 줄로 쓰고, 큰따옴표(\")는 쓰지 말고 작은따옴표(')만 사용하세요.\n"
        "- 코드에 없는 정보(주소, 함수 이름 등)를 지어내지 마세요. 알 수 없으면 동작코드를 비우고 메모에 필요한 정보를 적어 주세요.\n"
        "- 추측한 경우 메모에 그 근거를 한 줄로 적어 주세요.\n\n"
        "[답변 형식] 아래 형식의 CSV를 코드블록 하나로만 답해 주세요. 동작코드와 메모는 큰따옴표로 감싸세요.\n"
        "파일명,버튼id,버튼명,동작코드,메모\n"
        "예시.html,nextBtn,다음,\"location.href='step2.html'\",\"다음 단계 페이지로 이동으로 추정\"\n\n"
        "==================== 대상 버튼 ====================\n"
    )
    out = [head]
    by_file = {}
    for u in unresolved:
        by_file.setdefault(u["파일명"], []).append(u)
    for fname, items in by_file.items():
        text = texts.get(fname, "")
        lines = text.splitlines()
        out.append(f"\n######## 파일: {fname}\n")
        for u in items:
            out.append(f"--- 버튼 id: {u['버튼id'] or '(없음)'} / 버튼명: {u['버튼명']} / {u['줄']}행\n")
            a, b = max(0, u["줄"] - 1 - 12), min(len(lines), u["줄"] + 12)
            out.append("\n".join(f"{i + 1}: {lines[i]}" for i in range(a, b)) + "\n")
        js = style_and_script_text(text).strip()
        if len(js) > 8000:
            js = js[:8000] + "\n... (이하 생략)"
        out.append(f"\n--- {fname}의 CSS/JS ---\n{js or '(없음)'}\n")
    return "".join(out)


def main():
    ap = argparse.ArgumentParser(description="HTML 점검 결과 기반 자동 수정")
    ap.add_argument("--src", default="html", help="HTML 폴더 (기본: html)")
    ap.add_argument("--report", help="점검 결과표 파일명 또는 경로 (.xlsx / .csv). 파일명만 쓰면 results 폴더에서도 찾음")
    ap.add_argument("--actions", help="버튼 동작표 (.csv / .xlsx). 열: 파일명 / 버튼id / 버튼명 / 동작코드")
    args = ap.parse_args()

    src_dir = Path(args.src)
    if not src_dir.is_dir():
        sys.exit(f"HTML 폴더를 찾을 수 없습니다: {src_dir.resolve()}")

    out_dir = Path(OUT_DIR_NAME)
    result_dir = Path(RESULT_DIR_NAME)
    out_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)

    # 처리 대상 결정
    actions = []
    actions_name = args.actions or ACTIONS_FILE
    if actions_name:
        actions_path = resolve_report(actions_name, "동작표 파일")
        actions = read_actions(actions_path)
        print(f"동작표: {actions_path} ({len(actions)}건)")
    unresolved = []
    texts = {}

    report_name = args.report or REPORT_FILE
    if not report_name and sys.stdin.isatty():
        report_name = input("점검 결과 파일명 입력 (results 폴더 기준, 비우면 html 폴더 전체 처리): ").strip()

    report_by_file = {}
    if report_name:
        report_path = resolve_report(report_name)
        print(f"리포트 파일: {report_path}")
        all_rows = read_report(report_path)
        all_names = list(dict.fromkeys(r["파일명"] for r in all_rows))
        for r in all_rows:
            if r["구분"].strip() == SKIP_STATUS:  # '정상' 행은 대상에서 제외
                continue
            report_by_file.setdefault(r["파일명"], []).append(r)
        names = [n for n in all_names if n in report_by_file]
        skipped = [n for n in all_names if n not in report_by_file]
        print(f"리포트에서 {len(all_names)}개 파일 확인 (처리 {len(names)}개, '{SKIP_STATUS}'이라 제외 {len(skipped)}개)")
    else:
        names = sorted(p.name for p in src_dir.iterdir() if p.suffix.lower() in (".html", ".htm"))
        print("리포트 없이 폴더 내 모든 HTML 처리")

    result_rows = []
    changed_count = 0
    FILE_STEPS = 6  # 읽기, form, button, body, 요소(id), 저장

    overall_bar = tqdm(total=len(names), desc="전체 진행", unit="개", position=0)
    file_bar = tqdm(total=FILE_STEPS, desc="현재 파일", unit="단계", position=1, leave=False)

    for name in names:
        file_bar.reset(total=FILE_STEPS)
        file_bar.set_description(f"현재 파일: {name}")

        f = src_dir / name
        if not f.is_file():
            result_rows.append([name, "수정 불가", f"[파일 없음] {src_dir} 폴더에서 파일을 찾을 수 없음"])
            tqdm.write(f"[오류] 파일 없음: {f}")
            overall_bar.update(1)
            continue
        try:
            text, enc = read_text(f)
        except Exception as e:
            result_rows.append([name, "수정 불가", f"[파일 읽기 오류] {e}"])
            tqdm.write(f"[오류] {name}: {e}")
            overall_bar.update(1)
            continue
        file_bar.update(1)  # 읽기 완료

        def on_step(label, _bar=file_bar, _name=name):
            _bar.update(1)
            _bar.set_description(f"현재 파일: {_name} ({label} 완료)")

        texts[name] = text
        inserts, rows = process_html(text, on_step, actions, unresolved, name)

        # 리포트 대조: 리포트에는 있는데 코드가 찾지 못한 항목
        found = {ITEM_TO_CATEGORY[item] for _, item, _ in rows if item in ITEM_TO_CATEGORY}
        for r in report_by_file.get(name, []):
            cat = report_category(r["내용"])
            if cat and cat not in found:
                rows.append(("수동확인", "리포트 대조",
                             f"리포트에는 있으나 코드에서 같은 문제를 찾지 못함: {r['내용']}"))
                found.add(cat)

        # 수정 여부와 관계없이 항상 복사본을 html_edit 에 저장 (원본은 그대로 유지)
        out_path = next_output_path(f, out_dir)
        write_text(out_path, apply_inserts(text, inserts) if inserts else text, enc)
        saved_name = out_path.name
        file_bar.update(1)  # 저장 완료

        if inserts:
            changed_count += 1
            tqdm.write(f"[수정 후 복사] {name} -> {out_dir}/{saved_name}")
        else:
            tqdm.write(f"[수정 없이 복사] {name} -> {out_dir}/{saved_name}")

        if not rows:
            result_rows.append([name, "수정 불가",
                                f"[수정 대상 없음] 코드에서 수정할 항목을 찾지 못해 원본 그대로 복사 (저장: {saved_name})"])
        for kind, item, desc in rows:
            if kind == "수정":
                result_rows.append([name, "수정 완료", f"[{item}] {desc} (저장: {saved_name})"])
            else:
                result_rows.append([name, "수정 불가", f"[{item}] {desc}"])

        overall_bar.update(1)

    file_bar.close()
    overall_bar.close()

    stamp = datetime.now().strftime("%y%m%d_%H%M%S")
    csv_path = result_dir / f"result_{stamp}.csv"
    n = 2
    while csv_path.exists():  # 같은 초에 다시 실행해도 기존 파일을 덮어쓰지 않음
        csv_path = result_dir / f"result_{stamp}_{n}.csv"
        n += 1
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["파일명", "구분", "내용"])
        w.writerows(result_rows)

    if unresolved:
        tpl_path = result_dir / f"actions_template_{stamp}.csv"
        with open(tpl_path, "w", encoding="utf-8-sig", newline="") as fp:
            w = csv.writer(fp)
            w.writerow(["파일명", "버튼id", "버튼명", "줄번호", "동작코드"])
            for u in unresolved:
                w.writerow([u["파일명"], u["버튼id"], u["버튼명"], u["줄"], ""])
        print(f"\n동작을 추정하지 못한 버튼 {len(unresolved)}개 -> {tpl_path}")
        print("  '동작코드' 열을 채운 뒤  --actions 로 지정해서 다시 실행하세요.")
        prompt_path = result_dir / f"ai_prompt_{stamp}.txt"
        with open(prompt_path, "w", encoding="utf-8-sig", newline="") as fp:
            fp.write(build_ai_prompt(unresolved, texts))
        print(f"  채팅 AI에 붙여 넣을 질문 파일: {prompt_path}")

    print(f"\n완료: 전체 {len(names)}개 처리, 이 중 {changed_count}개 수정 (원본은 {src_dir} 폴더에 그대로 남아 있음)")
    print(f"수정본 폴더: {out_dir.resolve()}")
    print(f"결과 CSV  : {csv_path.resolve()}")


if __name__ == "__main__":
    main()
