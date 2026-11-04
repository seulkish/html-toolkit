# -*- coding: utf-8 -*-
"""
HTML 목업 자동 검수기 (Playwright + tqdm)

폴더 구조
    html_qa_playwright.py
    html/      <- 검수할 .html 파일들
    results/   <- result_YYMMDD_HHMMSS.csv 가 생성됨

동작 방식
    - html 폴더의 상위 폴더(SERVE_ROOT)를 내장 로컬 웹서버(127.0.0.1)로 띄워 http:// 로 엽니다.
      file:// 로 열면 Chrome이 fetch()·ES 모듈을 막아 정상 목업도 오류로 잡히기 때문입니다.
    - 외부(CDN 등) 요청은 막지 않습니다. jQuery·Bootstrap CDN을 정상적으로 불러옵니다.
      다만 외부 '페이지 이동'(외부 링크 클릭)은 실제로 접속하지 않고 빈 화면으로 대체합니다.
    - 네트워크 검사는 하지 않습니다. 외부 리소스 실패는 오류로 기록하지 않습니다.

결과 CSV (파일명, 구분, 내용) — 구분 기준
    오류 : 확실히 고장난 것 (JS 오류, 없는 파일/이미지, 다운로드 실패, 로그인 폼 무반응 등)
    경고 : 고장일 가능성이 높아 확인이 필요한 것 (클릭 무반응, 입력 검증 실패, 콘솔 오류 등)
    주의 : 구조상 의심되지만 의도일 수도 있는 것 (전송 대상 없는 <form>, href='#' 무반응,
           다른 요소에 가려져 클릭 불가, CDN 로드 실패 영향일 수 있는 JS 오류 등)
    정상 : 발견된 항목 없음
"""

import csv
import hashlib
import re
import tempfile
import threading
import time
from collections import Counter
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote, quote

from playwright.sync_api import sync_playwright, Error as PWError
from tqdm import tqdm

# ───────────── 설정 ─────────────
HTML_DIR = Path("html_input")  # 검수할 html 파일이 있는 폴더
RESULT_DIR = Path("results")
SERVE_ROOT = HTML_DIR.resolve().parent   # 웹서버 루트. html에서 ../css 처럼 상위 폴더를 참조해도 열리도록
HEADLESS = True              # 브라우저 화면을 보고 싶으면 False
MAX_ROUTES = 40              # 파일당 탐색할 최대 화면 수
MAX_CLICKS_PER_FILE = 300    # 파일당 최대 클릭 수
CLICK_WAIT_MS = 250          # 클릭 후 반응 대기 시간
LOAD_WAIT_MS = 150           # 화면 이동 후 렌더링 대기 시간
SAME_PATTERN_LIMIT = 2       # 같은 모양 요소/화면(예: 목록의 상세보기 50개)은 몇 개만 샘플 검사
REPORT_NO_RESPONSE = True    # '클릭해도 반응 없음'을 기록할지
SHOW_LOCATION = True         # 내용 뒤에 발생 위치(화면 > 요소)를 붙일지
MAX_LOCATIONS = 3            # 같은 내용이 여러 곳에서 나올 때 표시할 위치 수
LEVEL_ORDER = ["오류", "경고", "주의"]
# ────────────────────────────────

CLICKABLE_SELECTOR = (
    "a[href], button, [onclick], [role=button], [role=tab], [role=menuitem], "
    "input[type=button], input[type=submit], summary, [data-action]"
)

# 페이지 스크립트보다 먼저 실행: submit 리스너 등록 여부를 기록(jQuery .on('submit')도 포함)
SUBMIT_HOOK_JS = """
(() => {
  const orig = EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener = function (type, fn, opts) {
    try {
      if (type === 'submit') {
        if (this instanceof HTMLFormElement) this.__qaSubmit = true;
        else window.__qaGlobalSubmit = true;   // document/body 위임 방식
      }
    } catch (e) {}
    return orig.call(this, type, fn, opts);
  };
})();
"""

