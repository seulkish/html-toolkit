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

결과 CSV (파일명, 구분, 내용)
    수정 : 로그인·캘린더처럼 따로 모아 고칠 부분. 내용 앞에 '로그인 체크 필요' / '캘린더 체크 필요'와
           원래 구분(오류·경고·주의·불일치)을 적음. 엑셀에서 구분='수정'으로 필터하면 그 부분만 보임
           (수정으로 모을 기능은 FIX_CATEGORIES 설정에서 바꿈)
    오류 : 확실히 고장난 것 (JS 오류, 없는 파일/이미지, 다운로드 실패, 로그인 폼 무반응 등)
    경고 : 고장일 가능성이 높아 확인이 필요한 것 (클릭 무반응, 입력 검증 실패, 콘솔 오류 등)
    주의 : 구조상 의심되지만 의도일 수도 있는 것 (전송 대상 없는 <form>, href='#' 무반응,
           다른 요소에 가려져 클릭 불가, CDN 로드 실패 영향일 수 있는 JS 오류 등)
    (캘린더 범위 점검 결과: 불일치 → 수정, 일치 → 정상, 자동 판정 불가 → 주의)
    정상 : 자동 검사로 발견된 오류·경고·주의 없음

"""

import calendar
import csv
import hashlib
import json
import re
import shutil
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
HTML_DIR = Path("html_test")  # 검수할 html 파일이 있는 폴더
RESULT_DIR = Path("results")
EDIT_DIR = HTML_DIR.resolve().parent / "html_edit"  # '정상'이 아닌 파일을 옮길 폴더
MOVE_NOT_OK = True                                 # 이동 기능 끄려면 False
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
LEVEL_ORDER = ["오류", "경고", "주의", "요구사항", "수동"]
ROW_ORDER = ["수정", "오류", "경고", "주의", "수동", "정상"]   # 결과 CSV에 보이는 순서
SHOW_MANUAL = False          # True면 '자동 검사가 못 본 곳(수동)' 행도 결과 CSV에 표시
CALENDAR_CHECK = True        # 캘린더 표시 범위 점검(부장님 지시)
CALENDAR_START = "2026-10"   # 보여야 하는 첫 달
CALENDAR_END = "2027-06"     # 보여야 하는 마지막 달
CALENDAR_MODE = "include"      # exact: 이 범위 밖으로는 못 가야 함 / include: 이 범위가 모두 보이기만 하면 됨
CALENDAR_MAX_STEPS = 24      # '이전'·'다음'을 최대 몇 번 눌러 볼지(넘으면 '제한 없음')
MOVE_REQUIREMENT_MISMATCH = False   # True면 캘린더 [불일치] 파일도 html_edit 폴더로 이동
MOVE_FIX = True              # True면 구분='수정' 행이 하나라도 있는 파일은 무조건 html_edit 폴더로 이동
CLICK_DEPTH = 2              # 2: 클릭 후 나타난 버튼(모달·드롭다운·탭 내부)까지 자동 클릭. 1: 기존 방식
MAX_CHILD_CLICKS = 8         # 버튼 하나를 눌러 나타난 버튼 중 자동으로 눌러 볼 최대 수
HOVER_TEST = True            # 마우스를 올려야 열리는 메뉴를 자동으로 열어 클릭
MAX_HOVER_TESTS = 30         # 파일당 hover 메뉴 검사 최대 수
LOGIN_CHAIN_TEST = True      # 회원가입 폼 + 로그인 폼이 있으면 '가입 → 같은 값으로 로그인'을 이어서 검사
FAIL_WORDS = ("실패", "일치하지", "올바르지", "잘못", "존재하지 않", "등록되지 않", "가입되지 않", "없는 계정",
              "없는 아이디", "틀렸", "invalid", "incorrect", "failed", "wrong", "not found")
LOGIN_STATE_TEST = True      # 로그인 후 비로그인 화면이 '로그인 상태'로 바뀌는지, 로그아웃 후 원래대로 돌아오는지 검사
# 비로그인 때만 보여야 하는 버튼 글자(정확히 같을 때만, 폼 안의 제출 버튼은 제외)
GUEST_WORDS = ("로그인", "회원가입", "가입하기", "login", "log in", "sign in", "sign up", "signup", "join")
# 로그인 후 나타나야 하는 표시(화면 글자에 포함되면 인정). 비로그인 때부터 있던 글자는 제외하고 비교
MEMBER_WORDS = ("로그아웃", "logout", "log out", "sign out", "마이페이지", "my page", "mypage", "내 정보", "내정보",
                "환영", "qa_tester", "테스트님", "테스트 님")
# 파일별로 '비로그인 전용'·'회원 전용' 요소를 CSS 선택자로 지정(선택). 예:
# LOGIN_STATE_SELECTORS = {"1.html": {"guest": [".guest-banner", "#guestCart"], "member": ["#myMenu"],
#                                     "guest_actions": ["#addCartBtn"]}}   # 비회원 기록을 만드는 버튼(선택)
LOGIN_STATE_SELECTORS = {}
GUEST_RECORD_TEST = True     # 비회원으로 기록을 남긴 뒤 로그인하면 그 기록이 초기화되는지 검사
# 비회원 기록을 만들 만한 버튼 글자(포함되면 후보). 이 중 최대 GUEST_ACTION_MAX개를 눌러 기록을 남김
GUEST_RECORD_WORDS = ("담기", "장바구니", "찜", "즐겨찾기", "저장", "추가", "좋아요", "북마크", "관심",
                      "기록", "신청", "예약", "메모", "스크랩", "최근 본")
GUEST_ACTION_MAX = 5
GUEST_FORM_MAX = 2           # 비밀번호 없는 폼(검색·메모 등)도 비회원으로 최대 몇 개 제출해 볼지
CHECK_COLUMNS = ["확인결과(O/X)", "확인자", "비고"]     # 사람이 채우는 칸(빈칸으로 출력)
FIX_CATEGORIES = ("로그인", "캘린더")   # 이 기능의 문제는 구분='수정'으로 모음
DETAIL_COLUMNS = False       # True면 '수동 체크 흐름'·확인결과·확인자·비고 칸을 뒤에 붙임
PROBLEM_LEVELS = ("오류", "경고", "주의")   # 파일 판정·이동·누적 대상. '수동'은 판정에 넣지 않음
ADD_VISUAL_CHECK = True      # 파일마다 '화면 배치·문구 직접 확인' 수동 항목을 넣을지
MAX_SAMPLES = 4              # 수동 체크 흐름에 예시로 보여줄 버튼 이름 수
SETTLE_MAX_MS = 3000         # 화면이 스스로 바뀌는 동작(지도 타일 페이드인 등)이 멈출 때까지 기다리는 최대 시간
SETTLE_POLL_MS = 200         # 안정 여부를 확인하는 간격
# 링크 주소가 '아무 데도 안 감'인 값. 같은 패턴으로 묶지 않고 하나하나 검사
DEAD_HREFS = ("#", "", "javascript:;", "javascript:void(0)", "javascript:void(0);", "javascript:void 0")
CLICK_EVENT_TYPES = ("click", "mousedown", "mouseup", "pointerdown", "pointerup", "touchstart", "touchend")
LIVE_PRINT = True            # 파일 하나 끝날 때마다 문제 내용을 터미널에 바로 출력
LIVE_PRINT_MAX = 15          # 파일당 터미널에 보여줄 최대 줄 수(전체 내용은 CSV에 있음)
PER_FILE_CSV = True          # 파일마다 results/파일별_시각/이름.csv 따로 저장(검사 중 엑셀로 열어도 안전)
MOVE_IMMEDIATELY = False     # True면 정상 아닌 파일을 끝나자마자 html_edit로 이동(아래 주의 참고)
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
# 클릭 판정용: 입력칸에 JS로 넣은 값(el.value = ...)은 innerHTML에 안 나타나므로 값·체크 상태를 따로 붙임
# (예: '체험 계정 자동 입력' 버튼이 아이디·비밀번호를 채워도 '반응 없음'으로 잡히던 문제)
FIELD_VALUES_JS = """() => [...document.querySelectorAll('input, textarea, select')]
    .map(e => (e.type === 'checkbox' || e.type === 'radio') ? (e.checked ? '1' : '0') : e.value).join('\\u0001')"""

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

# 처음 화면에서 '숨겨져 있어' 자동 클릭 대상에서 빠진 요소(드롭다운·모달·탭 내부 등)
HIDDEN_CLICKABLES_JS = """
(sel) => {
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    if (el.closest('form') && (el.type === 'submit' || el.matches('form button:not([type])'))) continue;
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    const visible = r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
    if (visible || el.disabled) continue;
    const text = (el.textContent || el.value || el.getAttribute('aria-label') || el.title || el.getAttribute('href') || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
    if (!text || text.includes('바로가기')) continue;
    out.push([el.tagName.toLowerCase(), text]);
  }
  return out;
}
"""

# 지금 보이는 클릭 요소 목록(클릭 후 새로 나타난 버튼을 찾는 용도)
VISIBLE_SIGS_JS = """
(sel) => {
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    if (!(r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none') || el.disabled) continue;
    const text = (el.innerText || el.value || el.getAttribute('aria-label') || el.title || el.getAttribute('href') || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
    if (text) out.push([el.tagName.toLowerCase(), text]);
  }
  return out;
}
"""

# 처음 화면에 없던(새로 나타난) 버튼에 data-qa-cid 번호표를 붙이고 목록 반환
TAG_NEW_JS = """
([sel, base]) => {
  const known = new Set(base.map(x => x[0] + '\\u0001' + x[1]));
  const out = [];
  let i = 0;
  for (const el of document.querySelectorAll(sel)) {
    if (el.closest('form') && (el.type === 'submit' || el.matches('form button:not([type])'))) continue;
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    if (!(r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none') || el.disabled) continue;
    const tag = el.tagName.toLowerCase();
    const text = (el.innerText || el.value || el.getAttribute('aria-label') || el.title || el.getAttribute('href') || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
    if (!text || known.has(tag + '\\u0001' + text)) continue;
    el.setAttribute('data-qa-cid', String(i));
    out.push({ cid: i, tag, text, href: el.getAttribute('href') || '' });
    i++;
  }
  return out;
}
"""

# 숨겨진 메뉴 항목과, 마우스를 올릴 '가장 가까운 보이는 상위 요소'를 찾아 표시
HOVER_PREP_JS = """
([sel, tag, text]) => {
  const vis = (e) => { const r = e.getBoundingClientRect(); const st = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
  for (const el of document.querySelectorAll(sel)) {
    if (el.tagName.toLowerCase() !== tag || vis(el)) continue;
    const t = (el.textContent || el.value || el.getAttribute('aria-label') || el.title || el.getAttribute('href') || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
    if (t !== text) continue;
    let p = el.parentElement;
    while (p && p !== document.body && !vis(p)) p = p.parentElement;
    if (!p || p === document.body) return null;
    el.setAttribute('data-qa-hid', '1');
    p.setAttribute('data-qa-hover', '1');
    return ((p.innerText || '').trim().split('\\n')[0] || p.tagName.toLowerCase()).slice(0, 20);
  }
  return null;
}
"""

# 폼 종류 판별(비밀번호 칸 수, 회원가입 여부). 폼 안의 '회원가입' 링크 때문에 로그인 폼을 오인하지 않도록
# 제출 버튼 글자와 폼 속성만 봄
FORM_PEEK_JS = """
(idx) => {
  const f = document.querySelectorAll('form')[idx];
  if (!f) return null;
  const pw = f.querySelectorAll('input[type=password]').length;
  const btn = [...f.querySelectorAll('button:not([type]), button[type=submit], input[type=submit]')]
    .map(b => (b.innerText || b.value || '')).join(' ');
  const attrs = [f.getAttribute('id'), f.getAttribute('name'), f.getAttribute('class'), f.getAttribute('action')].join(' ');
  const signup = pw >= 2 || /가입|등록|sign ?up|register|join/i.test(btn) || /signup|sign-up|register|join/i.test(attrs);
  const name = (f.getAttribute('id') || f.getAttribute('name') || f.getAttribute('class') || ('form' + idx)).slice(0, 30);
  return { pw, signup, name };
}
"""

# 로그인 상태 스냅샷: 비로그인용 버튼, 로그인 표시, 입력칸에 남은 값, 지정 선택자
LOGIN_STATE_JS = """
([guestWords, memberWords, guestSel, memberSel, loginIdx]) => {
  const vis = (e) => { if (!e) return false; const r = e.getBoundingClientRect(); const st = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
  const norm = (t) => (t || '').trim().replace(/\\s+/g, ' ').toLowerCase();
  const guest = [];
  for (const el of document.querySelectorAll('a, button, [role=button], input[type=button], input[type=submit], [onclick]')) {
    if (el.closest('form') || !vis(el)) continue;
    const t = norm(el.innerText || el.value);
    if (guestWords.includes(t) && !guest.includes(t)) guest.push(t);
  }
  const text = norm(document.body ? document.body.innerText : '');
  const member = memberWords.filter(w => text.includes(w));
  const pw = [...document.querySelectorAll('input[type=password]')].filter(i => i.value);
  // 로그인·가입 폼(비밀번호 칸이 있는 폼) 안의 입력칸만 봄. 검색창 등에 남은 값은 제외
  const typed = [...document.querySelectorAll('form')].filter(f => f.querySelector('input[type=password]'))
    .flatMap(f => [...f.querySelectorAll('input')]).filter(i => ['qa_tester@example.com', '테스트'].includes(i.value)
    && !['hidden', 'checkbox', 'radio', 'submit', 'button'].includes((i.type || '').toLowerCase()));
  const q = (sel) => { try { return document.querySelector(sel); } catch (e) { return null; } };
  return {
    guest, member,
    pwVisible: pw.filter(vis).length, pwAny: pw.length,
    typedVisible: typed.filter(vis).length, typedAny: typed.length,
    guestSel: guestSel.filter(sel => vis(q(sel))),
    memberSel: memberSel.filter(sel => vis(q(sel))),
    loginFormVisible: vis(document.querySelectorAll('form')[loginIdx]),
  };
}
"""

# 보이는 '로그아웃' 버튼에 번호표를 붙이고 글자를 돌려줌
LOGOUT_TAG_JS = """
() => {
  const vis = (e) => { const r = e.getBoundingClientRect(); const st = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
  for (const el of document.querySelectorAll('a, button, [role=button], input[type=button], [onclick]')) {
    const t = (el.innerText || el.value || '').trim().toLowerCase();
    if (vis(el) && t.length < 15 && /로그아웃|logout|log out|sign out/.test(t)) {
      el.setAttribute('data-qa-logout', '1');
      return (el.innerText || el.value || '').trim();
    }
  }
  return null;
}
"""

# 캘린더 찾기: 월 제목(2026년 10월 / 2026.10 / October 2026) + 이전·다음 버튼 또는 날짜 칸(1~31)이 있는 묶음.
# 찾은 제목·버튼에 data-qa-cal-* 번호표를 붙임. date/month 입력칸, 월 선택 상자, '10월' 같은 월 탭도 함께 수집
CAL_SCAN_JS = r"""
() => {
  const MON = {jan:1,feb:2,mar:3,apr:4,may:5,jun:6,jul:7,aug:8,sep:9,oct:10,nov:11,dec:12};
  const ym = (y, m) => { m = +m; return (m >= 1 && m <= 12) ? `${y}-${String(m).padStart(2, '0')}` : null; };
  const parse = (t) => {
    t = (t || '').replace(/\s+/g, ' ').trim().replace(/[\s▾▼⌄˅]+$/, '');
    if (t.length > 25) return null;
    let m;
    if ((m = t.match(/^(\d{4})\s*년\s*(\d{1,2})\s*월$/))) return ym(m[1], m[2]);
    if ((m = t.match(/^(\d{4})\s*[.\-\/]\s*(\d{1,2})\.?$/))) return ym(m[1], m[2]);
    if ((m = t.match(/^(\d{1,2})\s*월\s*,?\s*(\d{4})\s*년?$/))) return ym(m[2], m[1]);
    if ((m = t.match(/^([A-Za-z]{3,9})\.?\s*,?\s*(\d{4})$/))) { const k = m[1].slice(0, 3).toLowerCase(); if (MON[k]) return ym(m[2], MON[k]); }
    return null;
  };
  const vis = (e) => { if (!e || !e.getBoundingClientRect) return false; const r = e.getBoundingClientRect(); const st = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
  const attrs = (el) => ((el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('title') || '') + ' ' +
    (typeof el.className === 'string' ? el.className : (el.className && el.className.baseVal) || '') + ' ' + (el.id || '')).toLowerCase();
  const clickable = (el) => el.matches('a, button, [role=button], [onclick], input[type=button]') || getComputedStyle(el).cursor === 'pointer';
  const isDir = (el, dir) => {
    const t = (el.innerText || el.value || '').trim().toLowerCase();
    const a = attrs(el);
    if (dir === 'prev') return /^(<|‹|«|◀|◁|〈|←|<<|이전|이전 ?달|prev|previous)$/.test(t) || (/prev|이전/.test(a) && !/next|다음/.test(a)) || (t === '' && /left/.test(a));
    return /^(>|›|»|▶|▷|〉|→|>>|다음|다음 ?달|next)$/.test(t) || (/next|다음/.test(a) && !/prev|이전/.test(a)) || (t === '' && /right/.test(a));
  };
  const findBtn = (box, title, dir) => {
    for (const el of box.querySelectorAll('a, button, [role=button], [onclick], input[type=button], span, i, div, svg')) {
      if (el === title || title.contains(el) || el.contains(title)) continue;
      if (isDir(el, dir) && clickable(el)) return el;
    }
    return null;
  };
  const dayGrid = (box) => {
    const s = new Set();
    for (const el of box.querySelectorAll('*')) {
      if (el.children.length) continue;
      const t = (el.textContent || '').trim();
      if (/^\d{1,2}$/.test(t) && +t >= 1 && +t <= 31) s.add(+t);
    }
    return s.size >= 28;
  };
  for (const el of document.querySelectorAll('[data-qa-cal-title],[data-qa-cal-prev],[data-qa-cal-next]')) {
    el.removeAttribute('data-qa-cal-title'); el.removeAttribute('data-qa-cal-prev'); el.removeAttribute('data-qa-cal-next');
  }
  // 1) 월 제목 후보: 자기 자신은 월로 읽히고, 안쪽에 더 작은 월 제목이 없는 요소
  const titles = [];
  for (const el of document.body.querySelectorAll('*')) {
    if (/^(SCRIPT|STYLE|OPTION|SELECT|TEMPLATE|NOSCRIPT)$/.test(el.tagName)) continue;
    const mo = parse(el.textContent);
    if (!mo) continue;
    if ([...el.querySelectorAll('*')].some(c => parse(c.textContent))) continue;
    titles.push([el, mo]);
  }
  const cals = [], boxes = new Set();
  for (const [el, mo] of titles) {
    let box = el, prev = null, next = null, grid = false;
    for (let k = 0; k < 6 && box.parentElement; k++) {
      box = box.parentElement;
      prev = prev || findBtn(box, el, 'prev');
      next = next || findBtn(box, el, 'next');
      grid = grid || dayGrid(box);
      if (prev || next) break;
    }
    if (!(prev || next || grid) || boxes.has(box)) continue;
    boxes.add(box);
    const i = cals.length;
    el.setAttribute('data-qa-cal-title', i);
    if (prev) prev.setAttribute('data-qa-cal-prev', i);
    if (next) next.setAttribute('data-qa-cal-next', i);
    cals.push({ i, month: mo, text: (el.textContent || '').trim().replace(/\s+/g, ' '), prev: !!prev, next: !!next, visible: vis(el) });
  }
  // 2) 날짜 입력칸
  const inputs = [...document.querySelectorAll('input[type=date], input[type=month], input[type=datetime-local], input[type=week]')]
    .map(e => ({ type: e.type, min: e.min || '', max: e.max || '', name: (e.id || e.name || e.type).slice(0, 30) }));
  // 3) 월 선택 상자(옵션이 '2026년 10월' 같은 형식)
  const selects = [];
  for (const s of document.querySelectorAll('select')) {
    const ms = [...s.options].map(o => parse(o.textContent) || parse(o.value)).filter(Boolean);
    if (ms.length >= 3) selects.push({ name: (s.id || s.name || 'select').slice(0, 30), months: ms.sort() });
  }
  // 4) '10월' '11월' 같은 월 탭
  const tabs = new Set();
  for (const e of document.querySelectorAll('a, button, [role=tab], [role=button], [onclick], li')) {
    const t = (e.innerText || '').trim();
    const m = t.match(/^(\d{1,2})\s*월$/);
    if (m && vis(e) && +m[1] >= 1 && +m[1] <= 12) tabs.add(+m[1]);
  }
  // 5) 형태를 알아보지 못한 캘린더 라이브러리 흔적
  const lib = !!document.querySelector('.fc, .flatpickr-calendar, .flatpickr-input, .ui-datepicker, .datepicker, [class*=calendar], [id*=calendar], [class*=datepicker], [id*=datepicker]');
  return { cals, inputs, selects, tabs: [...tabs], lib };
}
"""

# 비회원 기록용 버튼 하나를 골라 번호표(data-qa-gact)를 붙임. 이미 누른 글자(tried)는 건너뜀
GUEST_ACTION_JS = r"""
([words, tried, extraSel]) => {
  const vis = (e) => { const r = e.getBoundingClientRect(); const st = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
  document.querySelectorAll('[data-qa-gact]').forEach(e => e.removeAttribute('data-qa-gact'));
  const pick = (el, t) => { el.setAttribute('data-qa-gact', '1'); return t; };
  for (const sel of extraSel) {
    let el = null; try { el = document.querySelector(sel); } catch (e) {}
    if (el && vis(el) && !tried.includes(sel)) return pick(el, sel);
  }
  for (const el of document.querySelectorAll('a, button, [role=button], [onclick], input[type=button]')) {
    if (el.closest('form') || !vis(el) || el.disabled) continue;
    const t = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 30);
    if (!t || tried.includes(t)) continue;
    if (/로그|가입|삭제|비우기|초기화|취소|닫기|logout|login/i.test(t)) continue;
    if (words.some(w => t.includes(w))) return pick(el, t);
  }
  return null;
}
"""

# 브라우저 저장소(localStorage·sessionStorage) 내용
STORAGE_JS = r"""
() => {
  const o = {};
  for (const [name, st] of [['local', window.localStorage], ['session', window.sessionStorage]]) {
    try { for (let i = 0; i < st.length; i++) { const k = st.key(i); o[name + ':' + k] = String(st.getItem(k)).slice(0, 200); } } catch (e) {}
  }
  return o;
}
"""

# 비밀번호 칸이 없는 폼 번호(검색·메모 등)
PLAIN_FORMS_JS = "() => [...document.querySelectorAll('form')].map((f, i) => [i, f.querySelectorAll('input[type=password]').length]).filter(x => !x[1]).map(x => x[0])"

TEXT_LINES_JS = "() => document.body ? document.body.innerText.split('\\n').map(s => s.trim()).filter(Boolean).slice(0, 3000) : []"

# 자동 검사가 다루지 못하는 요소가 페이지에 있는지
PAGE_FEATURES_JS = """
() => ({
  iframe: document.querySelectorAll('iframe').length,
  canvas: document.querySelectorAll('canvas').length,
  select: document.querySelectorAll('select').length,
  fileinput: document.querySelectorAll('input[type=file]').length,
  media: document.querySelectorAll('video, audio').length,
})
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
def state_hash(page, with_values=False):
    try:
        text = page.evaluate(STATE_JS)
        if with_values:
            text += "|" + page.evaluate(FIELD_VALUES_JS)
        return hashlib.md5(text.encode("utf-8")).hexdigest()
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
        self.findings = {}   # (구분, 내용) -> [(위치, 수동 체크 흐름), ...]
        self.features = Counter()     # iframe/canvas 등 자동 검사 범위 밖 요소 수
        self.hidden_pending = {}      # url -> {(tag, text)}: 처음에 숨겨져 있던 클릭 요소
        self.route_visible = {}       # url -> {(tag, text)}: 처음에 보이던 클릭 요소
        self.has_pw_form = False
        self.has_form = False
        self.saw_download = False
        self.clicks_used = 0
        self.tested_children = set()  # 이미 검사한 '클릭 후 나타난 버튼'
        self.pw_forms = []            # 비밀번호 칸이 있는 폼(가입 → 로그인 연속 검사용)
        self.chain_passed = False
        self.last_had_error = False
        self.login_state_checked = False
        self.cal_status = set()       # 캘린더 점검 결과 종류: 일치/불일치/확인 필요
        self.cal_lib_noted = set()
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
    def add(self, level, where, msg, flow=""):
        locs = self.findings.setdefault((level, msg), [])
        if all(w != where for w, _ in locs):
            locs.append((where, flow))

    # ── 수동 체크 흐름(사람이 그대로 따라 할 순서) 만들기 ──
    def open_step(self, url):
        name = self.route_name(url)
        if name == "메인":
            return f"{self.file.name} 열기"
        return f"{self.file.name} 열기 → 주소 끝에 '{name}' 붙여 이동"

    def click_step(self, url, label):
        return f"{self.open_step(url)} → '{label}' 클릭"

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
        self.wait_settled()

    def wait_settled(self):
        """
        화면 지문이 연속 두 번 같아질 때까지 대기.
        지도 타일 페이드인처럼 '클릭과 무관하게' 바뀌는 DOM을 클릭 반응으로 오인하지 않기 위함.
        """
        prev, waited = state_hash(self.page), 0
        while waited < SETTLE_MAX_MS:
            self.page.wait_for_timeout(SETTLE_POLL_MS)
            waited += SETTLE_POLL_MS
            cur = state_hash(self.page)
            if cur == prev:
                return True
            prev = cur
        return False

    def has_click_handler(self, selector):
        """
        요소 자신~조상~document~window 중 어디에도 클릭 계열 이벤트 리스너가 없으면 False.
        (onclick 속성, addEventListener, 부모 위임 방식 모두 포함. Chromium CDP 사용)
        확인 자체가 실패하면 None.
        """
        try:
            if getattr(self, "_cdp", None) is None:
                self._cdp = self.context.new_cdp_session(self.page)
            cdp = self._cdp
            expr = ("(() => { const a = []; let e = document.querySelector(%s);"
                    " if (!e) return null; while (e) { a.push(e); e = e.parentNode; } a.push(window); return a; })()" % json.dumps(selector))
            res = cdp.send("Runtime.evaluate", {"expression": expr})
            oid = res.get("result", {}).get("objectId")
            if not oid:
                return None
            props = cdp.send("Runtime.getProperties", {"objectId": oid, "ownProperties": True})
            for prop in props["result"]:
                if not prop["name"].isdigit():
                    continue
                ls = cdp.send("DOMDebugger.getEventListeners", {"objectId": prop["value"]["objectId"]})["listeners"]
                if any(l["type"] in CLICK_EVENT_TYPES for l in ls):
                    return True
            return False
        except PWError:
            return None

    def flush_errors(self, where, flow=""):
        """events 중 에러성 항목을 기록하고 나머지(다운로드 등)를 반환"""
        rest = []
        self.last_had_error = any(k in ("jserror", "console", "resource", "brokenlink") for k, _ in self.events)
        console_flow = f"F12 → Console 탭 열어 둔 채로 {flow} → 빨간 오류 줄의 파일·줄 번호 확인"
        for kind, val in self.events:
            if kind == "jserror":
                if self.cdn_failed:
                    self.add("주의", where, f"JS 오류(외부 CDN 로드 실패 영향 가능성): {val}",
                             console_flow + f" (인터넷 연결·CDN 확인: {', '.join(sorted(self.cdn_failed))[:60]})")
                else:
                    self.add("오류", where, f"JS 오류: {val}", console_flow)
            elif kind == "console":
                self.add("경고", where, f"콘솔 오류: {val}", console_flow)
            elif kind in ("resource", "brokenlink"):
                self.add("오류", where, val,
                         f"F12 → Network 탭 열어 둔 채로 {flow} → 빨간(404) 항목의 경로와 실제 파일 위치·대소문자 비교")
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
                self.add("오류", self.route_name(url), f"화면 로드 실패: {str(e).split(chr(10))[0][:80]}",
                         f"{self.open_step(url)} → 화면이 열리는지 확인")
                continue
            routes.append(url)
            name = self.route_name(url)
            self.flush_errors(f"{name} 로드", self.open_step(url))
            for src in self.page.evaluate(BROKEN_IMG_JS):
                self.add("오류", name, f"깨진 이미지: {src}",
                         f"{self.open_step(url)} → 이미지 '{src}' 자리가 비어 있는지 확인 → 실제 파일 경로·대소문자 비교")
            # 자동 검사 범위 확인용 정보
            try:
                for k, v in self.page.evaluate(PAGE_FEATURES_JS).items():
                    self.features[k] = max(self.features[k], v)
                self.hidden_pending[url] = {tuple(x) for x in self.page.evaluate(HIDDEN_CLICKABLES_JS, CLICKABLE_SELECTOR)}
            except PWError:
                pass
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
                        self.add("오류", name, f"존재하지 않는 파일로 연결: {unquote(p.path).lstrip('/')}",
                                 f"{self.open_step(url)} → href='{raw}' 링크 클릭 → 화면이 열리는지 확인")
                    continue
                # 같은 파일 내부 화면
                if (p.query or p.fragment) and absu not in seen and not raw.startswith("#main") and raw not in ("#", "#content", "#top"):
                    seen.add(absu)
                    key = pattern(raw)
                    pat_count[key] += 1
                    if pat_count[key] <= SAME_PATTERN_LIMIT:
                        queue.append(absu)
                    else:
                        self.add("수동", f"{name} > 화면 '{raw}'", "같은 형태의 화면(예: 상세 페이지)은 일부만 자동 검사(샘플링)",
                                 f"{self.open_step(url)} → '{raw}' 링크 클릭 → 화면 내용·버튼 확인")
        if queue:
            self.add("수동", f"미방문 화면 {len(queue)}개", f"화면 탐색 제한(MAX_ROUTES={MAX_ROUTES}) 도달 — 일부 화면 미검사",
                     f"{self.file.name} 열기 → " + ", ".join(f"'{self.route_name(u)}'" for u in queue[:MAX_SAMPLES]) + " 등으로 이동해 확인")
        return routes

    # ── 2단계: 모든 클릭 요소 테스트 (+ 클릭 후 나타난 버튼까지 한 단계 더) ──
    def _prepare(self, url):
        """화면을 새로 열고 번호표를 다시 붙임(번호는 같은 화면이면 항상 같은 순서)"""
        self.goto(url)
        self.page.evaluate(TAG_ELEMENTS_JS, CLICKABLE_SELECTOR)
        self.events = []

    def _judge_click(self, selector, where, step, href):
        """
        selector 요소를 클릭하고 반응을 판정해 기록. (changed, url_changed)를 돌려줌.
        요소가 없으면 None. 클릭 예외는 호출한 쪽에서 처리.
        """
        loc = self.page.locator(selector)
        if loc.count() == 0:
            return None
        before_url, before_state = self.page.url, state_hash(self.page, with_values=True)
        handler = self.has_click_handler(selector)   # 클릭 전에 확인(클릭 후엔 화면이 바뀔 수 있음)
        loc.first.click(timeout=2000)
        self.clicks_used += 1
        self.page.wait_for_timeout(CLICK_WAIT_MS)
        self.wait_settled()
        after_url = self.page.url
        if after_url.startswith("chrome-error"):
            self.add("오류", where, "클릭 시 페이지 이동 실패", f"{step} → 이동한 화면이 열리는지 확인")
        after_state = state_hash(self.page, with_values=True)
        rest = self.flush_errors(where, step)
        self.check_downloads(rest, where, step)
        # 'page.html' → 'page.html#'처럼 해시만 바뀐 것은 화면이 그대로면 반응이 아님
        url_changed = before_url.split("#", 1)[0] != after_url.split("#", 1)[0]
        changed = url_changed or (before_state != after_state) or bool(rest)
        href = (href or "").strip()
        if not changed and self.last_had_error:
            pass   # 오류가 이미 원인으로 기록됨('반응 없음' 중복 방지)
        elif not changed and handler is False:
            self.add("경고", where, "클릭해도 반응 없음(연결된 클릭 이벤트가 전혀 없음 — 미구현 메뉴/버튼)",
                     f"{step} → 반응이 없으면 onclick·링크 연결 누락")
        elif not changed and href in DEAD_HREFS and href:
            self.add("주의", where, f"href='{href}' 링크 클릭 시 반응 없음",
                     f"{step} → 의도된 빈 링크인지 확인(아니면 실제 주소·동작 연결)")
        elif not changed and REPORT_NO_RESPONSE:
            self.add("경고", where, "클릭해도 반응 없음",
                     f"{step} → 1~2초 기다려 화면 변화·알림·이동이 있는지 확인")
        return changed, url_changed

    def _new_clickables(self, url):
        """지금 화면에서 '처음 화면에는 없던' 버튼에 data-qa-cid 번호표를 붙이고 목록을 돌려줌"""
        try:
            kids = self.page.evaluate(TAG_NEW_JS, [CLICKABLE_SELECTOR, [list(x) for x in self.route_visible.get(url, set())]])
        except PWError:
            return []
        pending = self.hidden_pending.get(url)
        if pending:
            pending -= {(k["tag"], k["text"]) for k in kids}   # 이 클릭으로 드러난 숨김 요소는 여기서 검사
        return kids

    def test_clicks(self, routes):
        tested = set()   # 화면이 달라도 같은 요소(헤더 메뉴 등)는 한 번만
        pat_count = Counter()
        plan = []
        for url in routes:
            try:
                self.goto(url)
                els = self.page.evaluate(TAG_ELEMENTS_JS, CLICKABLE_SELECTOR)
                self.route_visible[url] = {tuple(x) for x in self.page.evaluate(VISIBLE_SIGS_JS, CLICKABLE_SELECTOR)}
                for el in els:
                    if "바로가기" in el["text"] and el["href"].startswith("#"):
                        continue  # 키보드용 '본문 바로가기'는 평소 숨겨져 있어 제외
                    sig = (el["tag"], el["text"], el["href"], el["onclick"])
                    if sig in tested:
                        continue
                    tested.add(sig)
                    href_key = "" if el["href"].strip() in DEAD_HREFS else pattern(el["href"])
                    key = (el["tag"], pattern(el["onclick"]) or href_key or el["text"])
                    pat_count[key] += 1
                    if pat_count[key] > SAME_PATTERN_LIMIT:
                        label = el["text"] or el["href"] or el["onclick"] or el["tag"]
                        self.add("수동", f"{self.route_name(url)} > '{label}'",
                                 f"같은 형태로 반복되는 버튼/링크는 {SAME_PATTERN_LIMIT}개만 자동 검사(샘플링)",
                                 f"{self.click_step(url, label)} → 앞의 같은 종류 버튼과 똑같이 동작하는지 확인")
                        continue
                    plan.append((url, el))
            except PWError:
                continue
        if len(plan) > MAX_CLICKS_PER_FILE:
            cut = plan[MAX_CLICKS_PER_FILE:]
            names = ", ".join(f"'{e['text'] or e['href'] or e['tag']}'" for _, e in cut[:MAX_SAMPLES])
            self.add("수동", f"미검사 {len(cut)}개", f"클릭 제한(MAX_CLICKS_PER_FILE={MAX_CLICKS_PER_FILE}) 초과로 일부 요소 미검사",
                     f"{self.file.name} 열기 → {names} 등 직접 클릭 확인")
        plan = plan[:MAX_CLICKS_PER_FILE]
        self.events = []

        self.bar.reset(total=len(plan))
        dirty, cur_route = True, None
        for url, el in plan:
            label = el["text"] or el["href"] or el["onclick"] or el["tag"]
            where = f"{self.route_name(url)} > '{label}'"
            step = self.click_step(url, label)
            self.bar.set_postfix_str(f"클릭: {label[:20]}")
            try:
                if dirty or cur_route != url:
                    self._prepare(url)
                    cur_route = url
                res = self._judge_click(f'[data-qa-id="{el["id"]}"]', where, step, el["href"])
                if res is None:
                    dirty = True
                else:
                    changed, url_changed = res
                    dirty = changed
                    if changed and not url_changed:
                        kids = self._new_clickables(url)
                        if kids:
                            self.test_children(url, el, where, step, kids)
                            dirty = True
            except PWError as e:
                level, msg = classify_click_error(str(e))
                self.add(level, where, msg, f"{step} → 눌리는지, 다른 요소에 가려지거나 숨겨져 있지 않은지 확인")
                dirty = True
            self.bar.update(1)

    def test_children(self, url, parent, pwhere, pstep, kids):
        """
        클릭 깊이 2: 부모 버튼 클릭으로 나타난 버튼(모달 '확인'·'닫기', 드롭다운 항목, 탭 내용)을
        하나씩 [화면 새로 열기 → 부모 클릭 → 자식 클릭] 순서로 재현해 검사.
        """
        todo = []
        for k in kids:
            sig = (k["tag"], k["text"], k["href"])
            if sig not in self.tested_children:    # 같은 모달을 여러 버튼이 열어도 안쪽 버튼은 한 번만
                self.tested_children.add(sig)
                todo.append(k)
        if not todo:
            return
        limit = MAX_CHILD_CLICKS if CLICK_DEPTH >= 2 else 0
        run, rest = todo[:limit], todo[limit:]
        room = max(MAX_CLICKS_PER_FILE - self.clicks_used, 0)
        if len(run) > room:
            run, rest = run[:room], run[room:] + rest
        if rest:
            names = ", ".join(f"'{k['text']}'" for k in rest[:MAX_SAMPLES])
            more = f" 외 {len(rest) - MAX_SAMPLES}개" if len(rest) > MAX_SAMPLES else ""
            self.add("수동", f"{pwhere} 클릭 후 {len(rest)}개", "클릭 후 나타난 버튼 중 자동 검사 한도를 넘은 것",
                     f"{pstep} → 나타난 {names}{more} 각각 클릭 → 동작·닫기 확인")
        if not run:
            return
        self.bar.total += len(run)
        self.bar.refresh()
        for k in run:
            clabel = k["text"] or k["href"] or k["tag"]
            where = f"{pwhere} > '{clabel}'"
            step = f"{pstep} → 나타난 '{clabel}' 클릭"
            self.bar.set_postfix_str(f"클릭(2단계): {clabel[:15]}")
            try:
                self._prepare(url)
                self.page.locator(f'[data-qa-id="{parent["id"]}"]').first.click(timeout=2000)
                self.page.wait_for_timeout(CLICK_WAIT_MS)
                self.wait_settled()
                again = self.page.evaluate(TAG_NEW_JS, [CLICKABLE_SELECTOR, [list(x) for x in self.route_visible.get(url, set())]])
                match = next((x for x in again if (x["tag"], x["text"], x["href"]) == (k["tag"], k["text"], k["href"])), None)
                self.events = []   # 부모 클릭에서 난 오류는 이미 기록됨
                if match is None:
                    self.add("수동", where, "부모 버튼을 다시 눌렀을 때 같은 버튼이 나타나지 않아 자동 재현 실패",
                             f"{step} → 동작 확인")
                else:
                    self._judge_click(f'[data-qa-cid="{match["cid"]}"]', where, step, k["href"])
            except PWError as e:
                level, msg = classify_click_error(str(e))
                self.add(level, where, msg, f"{step} → 눌리는지, 다른 요소에 가려지거나 숨겨져 있지 않은지 확인")
            self.bar.update(1)

    # ── 2-2단계: hover로만 열리는 메뉴 검사 ──
    def test_hidden(self):
        """처음에 숨겨져 있던 메뉴 항목을, 가장 가까운 '보이는 상위 요소'에 마우스를 올려 드러낸 뒤 클릭"""
        if not HOVER_TEST:
            return
        targets = [(url, sig) for url, pend in self.hidden_pending.items() for sig in sorted(pend)]
        targets = targets[:MAX_HOVER_TESTS]
        if not targets:
            return
        self.bar.reset(total=len(targets))
        for url, (tag, text) in targets:
            if self.clicks_used >= MAX_CLICKS_PER_FILE:
                break
            self.bar.set_postfix_str(f"hover: {text[:15]}")
            try:
                self._prepare(url)
                info = self.page.evaluate(HOVER_PREP_JS, [CLICKABLE_SELECTOR, tag, text])
                if not info:
                    self.bar.update(1)
                    continue
                self.page.hover("[data-qa-hover]", timeout=2000)
                self.page.wait_for_timeout(CLICK_WAIT_MS)
                if not self.page.locator("[data-qa-hid]").first.is_visible():
                    self.bar.update(1)
                    continue   # hover로 안 열림 → '수동' 항목으로 남김
                self.hidden_pending[url].discard((tag, text))
                where = f"{self.route_name(url)} > '{info}'(마우스 올림) > '{text}'"
                step = f"{self.open_step(url)} → '{info}'에 마우스 올리기 → 나타난 '{text}' 클릭"
                self.events = []
                self._judge_click("[data-qa-hid]", where, step, "")
            except PWError as e:
                level, msg = classify_click_error(str(e))
                self.add(level, f"{self.route_name(url)} > '{text}'(hover 메뉴)", msg,
                         f"{self.open_step(url)} → 상위 메뉴에 마우스 올리기 → '{text}' 클릭되는지 확인")
            self.bar.update(1)

    def check_downloads(self, events, where, flow=""):
        for kind, val in events:
            if kind != "download":
                continue
            self.saw_download = True
            dl_flow = f"{flow} → 다운로드 폴더에 파일이 생기는지, 열리는지 확인"
            try:
                fail = val.failure()
                if fail:
                    self.add("오류", where, f"다운로드 실패: {fail}", dl_flow)
                    continue
                dest = self.dl_dir / (val.suggested_filename or "file")
                val.save_as(dest)
                if dest.stat().st_size == 0:
                    self.add("오류", where, f"다운로드 파일이 비어 있음(0바이트): {dest.name}", dl_flow)
                else:
                    self.add("수동", where, "다운로드는 '파일 생성'만 확인 — 파일 내용은 미검증",
                             f"{flow} → 받은 '{dest.name}'을 열어 내용·한글 깨짐 확인")
            except PWError as e:
                self.add("오류", where, f"다운로드 오류: {str(e).split(chr(10))[0][:80]}", dl_flow)

    # ── 3단계: 폼(로그인/회원가입/검색 등) 테스트 ──
    def _submit_form(self, idx):
        """폼 idx를 채워 제출. (info, changed, 새로 나타난 문구·알림 목록, rest)를 돌려줌"""
        info = self.page.evaluate(FILL_FORM_JS, idx)
        if not info:
            return None, False, [], []
        before_url, before_state = self.page.url, state_hash(self.page)
        before_text = set(self.page.evaluate(TEXT_LINES_JS))
        self.page.evaluate("(i) => { const f = document.querySelectorAll('form')[i]; f.requestSubmit ? f.requestSubmit() : f.submit(); }", idx)
        self.page.wait_for_timeout(CLICK_WAIT_MS + 200)
        self.wait_settled()
        try:
            new_text = [t for t in self.page.evaluate(TEXT_LINES_JS) if t not in before_text]
        except PWError:
            new_text = []
        changed = (before_url.split("#", 1)[0] != self.page.url.split("#", 1)[0]
                   or before_state != state_hash(self.page))
        return info, changed, new_text, []

    @staticmethod
    def _fail_message(new_text, dialogs):
        """새로 나타난 문구·알림 중 '실패'로 보이는 것을 찾음"""
        for t in list(dialogs) + list(new_text):
            low = t.lower()
            if any(w in low for w in FAIL_WORDS):
                return t[:60]
        return ""

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
                peek = self.page.evaluate(FORM_PEEK_JS, idx)
                if not peek or peek["name"] in done_names:
                    self.bar.update(1)
                    continue
                done_names.add(peek["name"])
                kind = ("회원가입 폼" if peek["signup"] else "로그인 폼") if peek["pw"] else "폼"
                where = f"{self.route_name(url)} > {kind}({peek['name']})"
                fstep = (f"{self.open_step(url)} → {kind}({peek['name']})에 값 입력"
                         f"(예: qa_tester@example.com / Test1234!@) → 제출")
                self.has_form = True
                if peek["pw"]:
                    self.has_pw_form = True
                    self.pw_forms.append({"url": url, "idx": idx, "name": peek["name"], "signup": peek["signup"],
                                          "where": where, "kind": kind})
                    self.add("수동", where, "로그인/회원가입 실제 사용 흐름(정상·실패·로그아웃)은 직접 확인",
                             f"{self.open_step(url)} → 회원가입 완료 → 같은 계정으로 로그인 → 로그인 상태 표시·로그아웃 확인"
                             f" → 틀린 비밀번호·빈 값으로 로그인 시 오류 문구 확인")
                else:
                    self.add("수동", where, "폼 입력값 검증(빈 값·잘못된 형식)은 자동 미검사",
                             f"{self.open_step(url)} → {kind}({peek['name']})를 빈 값으로 제출 → 안내 문구 확인 → 정상 값으로 제출 → 결과 확인")
                if struct and struct["noTarget"]:
                    self.add("주의", where, "action·onsubmit·submit 리스너가 모두 없는 <form> 태그 (전송 대상 불명)",
                             f"{fstep} → 제출 후 무슨 일이 일어나야 하는지 기획과 비교")
                info, changed, new_text, _ = self._submit_form(idx)
                if self.page.url.startswith("chrome-error"):
                    self.add("오류", where, "제출 후 페이지 이동 실패", f"{fstep} → 이동한 화면이 열리는지 확인")
                rest = self.flush_errors(where, fstep)
                self.check_downloads(rest, where, fstep)
                dialogs = [v for k, v in rest if k == "dialog"]
                changed = changed or bool(rest)
                if not changed:
                    invalid = self.page.evaluate("(i) => !document.querySelectorAll('form')[i]?.checkValidity()", idx)
                    if invalid:
                        self.add("경고", where, "테스트 값을 넣어도 입력 검증을 통과하지 못함(필수값/형식 확인 필요)",
                                 f"{fstep} → 어떤 칸에서 막히는지(빨간 안내) 확인 → required·pattern·minlength 조건 확인")
                    elif peek["pw"]:
                        self.add("오류", where, "제출해도 반응 없음(로그인/가입 처리 안 됨)",
                                 f"{fstep} → 완료 문구·화면 전환이 있는지 확인")
                    else:
                        self.add("경고", where, "제출해도 반응 없음", f"{fstep} → 결과 화면·메시지가 있는지 확인")
                elif peek["pw"]:
                    fail = self._fail_message(new_text, dialogs)
                    if fail:
                        self.add("주의" if not peek["signup"] else "경고", where,
                                 f"테스트 값으로 제출 시 실패 문구 표시: '{fail}'",
                                 f"{fstep} → '{fail}' 문구가 맞는 상황인지 확인(가입된 계정이 필요한 로그인이면 정상일 수 있음)")
            except PWError as e:
                self.add("오류", f"{self.route_name(url)} 폼#{idx}", f"제출 실패: {str(e).split(chr(10))[0][:80]}",
                         f"{self.open_step(url)} → {idx + 1}번째 폼에 값 입력 → 제출")
            self.bar.update(1)
        self.test_login_chain()

    def _login_state(self, login_idx):
        conf = LOGIN_STATE_SELECTORS.get(self.file.name, {})
        try:
            return self.page.evaluate(LOGIN_STATE_JS, [list(GUEST_WORDS), list(MEMBER_WORDS),
                                                       conf.get("guest", []), conf.get("member", []), login_idx])
        except PWError:
            return None

    def _back_to(self, url):
        """로그인 화면으로 돌아가기. 같은 파일이면 새로고침 없이(메모리 기록이 지워지지 않게)"""
        now, want = urlparse(self.page.url), urlparse(url)
        if now.path != want.path or now.query != want.query:
            self.goto(url)
        elif now.fragment != want.fragment:
            self.page.evaluate("(h) => { location.hash = h; }", want.fragment)
            self.page.wait_for_timeout(LOAD_WAIT_MS)
            self.wait_settled()

    def _make_guest_records(self, l):
        """
        비회원 상태에서 '담기·찜·저장' 같은 버튼과 검색·메모 폼으로 기록을 남기고,
        그때 새로 생긴 화면 글자와 저장소 값을 돌려줌. 로그인 후 이것이 남아 있으면 초기화 안 된 것.
        """
        conf = LOGIN_STATE_SELECTORS.get(self.file.name, {})
        try:
            base_text = set(self.page.evaluate(TEXT_LINES_JS))
            base_store = self.page.evaluate(STORAGE_JS)
            tried, done = [], []
            for _ in range(GUEST_ACTION_MAX):
                t = self.page.evaluate(GUEST_ACTION_JS, [list(GUEST_RECORD_WORDS), tried, conf.get("guest_actions", [])])
                if not t:
                    break
                tried.append(t)
                try:
                    self.page.locator("[data-qa-gact]").first.click(timeout=1500)
                    self.page.wait_for_timeout(CLICK_WAIT_MS)
                    self.wait_settled()
                    done.append(f"'{t}' 클릭")
                except PWError:
                    pass
                self._back_to(l["url"])
            for idx in self.page.evaluate(PLAIN_FORMS_JS)[:GUEST_FORM_MAX]:
                try:
                    self.page.evaluate(FILL_FORM_JS, idx)
                    self.page.evaluate("(i) => { const f = document.querySelectorAll('form')[i]; f.requestSubmit ? f.requestSubmit() : f.submit(); }", idx)
                    self.page.wait_for_timeout(CLICK_WAIT_MS)
                    self.wait_settled()
                    done.append(f"{idx + 1}번째 폼(검색·메모 등) 제출")
                except PWError:
                    pass
                self._back_to(l["url"])
            self.events = []
            lines = [x for x in self.page.evaluate(TEXT_LINES_JS)
                     if x not in base_text and not GUEST_MESSAGE_RE.search(x)][:50]
            now_store = self.page.evaluate(STORAGE_JS)
            store = {k: v for k, v in now_store.items() if base_store.get(k) != v}
        except PWError:
            return None
        if not (lines or store):
            return None
        return {"lines": lines, "store": store, "done": done}

    def _check_guest_records(self, rec, where, flow):
        """로그인 직후: 비회원 때 생긴 화면 글자·저장값이 그대로 남아 있는지"""
        try:
            now_text = set(self.page.evaluate(TEXT_LINES_JS))
            now_store = self.page.evaluate(STORAGE_JS)
        except PWError:
            return
        left_lines = [x for x in rec["lines"] if x in now_text]
        left_store = [k for k, v in rec["store"].items() if now_store.get(k) == v]
        if not (left_lines or left_store):
            return
        parts = []
        if left_store:
            parts.append("저장값 " + ", ".join(f"'{k.split(':', 1)[1]}'" for k in left_store[:MAX_SAMPLES]))
        if left_lines:
            parts.append("화면 " + ", ".join(f"'{x[:20]}'" for x in left_lines[:MAX_SAMPLES]))
        acts = ", ".join(rec["done"][:MAX_SAMPLES]) or "기록 남기기"
        self.add("경고", where, "로그인 후에도 비회원 때 남긴 기록이 초기화되지 않음: " + " / ".join(parts),
                 f"{self.open_step(self.pw_forms[0]['url'])} → 비회원 상태로 {acts} → 가입·로그인"
                 f" → 비회원 때 기록(장바구니·찜·검색 기록 등)이 사라졌는지 확인")

    def check_login_state(self, l, before, where, flow, guest_rec=None):
        """
        로그인 성공 후: 비로그인용 버튼·안내가 사라지고 로그인 표시로 바뀌었는지, 입력값이 비워졌는지.
        로그아웃 후: 반대로 원래 비로그인 화면으로 돌아왔는지.
        """
        if guest_rec:
            self._check_guest_records(guest_rec, where, flow)
        after = self._login_state(l["idx"])
        if after is None:
            return
        self.login_state_checked = True
        step = flow + " → 로그인 완료 직후 화면 확인"
        new_member = [w for w in after["member"] if w not in before["member"]]
        still_guest = [g for g in before["guest"] if g in after["guest"]]
        if still_guest:
            self.add("경고", where, "로그인 후에도 비로그인용 버튼이 그대로 보임: " + ", ".join(f"'{g}'" for g in still_guest),
                     step + " → 해당 버튼이 사라지고 로그아웃·내 정보 등으로 바뀌는지 확인")
        if after["loginFormVisible"]:
            self.add("경고", where, "로그인 후에도 로그인 입력창(폼)이 닫히지 않고 보임",
                     step + " → 로그인 창이 닫히거나 다른 화면으로 바뀌는지 확인")
        if not new_member and not after["memberSel"]:
            self.add("경고", where, "로그인 후 로그인 상태 표시(로그아웃 버튼·사용자 이름 등)가 나타나지 않음",
                     step + " → 로그인한 사람이 로그인 상태임을 알 수 있는지 확인")
        if after["pwVisible"] or after["typedVisible"]:
            self.add("경고", where, "로그인 후에도 입력했던 아이디·비밀번호가 화면 입력칸에 그대로 남아 있음(초기화 안 됨)",
                     step + " → 입력칸이 비워졌는지 확인")
        elif after["pwAny"]:
            self.add("주의", where, "로그인 후 숨겨진 입력칸에 비밀번호가 남아 있음(로그인 창을 다시 열면 보일 수 있음)",
                     step + " → 로그아웃 후 로그인 창을 다시 열어 입력칸이 비어 있는지 확인")
        for sel in after["guestSel"]:
            self.add("경고", where, f"로그인 후에도 비로그인 전용 요소가 보임: {sel}", step + f" → '{sel}' 요소가 사라지는지 확인")
        conf = LOGIN_STATE_SELECTORS.get(self.file.name, {})
        for sel in conf.get("member", []):
            if sel not in after["memberSel"]:
                self.add("경고", where, f"로그인 후 회원 전용 요소가 보이지 않음: {sel}", step + f" → '{sel}' 요소가 나타나는지 확인")

        # ── 로그아웃 → 원래대로 ──
        try:
            label = self.page.evaluate(LOGOUT_TAG_JS)
            if not label:
                self.add("수동", where, "로그아웃 버튼을 찾지 못해 '로그아웃 후 원래대로' 검사 생략",
                         flow + " → 로그아웃 → 로그인·회원가입 버튼이 돌아오고 입력칸이 비어 있는지 확인")
                return
            self.events = []
            self.page.locator("[data-qa-logout]").first.click(timeout=2000)
            self.page.wait_for_timeout(CLICK_WAIT_MS)
            self.wait_settled()
            ostep = flow + f" → '{label}' 클릭(로그아웃) → 화면 확인"
            self.flush_errors(where, ostep)
            out = self._login_state(l["idx"])
            if out is None:
                return
            left = [w for w in out["member"] if w not in before["member"]]
            if left:
                self.add("경고", where, "로그아웃 후에도 로그인 상태 표시가 남아 있음: " + ", ".join(f"'{w}'" for w in left),
                         ostep + " → 로그인 상태 표시가 모두 사라지는지 확인")
            missing = [g for g in before["guest"] if g not in out["guest"]]
            if missing:
                self.add("경고", where, "로그아웃 후 비로그인용 버튼이 다시 나타나지 않음: " + ", ".join(f"'{g}'" for g in missing),
                         ostep + " → 처음 화면처럼 로그인·회원가입 버튼이 돌아오는지 확인")
            if out["pwAny"] or out["typedAny"]:
                self.add("경고", where, "로그아웃 후에도 이전에 입력한 아이디·비밀번호가 입력칸에 남아 있음(초기화 안 됨)",
                         ostep + " → 로그인 창을 다시 열어 입력칸이 비어 있는지 확인")
            conf_g = conf.get("guest", [])
            for sel in conf_g:
                if sel in before["guestSel"] and sel not in out["guestSel"]:
                    self.add("경고", where, f"로그아웃 후 비로그인 전용 요소가 돌아오지 않음: {sel}", ostep + f" → '{sel}' 확인")
            for sel in out["memberSel"]:
                self.add("경고", where, f"로그아웃 후에도 회원 전용 요소가 보임: {sel}", ostep + f" → '{sel}' 사라지는지 확인")
        except PWError as e:
            self.add("수동", where, f"로그아웃 검사 중 중단: {str(e).split(chr(10))[0][:60]}", flow + " → 로그아웃 직접 확인")

    def test_login_chain(self):
        """
        회원가입 폼과 로그인 폼이 모두 있으면, 같은 브라우저 세션에서
        [가입(qa_tester@example.com / Test1234!@) → 같은 값으로 로그인]을 이어서 해 보고 실패 여부를 판정.
        부장님의 '로그인이 안 된다'는 대부분 이 흐름에서 나옴.
        """
        if not LOGIN_CHAIN_TEST:
            return
        signups = [f for f in self.pw_forms if f["signup"]]
        logins = [f for f in self.pw_forms if not f["signup"]]
        if not signups or not logins:
            return
        s, l = signups[0], logins[0]
        flow = (f"{self.open_step(s['url'])} → {s['kind']}({s['name']})에 qa_tester@example.com / Test1234!@로 가입"
                f" → {('같은 화면' if s['url'] == l['url'] else '주소 끝에 ' + repr(self.route_name(l['url'])) + ' 붙여 이동')}"
                f" → {l['kind']}({l['name']})에 같은 값으로 로그인")
        where = f"{s['where']} → {l['where']}"
        try:
            self.goto(s["url"])
            self.events = []
            info, changed, new_text, _ = self._submit_form(s["idx"])
            rest = self.flush_errors(where, flow)
            fail = self._fail_message(new_text, [v for k, v in rest if k == "dialog"])
            if not (changed or rest) or fail:
                self.add("수동", where, "자동 회원가입이 완료되지 않아 '가입 → 로그인' 연속 검사 생략" + (f"(문구: '{fail}')" if fail else ""),
                         flow + " → 직접 확인")
                return
            reloaded = False
            if l["url"] != s["url"]:
                if urlparse(l["url"]).path == urlparse(s["url"]).path and urlparse(l["url"]).fragment:
                    # 같은 파일 안 화면 전환은 새로고침 없이(메모리에 저장한 계정이 지워지지 않게)
                    self.page.evaluate("(h) => { location.hash = h; }", urlparse(l["url"]).fragment)
                    self.page.wait_for_timeout(LOAD_WAIT_MS)
                    self.wait_settled()
                else:
                    self.goto(l["url"])
                    reloaded = True
            self.events = []
            guest_rec = self._make_guest_records(l) if GUEST_RECORD_TEST else None   # 비회원 기록 남기기
            guest_state = self._login_state(l["idx"])   # 로그인 직전(비로그인) 화면 상태
            info, changed, new_text, _ = self._submit_form(l["idx"])
            rest = self.flush_errors(where, flow)
            fail = self._fail_message(new_text, [v for k, v in rest if k == "dialog"])
            for key in [k for k in self.findings if k[0] == "주의" and k[1].startswith("테스트 값으로 제출 시 실패 문구")]:
                self.findings[key] = [(w, f) for w, f in self.findings[key] if w != l["where"]]
                if not self.findings[key]:
                    del self.findings[key]
            # 화면 이동에 새로고침이 끼면 메모리에만 저장한 계정은 사라짐 → 실제 사용 흐름과 다를 수 있어 '경고'
            level = "경고" if reloaded else "오류"
            note = " (검사 중 새로고침이 있었음 — 실제 화면 흐름으로 다시 확인)" if reloaded else ""
            if fail:
                self.add(level, where, f"회원가입한 계정으로 로그인 실패: '{fail}'{note}",
                         flow + f" → '{fail}' 대신 로그인 완료가 되는지 확인(가입 정보 저장·비교 코드 확인)")
            elif not (changed or rest):
                self.add(level, where, f"회원가입 후 같은 계정으로 로그인해도 반응 없음{note}",
                         flow + " → 로그인 완료 화면·문구가 나오는지 확인")
            else:
                self.chain_passed = True
                if LOGIN_STATE_TEST and guest_state is not None:
                    self.check_login_state(l, guest_state, where, flow, guest_rec)
        except PWError as e:
            self.add("수동", where, f"'가입 → 로그인' 연속 검사 중 중단: {str(e).split(chr(10))[0][:60]}", flow + " → 직접 확인")

    # ── 4단계: 캘린더 표시 범위(부장님 요구사항) ──
    def _cal_scan(self):
        try:
            return self.page.evaluate(CAL_SCAN_JS)
        except PWError:
            return None

    def _cal_probe(self, url, i, direction):
        """캘린더 i에서 '이전'/'다음'을 막힐 때까지 눌러 끝 달을 찾음. (끝 달, 막혔는지)"""
        self.goto(url)
        scan = self._cal_scan()
        if not scan or i >= len(scan["cals"]):
            return None, False
        month = scan["cals"][i]["month"]
        for _ in range(CALENDAR_MAX_STEPS):
            loc = self.page.locator(f'[data-qa-cal-{direction}="{i}"]')
            try:
                if loc.count() == 0 or not loc.first.is_visible() or loc.first.is_disabled():
                    return month, True
                if loc.first.evaluate("e => e.getAttribute('aria-disabled') === 'true' || /(^|\\s)disabled(\\s|$)/.test(e.className || '')"):
                    return month, True
                loc.first.click(timeout=1500)
            except PWError:
                return month, True
            self.page.wait_for_timeout(250)
            scan = self._cal_scan()
            if not scan or i >= len(scan["cals"]):
                return month, True
            new = scan["cals"][i]["month"]
            if new == month:
                return month, True     # 눌러도 달이 안 바뀜 = 끝
            month = new
        return month, False            # 끝까지 눌러도 계속 이동됨 = 제한 없음

    @staticmethod
    def _range_issues(lo, hi):
        """lo/hi: 'YYYY-MM' 또는 None(제한 없음). 요구 범위와 다른 점 목록"""
        s, e = CALENDAR_START, CALENDAR_END
        out = []
        if lo is None:
            out.append(f"{s} 이전으로도 계속 이동됨" if CALENDAR_MODE == "exact" else "")
        elif lo > s:
            out.append(f"{s}을(를) 볼 수 없음(첫 달 {lo})")
        elif lo < s and CALENDAR_MODE == "exact":
            out.append(f"{lo}까지 이전 달로 이동됨")
        if hi is None:
            out.append(f"{e} 이후로도 계속 이동됨" if CALENDAR_MODE == "exact" else "")
        elif hi < e:
            out.append(f"{e}까지 볼 수 없음(마지막 달 {hi})")
        elif hi > e and CALENDAR_MODE == "exact":
            out.append(f"{hi}까지 다음 달로 이동됨")
        return [x for x in out if x]

    def _cal_result(self, where, what, lo, hi, flow, extra=""):
        want = f"{CALENDAR_START} ~ {CALENDAR_END}"
        got = f"{lo or '제한 없음'} ~ {hi or '제한 없음'}"
        issues = self._range_issues(lo, hi)
        if issues:
            self.cal_status.add("불일치")
            self.add("요구사항", where, f"[불일치] 캘린더 표시 범위가 요구와 다름: {what} 실제 {got} / 요구 {want} — {', '.join(issues)}{extra}",
                     flow + f" → 요구 {want}과 비교")
        else:
            self.cal_status.add("일치")
            self.add("요구사항", where, f"[일치] 캘린더 표시 범위 {got}({what}){extra}", flow + " → 확인만")

    def test_calendars(self, routes):
        if not CALENDAR_CHECK:
            return
        self.bar.reset(total=max(len(routes), 1))
        seen_inputs, seen_titles = set(), set()
        for url in routes:
            self.bar.set_postfix_str("캘린더")
            try:
                self.goto(url)
                scan = self._cal_scan()
            except PWError:
                scan = None
            if not scan:
                self.bar.update(1)
                continue
            name = self.route_name(url)
            found = False
            # 1) 화면에 보이는 캘린더: 이전·다음을 끝까지 눌러 범위 측정
            for c in scan["cals"]:
                key = (c["prev"], c["next"], c["text"])
                if key in seen_titles:
                    continue
                seen_titles.add(key)
                found = True
                where = f"{name} > 캘린더('{c['text']}')"
                if not c["visible"]:
                    self.cal_status.add("확인 필요")
                    self.add("요구사항", where, "[확인 필요] 숨겨진 캘린더(팝업·탭 안 등) — 자동 범위 검사 못 함",
                             f"{self.open_step(url)} → 캘린더를 열고 '이전'·'다음'을 끝까지 눌러 첫 달·마지막 달 확인 → 요구 {CALENDAR_START} ~ {CALENDAR_END}과 비교")
                    continue
                flow = (f"{self.open_step(url)} → 캘린더('{c['text']}')에서 '이전'을 끝까지 눌러 첫 달 확인"
                        f" → '다음'을 끝까지 눌러 마지막 달 확인")
                lo, lo_blocked = (self._cal_probe(url, c["i"], "prev") if c["prev"] else (c["month"], True))
                hi, hi_blocked = (self._cal_probe(url, c["i"], "next") if c["next"] else (c["month"], True))
                if lo is None or hi is None:
                    self.cal_status.add("확인 필요")
                    self.add("요구사항", where, "[확인 필요] 캘린더 이동 중 다시 찾지 못해 범위 측정 실패", flow)
                    continue
                self._cal_result(where, "이전·다음 버튼", lo if lo_blocked else None, hi if hi_blocked else None, flow,
                                 f" (처음 표시 {c['month']})")
            # 2) date/month 입력칸: min·max 속성
            for d in scan["inputs"]:
                key = (d["type"], d["name"])
                if key in seen_inputs:
                    continue
                seen_inputs.add(key)
                found = True
                where = f"{name} > 날짜 입력칸({d['name']})"
                flow = f"{self.open_step(url)} → 날짜 입력칸({d['name']}) 달력을 열어 선택 가능한 첫 날·마지막 날 확인"
                if d["type"] == "week":
                    self.cal_status.add("확인 필요")
                    self.add("요구사항", where, "[확인 필요] 주 단위 입력칸(type=week)은 자동 범위 판정 안 함", flow)
                    continue
                lo, hi = (d["min"][:7] or None), (d["max"][:7] or None)
                extra = ""
                if CALENDAR_MODE == "exact":
                    if d["type"] == "date" and d["min"] and not d["min"].endswith("-01"):
                        extra += f" / 시작일 {d['min']}(1일 아님)"
                    if d["type"] == "date" and d["max"] and d["max"][:7] == CALENDAR_END:
                        y, m = map(int, CALENDAR_END.split("-"))
                        last = calendar.monthrange(y, m)[1]
                        if d["max"] != f"{CALENDAR_END}-{last:02d}":
                            extra += f" / 종료일 {d['max']}(말일 {last}일 아님)"
                if extra:
                    self.cal_status.add("불일치")
                    self.add("요구사항", where, f"[불일치] 캘린더 표시 범위가 요구와 다름: 입력칸 min~max {d['min'] or '없음'} ~ {d['max'] or '없음'}{extra}",
                             flow + f" → 요구 {CALENDAR_START} ~ {CALENDAR_END}과 비교")
                else:
                    self._cal_result(where, "입력칸 min·max", lo, hi, flow)
            # 3) 월 선택 상자
            for sct in scan["selects"]:
                found = True
                where = f"{name} > 월 선택({sct['name']})"
                flow = f"{self.open_step(url)} → 월 선택 상자({sct['name']})를 펼쳐 첫·마지막 항목 확인"
                self._cal_result(where, "선택 항목", sct["months"][0], sct["months"][-1], flow)
            # 4) '10월' 같은 월 탭: 요구 월 목록과 비교(연도는 모름)
            if len(scan["tabs"]) >= 3:
                found = True
                want = self._want_months()
                have = set(scan["tabs"])
                missing = [m for m in want if m not in have]
                extra_m = sorted(have - set(want))
                where = f"{name} > 월 탭"
                flow = f"{self.open_step(url)} → 월 탭 목록 확인"
                if missing or (extra_m and CALENDAR_MODE == "exact"):
                    self.cal_status.add("불일치")
                    detail = []
                    if missing:
                        detail.append("없는 달 " + ", ".join(f"{m}월" for m in missing))
                    if extra_m and CALENDAR_MODE == "exact":
                        detail.append("범위 밖 달 " + ", ".join(f"{m}월" for m in extra_m))
                    self.add("요구사항", where, f"[불일치] 캘린더 표시 범위가 요구와 다름: 월 탭 — {' / '.join(detail)}",
                             flow + f" → 요구 {CALENDAR_START} ~ {CALENDAR_END}과 비교")
                else:
                    self.cal_status.add("일치")
                    self.add("요구사항", where, "[일치] 월 탭이 요구 달과 같음(연도는 직접 확인)", flow)
            # 5) 캘린더처럼 보이는데 형태를 모름
            if scan["lib"] and not found and name not in self.cal_lib_noted:
                self.cal_lib_noted.add(name)
                self.cal_status.add("확인 필요")
                self.add("요구사항", f"{name}", "[확인 필요] 캘린더·날짜 선택기로 보이는 요소가 있으나 자동 인식 못 함",
                         f"{self.open_step(url)} → 캘린더를 찾아 첫 달·마지막 달 확인 → 요구 {CALENDAR_START} ~ {CALENDAR_END}과 비교")
            self.bar.update(1)

    @staticmethod
    def _want_months():
        y, m = map(int, CALENDAR_START.split("-"))
        ey, em = map(int, CALENDAR_END.split("-"))
        out = []
        while (y, m) <= (ey, em) and len(out) < 12:
            out.append(m)
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return out

    def run(self):
        routes = []
        try:
            self.bar.reset(total=1)
            self.bar.set_description(f"  ├ {self.file.name[:25]} 화면 탐색")
            routes = self.discover_routes()
            self.bar.update(1)

            self.bar.set_description(f"  ├ {self.file.name[:25]} 클릭 검사")
            self.test_clicks(routes)

            self.bar.set_description(f"  ├ {self.file.name[:25]} hover 메뉴")
            self.test_hidden()

            self.bar.set_description(f"  └ {self.file.name[:25]} 폼 검사")
            self.test_forms(routes)

            self.bar.set_description(f"  └ {self.file.name[:25]} 캘린더")
            self.test_calendars(routes)
            self.report_coverage(routes)
        except Exception as e:  # 한 파일이 죽어도 전체는 계속
            self.add("오류", "전체", f"검수 중단: {type(e).__name__}: {str(e)[:100]}",
                     f"{self.file.name} 열기 → 화면이 정상적으로 열리는지, 콘솔 오류가 있는지 확인")
        finally:
            self.context.close()
        return len(routes)

    # ── 자동 검사가 보지 못한 범위를 '수동' 항목으로 정리 ──
    def report_coverage(self, routes):
        for url, pending in self.hidden_pending.items():
            if not pending:
                continue
            names = ", ".join(f"'{t}'" for _, t in sorted(pending)[:MAX_SAMPLES])
            more = f" 외 {len(pending) - MAX_SAMPLES}개" if len(pending) > MAX_SAMPLES else ""
            self.add("수동", f"{self.route_name(url)} 숨김 요소 {len(pending)}개",
                     "숨겨진 버튼/링크 중 클릭·마우스 올리기로도 자동으로 열지 못한 것",
                     f"{self.open_step(url)} → 메뉴에 마우스 올리기·펼치기 등으로 {names}{more} 표시 → 각각 클릭 확인")
        if self.chain_passed:
            extra = (" 및 로그인·로그아웃 화면 전환(일반 버튼 이름 기준) 검사 완료" if self.login_state_checked else "")
            self.add("수동", "로그인", f"자동 '회원가입 → 같은 계정 로그인' 검사는 통과(테스트 값 기준){extra}",
                     f"{self.file.name} 열기 → 로그인 → 이 페이지만의 비로그인 전용 요소(안내 배너·게스트 메뉴 등)가 사라지는지 확인"
                     f" → 로그아웃 → 원래대로 돌아오는지 확인 → 틀린 비밀번호로 로그인 시 오류 문구 확인")
        labels = {"iframe": "iframe 내부", "canvas": "canvas(차트·그림)", "select": "선택 상자(select) 옵션별 동작",
                  "fileinput": "파일 첨부(input type=file)", "media": "동영상·오디오 재생"}
        found = [labels[k] for k in labels if self.features[k]]
        if found:
            self.add("수동", "페이지 전체", f"자동 검사 범위 밖 요소 있음: {', '.join(found)}",
                     f"{self.file.name} 열기 → {', '.join(found)} 직접 조작해 동작 확인")
        if ADD_VISUAL_CHECK and routes:
            shown = ", ".join(f"'{self.route_name(u)}'" for u in routes[:MAX_SAMPLES])
            more = f" 외 {len(routes) - MAX_SAMPLES}개" if len(routes) > MAX_SAMPLES else ""
            self.add("수동", f"검사 화면 {len(routes)}개", "화면 배치·문구·오타·반응형은 자동 검사 대상 아님",
                     f"{self.file.name} 열기 → {shown}{more} 화면마다 글자 잘림·겹침·오타 확인 → 창 너비를 휴대폰 크기로 줄여 다시 확인")

    # ── CSV 행 만들기 ──
    def rows(self):
        out = []
        for name, label, text, flow in self._rows():
            row = [name, label, text]
            if DETAIL_COLUMNS:
                row += [flow] + [""] * len(CHECK_COLUMNS)
            out.append(row)
        return out

    def _rows(self):
        out = []
        rows = []
        for (level, msg), locs in self.findings.items():
            cat = feature_category(msg, " ".join(w for w, _ in locs))
            label, text = row_label(level, msg, cat)
            if label == "수동" and not SHOW_MANUAL:
                continue
            rows.append((ROW_ORDER.index(label), LEVEL_ORDER.index(level),
                         [self.file.name, label, self._text(text, locs), self._flow(locs)]))
        if not any(r[2][1] in ("수정", "오류", "경고", "주의") for r in rows):
            out.append([self.file.name, "정상", "-", "-"])
        out += [r for _, _, r in sorted(rows, key=lambda x: (x[0], x[1]))]
        return out

    def fix_categories(self):
        """이 파일에서 구분='수정'으로 나온 기능(요약 출력용)"""
        out = set()
        for (level, msg), locs in self.findings.items():
            cat = feature_category(msg, " ".join(w for w, _ in locs))
            if row_label(level, msg, cat)[0] == "수정":
                out.add(cat)
        return out

    def _text(self, msg, locs):
        if not (SHOW_LOCATION and locs):
            return msg
        shown = ", ".join(w for w, _ in locs[:MAX_LOCATIONS])
        more = f" 외 {len(locs) - MAX_LOCATIONS}곳" if len(locs) > MAX_LOCATIONS else ""
        return f"{msg} — 위치: {shown}{more}"

    def _flow(self, locs):
        flows = []
        for _, f in locs:
            if f and f not in flows:
                flows.append(f)
        if not flows:
            return "-"
        shown = flows[:MAX_LOCATIONS]
        text = "\n".join(f"{i}) {f}" for i, f in enumerate(shown, 1)) if len(shown) > 1 else shown[0]
        if len(flows) > MAX_LOCATIONS:
            text += f"\n(외 {len(flows) - MAX_LOCATIONS}곳 같은 방식으로 확인)"
        return text

    def worst_level(self):
        levels = {lv for lv, _ in self.findings}
        for lv in PROBLEM_LEVELS:
            if lv in levels:
                return lv
        return "정상"

# 비회원 기록 비교 때 빼는 안내 문구(토스트·알림 등)
GUEST_MESSAGE_RE = re.compile(r"(되었습니다|됐습니다|했습니다|완료|실패|오류|에러|하세요|해 ?주세요|비어 ?있|없습니다)")


def row_label(level, msg, cat):
    """
    결과 CSV의 (구분, 내용 앞부분) 결정.
    로그인·캘린더 문제 → 구분 '수정', 내용 '로그인 체크 필요(경고): …'
    캘린더 [일치] → '정상', [확인 필요] → '수동', 나머지는 원래 구분 그대로
    """
    body = re.sub(r"^\[(일치|불일치|확인 필요)\]\s*", "", msg)
    if level == "요구사항":
        if msg.startswith("[불일치]"):
            return ("수정", f"{cat} 체크 필요(요구사항 불일치): {body}") if cat in FIX_CATEGORIES else ("주의", body)
        if msg.startswith("[일치]"):
            return "정상", f"{cat}: {body}"
        return "주의", f"{cat} 체크 필요(자동 판정 불가): {body}"
    if level in PROBLEM_LEVELS and cat in FIX_CATEGORIES:
        return "수정", f"{cat} 체크 필요({level}): {msg}"
    if level == "수동" and cat in FIX_CATEGORIES:
        return level, f"{cat}: {msg}"
    return level, msg


def feature_category(msg, where=""):
    """결과 행의 기능 분류(엑셀 필터용). 위에서부터 먼저 맞는 것"""
    t = f"{msg} {where}"
    if "캘린더" in t or "달력" in t or "날짜 입력칸" in t or "월 탭" in t:
        return "캘린더"
    if any(w in t for w in ("로그인", "로그아웃", "회원가입", "가입")):
        return "로그인"
    if "다운로드" in t:
        return "다운로드"
    if "이미지" in t:
        return "이미지"
    if any(w in t for w in ("폼", "제출", "입력값", "입력 검증")):
        return "폼"
    if any(w in t for w in ("파일로 연결", "페이지 이동", "화면 로드", "리소스", "미방문 화면", "같은 형태의 화면", "[링크")):
        return "링크·이동"
    if "JS 오류" in t or "콘솔" in t or "검수 중단" in t:
        return "스크립트"
    if any(w in t for w in ("클릭", "버튼", "메뉴", "링크", "hover", "마우스", "모달", "팝업")):
        return "메뉴·버튼"
    if any(w in t for w in ("배치", "문구", "반응형", "범위 밖 요소")):
        return "화면"
    return "기타"


def _write_csv(path, header, rows, mode="w"):
    """엑셀이 파일을 잡고 있으면 다른 이름으로 저장하고 경로를 돌려줌"""
    write_header = mode == "w" or not path.exists() or path.stat().st_size == 0
    try:
        with open(path, mode, newline="", encoding="utf-8-sig" if write_header else "utf-8") as fp:
            w = csv.writer(fp)
            if write_header:
                w.writerow(header)
            w.writerows(rows)
        return path
    except PermissionError:
        alt = path.with_name(f"{path.stem}_{datetime.now():%H%M%S}{path.suffix}")
        print(f"  ! {path.name}이 열려 있어(엑셀 등) {alt.name}로 저장했습니다. 닫은 뒤 내용을 옮겨 주세요.")
        with open(alt, "w", newline="", encoding="utf-8-sig") as fp:
            w = csv.writer(fp)
            w.writerow(header)
            w.writerows(rows)
        return alt


def move_to_edit(files):
    if EDIT_DIR.resolve() == HTML_DIR.resolve():
        # 검수 폴더와 이동 폴더가 같으면 이동 대신 '_1' 이름 변경만 반복되므로 건너뜀
        print(f"  이동 건너뜀: 검수 폴더와 이동 폴더가 같습니다({EDIT_DIR})")
        return []
    EDIT_DIR.mkdir(exist_ok=True)
    moved = []
    for f in files:
        dest = EDIT_DIR / f.name
        n = 1
        while dest.exists():  # 같은 이름이 이미 있으면 _1, _2 붙임
            dest = EDIT_DIR / f"{f.stem}_{n}{f.suffix}"
            n += 1
        try:
            shutil.move(str(f), str(dest))
            moved.append((f.name, dest.name))
        except OSError as e:
            print(f"  이동 실패: {f.name} ({e})")
    return moved

def print_problems(file_rows):
    """방금 끝난 파일의 수정·오류·경고·주의 내용을 터미널에 출력"""
    probs = [r for r in file_rows if r[1] in ("수정", "오류", "경고", "주의")]
    for r in probs[:LIVE_PRINT_MAX]:
        tqdm.write(f"     [{r[1]}] {r[2][:150]}")
    if len(probs) > LIVE_PRINT_MAX:
        tqdm.write(f"     … 외 {len(probs) - LIVE_PRINT_MAX}건 (CSV 참고)")

def main():
    files = sorted(HTML_DIR.glob("*.html")) + sorted(HTML_DIR.glob("*.htm"))
    if not files:
        print(f"'{HTML_DIR}' 폴더에 html 파일이 없습니다.")
        return
    RESULT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%y%m%d_%H%M%S")
    out_csv = RESULT_DIR / f"result_{stamp}.csv"
    header = ["파일명", "구분", "내용"] + (["수동 체크 흐름"] + CHECK_COLUMNS if DETAIL_COLUMNS else [])
    live_csv = _write_csv(out_csv, header, [])          # 헤더만 먼저 만들어 둠
    per_dir = RESULT_DIR / f"파일별_{stamp}"
    if PER_FILE_CSV:
        per_dir.mkdir(exist_ok=True)
    print(f"파일 하나가 끝날 때마다 저장: {out_csv}" + (f" / {per_dir}" if PER_FILE_CSV else ""))

    rows = []
    cal_summary = Counter()
    work_summary = Counter()
    summary = Counter()
    not_ok_files = []
    moved = []
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
                file_rows = t.rows()
                rows += file_rows

                # ── 끝나자마자 저장 ──
                live_csv = _write_csv(live_csv, header, file_rows, mode="a")
                if PER_FILE_CSV:
                    _write_csv(per_dir / f"{f.name}.csv", header, file_rows)

                worst = t.worst_level()
                summary[worst] += 1
                fix_cats = t.fix_categories()
                not_ok = (worst != "정상" or (MOVE_FIX and fix_cats)
                          or (MOVE_REQUIREMENT_MISMATCH and "불일치" in t.cal_status))
                for cat in fix_cats:
                    work_summary[cat] += 1
                for st in t.cal_status:
                    cal_summary[st] += 1
                if t.cal_status:
                    cal_summary["파일"] += 1

                # ── 끝나자마자 터미널에 출력 ──
                cnt = Counter(lv for lv, _ in t.findings)
                tqdm.write(f"  {f.name}: {worst} (화면 {n_routes}개, 오류 {cnt['오류']}, 경고 {cnt['경고']}, "
                           f"주의 {cnt['주의']})")
                if LIVE_PRINT:
                    print_problems(file_rows)

                if not_ok:
                    if MOVE_NOT_OK and MOVE_IMMEDIATELY:
                        m = move_to_edit([f])
                        moved += m
                        for old, new in m:
                            tqdm.write(f"     → '{EDIT_DIR.name}' 폴더로 이동: {new}")
                    else:
                        not_ok_files.append(f)
            inner_bar.close()
            file_bar.close()
            browser.close()
    finally:
        server.shutdown()

    out_csv = _write_csv(out_csv, header, rows)   # 마지막에 전체를 한 번 더 깔끔하게 저장

    print(f"\n완료: {len(files)}개 파일 / 오류 {summary['오류']} / 경고 {summary['경고']} / "
          f"주의 {summary['주의']} / 정상 {summary['정상']}  ({time.time()-start:.0f}초)")
    print("  (파일별로 가장 심각한 구분 기준으로 집계)")
    if work_summary:
        print("구분='수정' 파일 수: " + " / ".join(f"{k} {v}개" for k, v in work_summary.most_common()))
    if CALENDAR_CHECK:
        print(f"캘린더({CALENDAR_START} ~ {CALENDAR_END}, {CALENDAR_MODE}): 발견 파일 {cal_summary['파일']}개 / "
              f"불일치 포함 {cal_summary['불일치']}개 / 확인 필요 포함 {cal_summary['확인 필요']}개 (구분='수정' + 내용 '캘린더'로 필터)")
    print(f"결과: {out_csv}")
    if MOVE_NOT_OK and not_ok_files:
        moved += move_to_edit(not_ok_files)
    if moved:
        print(f"정상 아닌 파일·'수정' 파일 {len(moved)}개를 '{EDIT_DIR}'로 이동:")
        for old, new in moved:
            print(f"  이동: {old}" if old == new else f"  이동(이름 변경): {old} → {new}")
    files = sorted(HTML_DIR.glob("*.html")) + sorted(HTML_DIR.glob("*.htm"))
    if not files:
        print(f"'{HTML_DIR}' 폴더에 html 파일이 없습니다.")
        return
    RESULT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%y%m%d_%H%M%S")
    out_csv = RESULT_DIR / f"result_{stamp}.csv"

    rows = []
    cal_summary = Counter()
    work_summary = Counter()
    summary = Counter()
    not_ok_files = [] 
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
                fix_cats = t.fix_categories()
                if (worst != "정상" or (MOVE_FIX and fix_cats)
                        or (MOVE_REQUIREMENT_MISMATCH and "불일치" in t.cal_status)):
                    not_ok_files.append(f)
                for cat in fix_cats:
                    work_summary[cat] += 1
                for st in t.cal_status:
                    cal_summary[st] += 1
                if t.cal_status:
                    cal_summary["파일"] += 1
                cnt = Counter(lv for lv, _ in t.findings)
                tqdm.write(f"  {f.name}: {worst} (화면 {n_routes}개, 오류 {cnt['오류']}, 경고 {cnt['경고']}, "
                           f"주의 {cnt['주의']})")
            inner_bar.close()
            file_bar.close()
            browser.close()
    finally:
        server.shutdown()

    # utf-8-sig: 엑셀에서 한글이 깨지지 않음
    header = ["파일명", "구분", "내용"] + (["수동 체크 흐름"] + CHECK_COLUMNS if DETAIL_COLUMNS else [])
    out_csv = _write_csv(out_csv, header, rows)

    print(f"\n완료: {len(files)}개 파일 / 오류 {summary['오류']} / 경고 {summary['경고']} / "
          f"주의 {summary['주의']} / 정상 {summary['정상']}  ({time.time()-start:.0f}초)")
    print("  (파일별로 가장 심각한 구분 기준으로 집계)")
    if work_summary:
        print("구분='수정' 파일 수: " + " / ".join(f"{k} {v}개" for k, v in work_summary.most_common()))
    if CALENDAR_CHECK:
        print(f"캘린더({CALENDAR_START} ~ {CALENDAR_END}, {CALENDAR_MODE}): 발견 파일 {cal_summary['파일']}개 / "
              f"불일치 포함 {cal_summary['불일치']}개 / 확인 필요 포함 {cal_summary['확인 필요']}개 (구분='수정' + 내용 '캘린더'로 필터)")
    print(f"결과: {out_csv}")
    if MOVE_NOT_OK and not_ok_files:
        moved = move_to_edit(not_ok_files)
        print(f"정상 아닌 파일·'수정' 파일 {len(moved)}개를 '{EDIT_DIR}'로 이동:")
        for old, new in moved:
            print(f"  이동: {old}" if old == new else f"  이동(이름 변경): {old} → {new}")


if __name__ == "__main__":
    main()