# 화면의 클릭 요소에 번호표(data-qa-id)를 붙이고 정보를 돌려주는 JS
TAG_ELEMENTS_JS = """
(sel) => {
  const out = [];
  let i = 0;
  for (const el of document.querySelectorAll(sel)) {
    if (el.closest('form') && (el.type === 'submit' || el.matches('form button:not([type])'))) continue;
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    const visible = r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
    if (!visible || el.disabled) continue;
    el.setAttribute('data-qa-id', String(i));
    const text = (el.innerText || el.value || el.getAttribute('aria-label') || el.title || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
    out.push({
      id: i,
      tag: el.tagName.toLowerCase(),
      text: text,
      href: el.getAttribute('href') || '',
      absHref: el.href || '',
      target: el.getAttribute('target') || '',
      download: el.hasAttribute('download'),
      onclick: (el.getAttribute('onclick') || '').slice(0, 60),
    });
    i++;
  }
  return out;
}
"""

# 화면 내용 + 스크롤 위치 + 포커스까지 비교('맨 위로' 버튼 같은 동작도 반응으로 인정)
STATE_JS = "() => document.body ? Math.round(window.scrollY) + '|' + (document.activeElement && document.activeElement.id) + '|' + document.body.innerHTML : ''"

# 로컬(같은 서버) 이미지만 검사. 외부 이미지는 네트워크 검사 대상이 아니므로 제외
BROKEN_IMG_JS = """
() => [...document.images]
  .filter(img => {
    if (!img.complete || img.naturalWidth !== 0 || !img.getAttribute('src')) return false;
    try { return new URL(img.src).origin === location.origin; } catch (e) { return false; }
  })
  .map(img => img.getAttribute('src').slice(0, 80))
"""

# 폼 구조 검사: action·onsubmit·submit 리스너가 하나도 없으면 전송 대상 불명
FORM_STRUCT_JS = """
(idx) => {
  const f = document.querySelectorAll('form')[idx];
  if (!f) return null;
  const hasAction = !!(f.getAttribute('action') || '').trim();
  const hasOnsubmit = typeof f.onsubmit === 'function';
  const hasListener = !!f.__qaSubmit || !!window.__qaGlobalSubmit;
  const hasFormAction = !!f.querySelector('[formaction]');
  return { noTarget: !hasAction && !hasOnsubmit && !hasListener && !hasFormAction };
}
"""

FILL_FORM_JS = """
(idx) => {
  const f = document.querySelectorAll('form')[idx];
  if (!f) return null;
  let hasPw = false;
  for (const el of f.querySelectorAll('input, textarea, select')) {
    if (el.disabled || el.readOnly) continue;
    const t = (el.type || '').toLowerCase();
    const set = (v) => { el.value = v; el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); };
    if (['hidden','submit','button','reset','file','image'].includes(t)) continue;
    if (t === 'password') { hasPw = true; set('Test1234!@'); }
    else if (t === 'email') set('qa_tester@example.com');
    else if (t === 'tel') set('010-1234-5678');
    else if (t === 'number' || t === 'range') set(el.min || '1');
    else if (t === 'date') set('2026-10-30');
    else if (t === 'time') set('10:00');
    else if (t === 'url') set('https://example.com');
    else if (t === 'checkbox') { el.checked = true; el.dispatchEvent(new Event('change', {bubbles:true})); }
    else if (t === 'radio') { el.checked = true; el.dispatchEvent(new Event('change', {bubbles:true})); }
    else if (el.tagName === 'SELECT') { if (el.options.length > 1) el.selectedIndex = 1; el.dispatchEvent(new Event('change', {bubbles:true})); }
    else set(el.minLength > 0 ? '테스트'.padEnd(el.minLength, '1') : '테스트');
  }
  // f.id 대신 getAttribute 사용: <input name="id">가 있으면 f.id가 그 input을 가리킴
  const name = (f.getAttribute('id') || f.getAttribute('name') || f.getAttribute('class') || ('form' + idx)).slice(0, 30);
  return { hasPw, name };
}
"""

EXTERNAL_PAGE_HTML = "<!doctype html><meta charset='utf-8'><title>external</title><body>외부 링크(검수 중 실제 접속 안 함)</body>"


# ───────────── 내장 로컬 웹서버 ─────────────
class _QuietHandler(SimpleHTTPRequestHandler):
    # Windows는 레지스트리 설정에 따라 .js를 text/plain으로 내보내 ES 모듈이 막히는 경우가 있어 고정
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
        ".json": "application/json", ".svg": "image/svg+xml", ".wasm": "application/wasm",
        ".html": "text/html", ".htm": "text/html",
    }

    def do_POST(self):
        # 정적 목업이므로 POST 폼 제출도 파일을 그대로 돌려줌(file:// 동작과 동일)
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self.do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass  # 브라우저가 연결을 끊을 때 나는 BrokenPipe 로그 숨김


def start_server(root: Path):
    server = _QuietServer(("127.0.0.1", 0), partial(_QuietHandler, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


# ───────────── 유틸 ─────────────
def state_hash(page):
    try:
        return hashlib.md5(page.evaluate(STATE_JS).encode("utf-8")).hexdigest()
    except PWError:
        return ""


def pattern(text):
    """'favorite('ST-012')' / '#/stations/12' 같은 반복 요소를 같은 패턴으로 묶기"""
    text = re.sub(r"\(.*\)", "()", text or "")
    text = re.sub(r"\d+", "N", text)
    if text.count("/") >= 2:                     # #/regions/서울 → #/regions/*
        text = text.rsplit("/", 1)[0] + "/*"
    text = re.sub(r"(id|no|seq|item)=[^&#]*", r"\1=*", text)
    return text


def classify_click_error(full_msg):
    """
    Playwright 예외 전문(콜 로그 포함)에서 실제 원인을 찾아 (구분, 내용)으로 돌려줌.
    첫 줄만 보면 'Timeout 2000ms exceeded'만 남아 원인을 알 수 없으므로 전체를 검사.
    """
    m = re.search(r"(<[^>\n]{1,80}>)[^\n]*intercepts pointer events", full_msg)
    if m:
        return "주의", f"다른 요소에 가려져 클릭 불가(가리는 요소: {m.group(1)})"
    if "intercepts pointer events" in full_msg:
        return "주의", "다른 요소에 가려져 클릭 불가"
    if "outside of the viewport" in full_msg:
        return "주의", "요소가 화면 밖에 있어 클릭 불가"
    if "not visible" in full_msg:
        return "주의", "요소가 보이지 않아 클릭 불가(숨김 상태)"
    if "not enabled" in full_msg or "disabled" in full_msg:
        return "주의", "요소가 비활성 상태라 클릭 불가"
    if "not stable" in full_msg:
        return "주의", "요소가 계속 움직여(애니메이션) 클릭 불가"
    if "not attached" in full_msg or "detached" in full_msg:
        return "주의", "클릭 직전에 요소가 화면에서 사라짐"
    first = full_msg.split("\n")[0]
    if "Timeout" in first:
        return "경고", "클릭 대기 시간 초과(원인 미확인)"
    return "오류", f"클릭 실패: {first[:80]}"


class FileTester:
    def __init__(self, browser, html_file: Path, origin: str, inner_bar: tqdm):
        self.file = html_file
        self.origin = origin
        rel = html_file.resolve().relative_to(SERVE_ROOT)
        self.base_path = "/" + rel.as_posix()
        self.base_url = origin + quote(self.base_path)
        self.bar = inner_bar
        self.findings = {}   # (구분, 내용) -> [위치, ...]
        self.events = []     # 클릭 중 발생한 이벤트
        self.cdn_failed = set()   # 불러오지 못한 외부 스크립트/CSS 호스트
        self.context = browser.new_context(accept_downloads=True)
        self.context.add_init_script(SUBMIT_HOOK_JS)
        # 외부 요청은 그대로 통과(CDN 정상 로드). 외부 '페이지 이동'만 빈 화면으로 대체
        self.context.route(lambda u: u.startswith("http") and not u.startswith(self.origin), self._route_external)
        self.context.on("response", self._on_response)
        self.context.on("requestfailed", self._on_request_failed)
        self.page = self.context.new_page()
        self.context.on("page", self._on_popup)  # 메인 페이지 생성 후 등록
        self.page.set_default_timeout(3000)
        self._attach(self.page)
        self.dl_dir = Path(tempfile.mkdtemp(prefix="qa_dl_"))

    # ── 네트워크 처리 ──
    def _route_external(self, route):
        try:
            if route.request.resource_type == "document":
                route.fulfill(status=200, content_type="text/html; charset=utf-8", body=EXTERNAL_PAGE_HTML)
            else:
                route.continue_()
        except PWError:
            pass

    def _local_name(self, url):
        return unquote(urlparse(url).path).lstrip("/")

    def _on_response(self, r):
        url = r.url
        if url.startswith(self.origin):
            if r.status < 400 or url.endswith("favicon.ico"):
                return
            rtype = r.request.resource_type
            if rtype == "image":
                return  # 깨진 이미지는 BROKEN_IMG_JS가 따로 잡음(중복 방지)
            if r.status == 404 and rtype == "document":
                self.events.append(("brokenlink", f"존재하지 않는 파일로 연결: {self._local_name(url)}"))
            elif r.status == 404:
                self.events.append(("resource", f"로컬 리소스 로드 실패: {self._local_name(url)}"))
            else:
                self.events.append(("resource", f"로컬 파일 응답 오류(HTTP {r.status}): {self._local_name(url)}"))
        elif r.status >= 400 and r.request.resource_type in ("script", "stylesheet"):
            self.cdn_failed.add(urlparse(url).netloc)

    def _on_request_failed(self, req):
        url = req.url
        fail = req.failure or ""
        if "ERR_ABORTED" in fail:
            return  # 화면 이동으로 중간에 취소된 요청은 문제 아님
        if url.startswith(self.origin):
            if not url.endswith("favicon.ico"):
                self.events.append(("resource", f"로컬 리소스 로드 실패: {self._local_name(url)}"))
        elif req.resource_type in ("script", "stylesheet"):
            self.cdn_failed.add(urlparse(url).netloc)

    # ── 이벤트 수집 ──
    def _attach(self, page):
        page.on("pageerror", lambda e: self.events.append(("jserror", str(e).split("\n")[0][:150])))
        page.on("console", self._on_console)
        page.on("dialog", self._on_dialog)
        page.on("download", lambda d: self.events.append(("download", d)))

    def _on_console(self, m):
        if m.type != "error":
            return
        if m.text.startswith("Failed to load resource"):
            return  # 리소스 실패는 _on_response에서 파일명과 함께 기록(중복 방지)
        self.events.append(("console", m.text[:150]))

    def _on_dialog(self, d):
        self.events.append(("dialog", f"{d.type}: {d.message[:60]}"))
        try:
            d.accept("테스트") if d.type == "prompt" else d.accept()
        except PWError:
            pass

    def _on_popup(self, p):
        if p is not getattr(self, "page", None):
            self.events.append(("popup", p.url))
            try:
                p.wait_for_load_state(timeout=2000)
                p.close()
            except PWError:
                pass

    # ── 결과 기록 ──
    def add(self, level, where, msg):
        locs = self.findings.setdefault((level, msg), [])
        if where not in locs:
            locs.append(where)

    def route_name(self, url):
        p = urlparse(url)
        return (("?" + p.query) if p.query else "") + (("#" + p.fragment) if p.fragment else "") or "메인"

    def same_file(self, url):
        p = urlparse(url)
        return url.startswith(self.origin) and unquote(p.path) == self.base_path

    def goto(self, url):
        self.page.goto("about:blank")
        self.page.goto(url, wait_until="load")
        self.page.wait_for_timeout(LOAD_WAIT_MS)

    def flush_errors(self, where):
        """events 중 에러성 항목을 기록하고 나머지(다운로드 등)를 반환"""
        rest = []
        for kind, val in self.events:
            if kind == "jserror":
                if self.cdn_failed:
                    self.add("주의", where, f"JS 오류(외부 CDN 로드 실패 영향 가능성): {val}")
                else:
                    self.add("오류", where, f"JS 오류: {val}")
            elif kind == "console":
                self.add("경고", where, f"콘솔 오류: {val}")
            elif kind in ("resource", "brokenlink"):
                self.add("오류", where, val)
            else:
                rest.append((kind, val))
        self.events = []
        return rest

    # ── 1단계: 화면 탐색 ──
    def discover_routes(self):
        routes, queue, seen = [], [self.base_url], {self.base_url}
        pat_count = Counter()
        while queue and len(routes) < MAX_ROUTES:
            url = queue.pop(0)
            try:
                self.goto(url)
            except PWError as e:
                self.add("오류", self.route_name(url), f"화면 로드 실패: {str(e).split(chr(10))[0][:80]}")
                continue
            routes.append(url)
            name = self.route_name(url)
            self.flush_errors(f"{name} 로드")
            for src in self.page.evaluate(BROKEN_IMG_JS):
                self.add("오류", name, f"깨진 이미지: {src}")
            hrefs = self.page.eval_on_selector_all("a[href]", "els => els.map(e => [e.getAttribute('href'), e.href])")
            for raw, absu in hrefs:
                if not raw or raw.startswith(("javascript:", "mailto:", "tel:", "http")):
                    continue
                if not absu.startswith(self.origin):
                    continue
                p = urlparse(absu)
                if not self.same_file(absu):
                    target = SERVE_ROOT / unquote(p.path).lstrip("/")
                    if not target.exists():
                        self.add("오류", name, f"존재하지 않는 파일로 연결: {unquote(p.path).lstrip('/')}")
                    continue
                # 같은 파일 내부 화면
                if (p.query or p.fragment) and absu not in seen and not raw.startswith("#main") and raw not in ("#", "#content", "#top"):
                    seen.add(absu)
                    key = pattern(raw)
                    pat_count[key] += 1
                    if pat_count[key] <= SAME_PATTERN_LIMIT:
                        queue.append(absu)
        return routes

    # ── 2단계: 모든 클릭 요소 테스트 ──
    def test_clicks(self, routes):
        tested = set()   # 화면이 달라도 같은 요소(헤더 메뉴 등)는 한 번만
        pat_count = Counter()
        plan = []
        for url in routes:
            try:
                self.goto(url)
                for el in self.page.evaluate(TAG_ELEMENTS_JS, CLICKABLE_SELECTOR):
                    if "바로가기" in el["text"] and el["href"].startswith("#"):
                        continue  # 키보드용 '본문 바로가기'는 평소 숨겨져 있어 제외
                    sig = (el["tag"], el["text"], el["href"], el["onclick"])
                    if sig in tested:
                        continue
                    tested.add(sig)
                    key = (el["tag"], pattern(el["onclick"]) or pattern(el["href"]) or el["text"])
                    pat_count[key] += 1
                    if pat_count[key] > SAME_PATTERN_LIMIT:
                        continue
                    plan.append((url, el))
            except PWError:
                continue
        plan = plan[:MAX_CLICKS_PER_FILE]
        self.events = []

        self.bar.reset(total=len(plan))
        dirty, cur_route = True, None
        for url, el in plan:
            label = el["text"] or el["href"] or el["onclick"] or el["tag"]
            where = f"{self.route_name(url)} > '{label}'"
            self.bar.set_postfix_str(f"클릭: {label[:20]}")
            try:
                if dirty or cur_route != url:
                    self.goto(url)
                    self.page.evaluate(TAG_ELEMENTS_JS, CLICKABLE_SELECTOR)
                    cur_route = url
                    self.events = []
                before_url, before_state = self.page.url, state_hash(self.page)
                loc = self.page.locator(f'[data-qa-id="{el["id"]}"]')
                if loc.count() == 0:
                    dirty = True
                    self.bar.update(1)
                    continue
                loc.first.click(timeout=2000)
                self.page.wait_for_timeout(CLICK_WAIT_MS)
                after_url = self.page.url
                if after_url.startswith("chrome-error"):
                    self.add("오류", where, "클릭 시 페이지 이동 실패")
                after_state = state_hash(self.page)
                rest = self.flush_errors(where)
                self.check_downloads(rest, where)
                changed = (before_url != after_url) or (before_state != after_state) or bool(rest)
                if not changed and el["href"] == "#":
                    self.add("주의", where, "href='#' 링크 클릭 시 반응 없음")
                elif not changed and REPORT_NO_RESPONSE:
                    self.add("경고", where, "클릭해도 반응 없음")
                dirty = changed
            except PWError as e:
                level, msg = classify_click_error(str(e))
                self.add(level, where, msg)
                dirty = True
            self.bar.update(1)

    def check_downloads(self, events, where):
        for kind, val in events:
            if kind != "download":
                continue
            try:
                fail = val.failure()
                if fail:
                    self.add("오류", where, f"다운로드 실패: {fail}")
                    continue
                dest = self.dl_dir / (val.suggested_filename or "file")
                val.save_as(dest)
                if dest.stat().st_size == 0:
                    self.add("오류", where, f"다운로드 파일이 비어 있음(0바이트): {dest.name}")
            except PWError as e:
                self.add("오류", where, f"다운로드 오류: {str(e).split(chr(10))[0][:80]}")

    # ── 3단계: 폼(로그인/회원가입/검색 등) 테스트 ──
    def test_forms(self, routes):
        plan = []
        for url in routes:
            try:
                self.goto(url)
                n = self.page.locator("form").count()
                plan += [(url, i) for i in range(n)]
            except PWError:
                pass
        self.bar.reset(total=max(len(plan), 1))
        done_names = set()
        for url, idx in plan:
            self.bar.set_postfix_str(f"폼 #{idx}")
            try:
                self.goto(url)
                self.events = []
                struct = self.page.evaluate(FORM_STRUCT_JS, idx)
                info = self.page.evaluate(FILL_FORM_JS, idx)
                if not info or info["name"] in done_names:
                    self.bar.update(1)
                    continue
                done_names.add(info["name"])
                kind = "로그인/회원가입 폼" if info["hasPw"] else "폼"
                where = f"{self.route_name(url)} > {kind}({info['name']})"
                if struct and struct["noTarget"]:
                    self.add("주의", where, "action·onsubmit·submit 리스너가 모두 없는 <form> 태그 (전송 대상 불명)")
                before_url, before_state = self.page.url, state_hash(self.page)
                self.page.evaluate("(i) => { const f = document.querySelectorAll('form')[i]; f.requestSubmit ? f.requestSubmit() : f.submit(); }", idx)
                self.page.wait_for_timeout(CLICK_WAIT_MS + 200)
                if self.page.url.startswith("chrome-error"):
                    self.add("오류", where, "제출 후 페이지 이동 실패")
                rest = self.flush_errors(where)
                self.check_downloads(rest, where)
                changed = before_url != self.page.url or before_state != state_hash(self.page) or bool(rest)
                if not changed:
                    invalid = self.page.evaluate("(i) => !document.querySelectorAll('form')[i]?.checkValidity()", idx)
                    if invalid:
                        self.add("경고", where, "테스트 값을 넣어도 입력 검증을 통과하지 못함(필수값/형식 확인 필요)")
                    elif info["hasPw"]:
                        self.add("오류", where, "제출해도 반응 없음(로그인/가입 처리 안 됨)")
                    else:
                        self.add("경고", where, "제출해도 반응 없음")
            except PWError as e:
                self.add("오류", f"{self.route_name(url)} 폼#{idx}", f"제출 실패: {str(e).split(chr(10))[0][:80]}")
            self.bar.update(1)

    def run(self):
        routes = []
        try:
            self.bar.reset(total=1)
            self.bar.set_description(f"  ├ {self.file.name[:25]} 화면 탐색")
            routes = self.discover_routes()
            self.bar.update(1)

            self.bar.set_description(f"  ├ {self.file.name[:25]} 클릭 검사")
            self.test_clicks(routes)

            self.bar.set_description(f"  └ {self.file.name[:25]} 폼 검사")
            self.test_forms(routes)
        except Exception as e:  # 한 파일이 죽어도 전체는 계속
            self.add("오류", "전체", f"검수 중단: {type(e).__name__}: {str(e)[:100]}")
        finally:
            self.context.close()
        return len(routes)

    # ── CSV 행 만들기 ──
    def rows(self):
        if not self.findings:
            return [[self.file.name, "정상", "-"]]
        out = []
        items = sorted(self.findings.items(), key=lambda kv: LEVEL_ORDER.index(kv[0][0]))
        for (level, msg), locs in items:
            text = msg
            if SHOW_LOCATION and locs:
                shown = ", ".join(locs[:MAX_LOCATIONS])
                more = f" 외 {len(locs) - MAX_LOCATIONS}곳" if len(locs) > MAX_LOCATIONS else ""
                text = f"{msg} — 위치: {shown}{more}"
            out.append([self.file.name, level, text])
        return out

    def worst_level(self):
        levels = {lv for lv, _ in self.findings}
        for lv in LEVEL_ORDER:
            if lv in levels:
                return lv
        return "정상"


def main():
    files = sorted(HTML_DIR.glob("*.html")) + sorted(HTML_DIR.glob("*.htm"))
    if not files:
        print(f"'{HTML_DIR}' 폴더에 html 파일이 없습니다.")
        return
    RESULT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%y%m%d_%H%M%S")
    out_csv = RESULT_DIR / f"result_{stamp}.csv"

    rows = []
    summary = Counter()
    start = time.time()
    server, origin = start_server(SERVE_ROOT)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=HEADLESS)
            file_bar = tqdm(files, desc="전체 파일", unit="file", position=0, ncols=100)
            inner_bar = tqdm(total=1, desc="  ├ 준비", position=1, ncols=100, leave=False)
            for f in file_bar:
                file_bar.set_postfix_str(f.name[:30])
                t = FileTester(browser, f, origin, inner_bar)
                n_routes = t.run()
                rows += t.rows()
                worst = t.worst_level()
                summary[worst] += 1
                cnt = Counter(lv for lv, _ in t.findings)
                tqdm.write(f"  {f.name}: {worst} (화면 {n_routes}개, 오류 {cnt['오류']}, 경고 {cnt['경고']}, 주의 {cnt['주의']})")
            inner_bar.close()
            file_bar.close()
            browser.close()
    finally:
        server.shutdown()

    # utf-8-sig: 엑셀에서 한글이 깨지지 않음
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as fp:
        w = csv.writer(fp)
        w.writerow(["파일명", "구분", "내용"])
        w.writerows(rows)

    print(f"\n완료: {len(files)}개 파일 / 오류 {summary['오류']} / 경고 {summary['경고']} / "
          f"주의 {summary['주의']} / 정상 {summary['정상']}  ({time.time()-start:.0f}초)")
    print("  (파일별로 가장 심각한 구분 기준으로 집계)")
    print(f"결과: {out_csv}")


if __name__ == "__main__":
    main()