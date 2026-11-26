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
           (로그인·인증창이 실제로 동작하면 '로그인: … 정상 동작'처럼 통과 내용도 '정상' 행에 함께 적음)

_edit 버전에서 바뀐 점
    - 체험 계정 우선: 로그인 폼에 체험(데모) 계정이 있으면 그 계정으로 먼저 로그인
      (① 처음부터 채워진 값 ② '체험 계정' 자동 입력 버튼 ③ 화면에 적힌 계정 안내)
    - 회원가입: 가입 폼이 처음부터 보이지 않으면 로그인 화면의 '회원가입' 버튼·링크를 눌러 열고 가입 → 같은 계정으로 로그인
      (<form> 태그 없이 만든 가입 화면도 입력칸을 직접 찾아 입력)
    - 인증창: '인증번호 받기 → 번호 입력 → 확인'이 실제로 되는지 확인(인증창이 뜨는 것 자체는 오류가 아님)
    - 진행률: 전체 N단계 중 몇 단계인지, 몇 번째 파일인지 표시
    - 종료 후 '비정상(주의, 오류, 경고, 수정)' 건수를 터미널 마지막 줄에 출력
    - '클릭해도 반응 없음'·'다른 요소에 가려져 클릭 불가'를 근거와 함께 구분: 늦은 반응·저장만 하는 버튼은 반응으로 인정,
      일시적으로 덮는 로딩 막은 기다렸다가 클릭, 가리는 요소의 정체(위치·z-index·화면 비율)를 메시지에 표시

v2(인증 패치)에서 바뀐 점
    - 비밀번호 없는 인증 폼: 이름·휴대폰(이메일)만 넣고 인증번호로 확인하는 폼도 로그인·가입 폼으로 보고
      '가입 인증 → 같은 정보로 로그인 인증'까지 확인. 탭(회원 로그인·회원가입·비회원)은 제출 버튼 글자로 구분
    - 클릭해야 나타나는 로그인 창(모달·소셜 로그인)도 폼 검사 대상에 포함. '동의하고 계속하기' 같은 중간 단계를 넘긴 뒤 인증창 확인
    - 인증번호 입력칸 찾기: 열려 있는 창 안에서만, one-time-code·'인증번호' 표시가 있는 칸 우선(이름·전화·쿠폰 칸 제외)
    - 인증 성공 판정: 버튼 글자('인증 완료' 등)는 성공 문구로 보지 않음. 입력칸이 사라졌거나 성공 문구가 새로 나타나야 통과
    - 체험 계정: '빠른 로그인'처럼 계정 안내 영역 안의 '입력'·'채우기' 버튼, '이메일 / 비밀번호'만 적힌 안내 줄도 인식
    - 회원 전용 화면: 로그인이 확인되면 로그인 상태로 화면을 다시 훑어, 새로 나타난 폼(주문서 등)을 제출해 결제 인증창 확인
      (이 단계에서는 인증창 결과와 JS·콘솔 오류만 기록)

v3에서 바뀐 점
    - 제출 버튼 찾기: 검색·조회·필터 폼에서 type=button인 '검색'·'조회'·'찾기'·'적용' 버튼도 제출 버튼으로 인식
      (동작이 버튼 클릭에만 연결된 폼을 requestSubmit()으로만 제출해 '제출해도 반응 없음'으로 오판하던 문제)
      '주소 검색'·'비밀번호 찾기'·'쿠폰 적용' 같은 보조 버튼과 비밀번호가 있는 폼은 제외

v4에서 바뀐 점
    - 폼 밖 제출 버튼 찾기: 다른 폼에 속한 버튼은 제외(옆에 있는 로그인 폼의 '로그인' 버튼을 대신 누르던 문제)
    - '전송 대상 불명'(action·onsubmit·submit 리스너 없는 <form>)을 제출해 본 뒤 판정
      · 버튼 클릭으로 동작하면 '전송 대상 불명'으로 보지 않음
      · 대신 입력칸에서 Enter를 눌러 폼이 그대로 전송되어 새로고침되면 그 사실을 '주의'로 기록(ENTER_SUBMIT_CHECK)
      · 버튼을 못 찾았거나 제출하면 화면이 다시 열리기만 하는 폼은 기존대로 '전송 대상 불명'

v5에서 바뀐 점
    - 로그인 실패 문구 판정: 로그인 폼이 사라지고 로그인됐다는 근거(로그아웃 버튼·새 로그인 표시·'로그인했습니다' 안내)가 있으면
      옮겨 간 화면 본문의 '실패' 같은 낱말을 로그인 실패 문구로 보지 않음
    - 로그아웃: 버튼이 지금 화면에 없으면 '마이페이지'·'내 정보' 같은 메뉴를 눌러 그 화면에서 찾아 로그아웃(LOGOUT_SEARCH)
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

from playwright.sync_api import sync_playwright, Error as PWError, TimeoutError as PWTimeout
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
SUBMIT_WAIT_MS = 500         # 제출 후 화면 변화가 없을 때 추가로 기다릴 최대 시간
LOAD_WAIT_MS = 150           # 화면 이동 후 렌더링 대기 시간
SAME_PATTERN_LIMIT = 2       # 같은 모양 요소/화면(예: 목록의 상세보기 50개)은 몇 개만 샘플 검사
REPORT_NO_RESPONSE = True    # '클릭해도 반응 없음'을 기록할지
SHOW_LOCATION = True         # 내용 뒤에 발생 위치(화면 > 요소)를 붙일지
MAX_LOCATIONS = 3            # 같은 내용이 여러 곳에서 나올 때 표시할 위치 수
LEVEL_ORDER = ["오류", "경고", "주의", "요구사항", "수동", "통과"]
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
CLOSE_POPUPS = True          # 화면을 열면 저절로 뜨는 팝업(공지·이벤트·쿠키 안내 등)을 닫은 뒤 검사
# 팝업으로 볼 요소의 class·id 앞부분. 화면에 고정(fixed)됐거나 위에 떠 있는(absolute+z-index) 요소만 대상
POPUP_NAME_RE = r"(^|[\s_-])(modal|popup|pop|layer|dialog|overlay|backdrop|dim|toast|cookie|notice|event|loading|loader|spinner|mask)"
# 팝업 안에서 누를 '닫기' 버튼 글자(정확히 같을 때)
POPUP_CLOSE_TEXT_RE = r"^(닫기|창닫기|팝업 ?닫기|close|x|×|✕|✖|확인|오늘 ?하루 ?(보지|열지) ?않기|다시 ?보지 ?않기|동의|ok)$"
MAX_HOVER_TESTS = 30         # 파일당 hover 메뉴 검사 최대 수
LOGIN_CHAIN_TEST = True      # 회원가입 폼 + 로그인 폼이 있으면 '가입 → 같은 값으로 로그인'을 이어서 검사
# 폼에 자동으로 넣을 테스트 계정. 입력칸의 라벨·placeholder·id·name을 보고 알맞은 값을 골라 넣음
TEST_ACCOUNT = {
    "id": "hello",                # 아이디 칸
    "email": "hello@naver.com",   # 이메일 칸
    "password": "Hello123456",    # 비밀번호·비밀번호 확인 칸(대문자+소문자+숫자 3종류: '3종류 이상 조합' 규칙 통과)
    "name": "안뇽",               # 이름·닉네임 칸
    "phone": "010-1234-5678",     # 전화번호 칸
}
# 로그인 폼의 칸이 '아이디인지 이메일인지' 알 수 없을 때 넣어 볼 순서. 첫 값이 실패하면 다음 값으로 한 번 더 로그인
LOGIN_KEY_ORDER = ("email", "id")
# 가입 시 이 문구가 나오면 '이미 가입된 계정' → 실패로 보지 않고 로그인 단계로 넘어감
# (같은 검사 중 앞 단계에서 이미 가입이 한 번 이루어졌을 수 있기 때문)
DUPLICATE_WORDS = ("이미 가입", "이미 사용", "이미 존재", "이미 등록", "중복된", "already")
# 가입 제출 전에 먼저 눌러 볼 버튼(아이디·이메일 중복확인 등). 사람이 가입할 때 누르는 순서를 흉내 냄
PRECHECK_RE = r"중복\s*(확인|체크|검사)|check"
FAIL_WORDS = ("실패", "일치하지", "맞지 않", "올바르지", "잘못", "존재하지 않", "등록되지 않", "가입되지 않", "없는 계정",
              "없는 아이디", "틀렸", "invalid", "incorrect", "failed", "wrong", "not found")
LOGIN_STATE_TEST = True      # 로그인 후 비로그인 화면이 '로그인 상태'로 바뀌는지, 로그아웃 후 원래대로 돌아오는지 검사
# 비로그인 때만 보여야 하는 버튼 글자(정확히 같을 때만, 폼 안의 제출 버튼은 제외)
GUEST_WORDS = ("로그인", "회원가입", "가입하기", "login", "log in", "sign in", "sign up", "signup", "join")
# 로그인 후 나타나야 하는 표시(화면 글자에 포함되면 인정). 비로그인 때부터 있던 글자는 제외하고 비교
MEMBER_WORDS = ("로그아웃", "logout", "log out", "sign out", "마이페이지", "my page", "mypage", "내 정보", "내정보",
                "환영", TEST_ACCOUNT["name"].lower(), TEST_ACCOUNT["email"].lower())
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
FIX_CATEGORIES = ("로그인", "인증", "캘린더")   # 이 기능의 문제는 구분='수정'으로 모음
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
# ── _edit 버전 추가 설정 ──
ABNORMAL_LABELS = ("주의", "오류", "경고", "수정")   # 종료 후 '비정상(...) 건수'로 출력할 구분. 괄호 안 순서 = 숫자 순서
STAGES = ("화면 탐색", "클릭 검사", "hover 메뉴", "폼·로그인", "캘린더")   # 파일 하나당 진행 단계(진행률 표시용)
DEMO_FIRST = True            # 로그인 폼에 체험 계정이 있으면 TEST_ACCOUNT보다 먼저 그 계정으로 로그인
# 체험 계정 자동 입력 버튼 글자(포함되면 후보). 로그인 폼 안 → 폼을 감싼 3단계 상위 순서로 찾음
DEMO_BTN_RE = (r"(체험|데모|demo|테스트|test|샘플|sample|시연).{0,8}(계정|account|로그인|login|아이디|id)"
               r"|(계정|아이디).{0,6}(자동|채우|입력)|(자동|바로).{0,4}(입력|채우|채움)|auto-?fill")
DEMO_LINE_RE = r"(체험|데모|demo|테스트|test|샘플|sample|시연).{0,8}(계정|account)"   # 화면에 적힌 '체험 계정: 아이디 / 비밀번호' 안내 줄
# 가입 폼이 처음부터 안 보일 때 로그인 화면에서 눌러 볼 버튼 글자 / 가입 후 로그인 창을 다시 열 버튼 글자(정확히 같을 때)
SIGNUP_TRIGGER_RE = r"회원\s*가입|가입\s*하기|회원\s*등록|계정\s*(만들기|생성)|새\s*계정|sign ?up|register|create (an )?account|\bjoin\b"
LOGIN_TRIGGER_RE = r"^(회원\s*)?(로그인|login|log in|sign in|signin)$"
AUTH_TEST = True             # 인증창('인증번호 받기 → 번호 입력 → 확인')이 실제로 되는지 확인
AUTH_SEND_RE = (r"인증\s*(번호|코드)?\s*(요청|받기|발송|전송|재전송|하기)|(본인|휴대폰|이메일|메일|문자)\s*인증"
                r"|send ?(code|otp)|get ?(code|otp)")
AUTH_OK_RE = r"인증\s*확인|확인|완료|제출|\bverify\b|\bconfirm\b|\bsubmit\b|\bok\b"
AUTH_HINT_RE = r"인증|코드|otp|verif|code|authnum|\bpin\b"   # [v2] 'auth' 단독 제외(auth-name 같은 이름 칸 오인 방지)
AUTH_SUCCESS_WORDS = ("인증되었", "인증 되었", "인증이 완료", "인증 완료", "인증완료", "인증 성공", "인증성공",
                      "확인되었", "성공", "완료", "verified", "success")
LATE_WAIT_MS = 1500          # 클릭 직후 변화가 없을 때, 반응이 늦게 나타나는지 더 기다릴 최대 시간(ms). 0이면 끔
COVER_WAIT_MS = 8000         # 다른 요소가 덮고 있을 때 풀리길(로딩 화면 등) 기다릴 최대 시간(ms)
VIEWPORT_SIZE = (1280, 720)  # 브라우저 화면 크기(가로, 세로). 모바일 목업이면 (390, 844)처럼 바꿔 보세요
AUTH_DEFAULT_CODE = "123456"  # 화면·알림에서 인증번호를 못 찾았을 때 넣어 볼 값(맞는 번호가 아닐 수 있음)
# ── v2(인증 패치) 추가 설정 ──
AUTH_FORM_TEST = True        # 비밀번호 없이 이름·휴대폰(이메일)을 넣고 인증번호로 확인하는 폼도 로그인·가입 폼처럼 검사
GUEST_TAB_RE = r"비회원|게스트|guest|손님"   # '비회원 인증' 탭·버튼 글자
REVEALED_FORM_TEST = True    # 버튼을 눌러야 나타나는 로그인 창(모달·소셜 로그인 등)도 검사
REVEALED_FORM_MAX = 3        # 파일당 그런 로그인 창을 몇 개까지 검사할지
REVEALED_FORM_STRICT = False # False: 그런 창에서는 '통과'만 결과에 남기고 문제는 '수동'으로 낮춤 / True: 일반 로그인 폼과 같은 구분으로 기록
LOGIN_STEP_MAX = 3           # 로그인 제출 뒤 '동의하고 계속하기' 같은 중간 단계를 최대 몇 번 넘길지
LOGIN_CONTINUE_RE = r"동의|계속|다음|허용|continue|next|agree|allow|accept"
LOGIN_TRIGGER_LOOSE_RE = r"^(?!.*(로그아웃|logout|log ?out|sign ?out)).*(로그인|log ?in|sign ?in)"   # '로그인·비회원 인증'처럼 다른 글자가 붙은 로그인 버튼
DEMO_ZONE_RE = r"체험|데모|demo|테스트\s*계정|test\s*account|샘플|sample|시연|빠른\s*로그인|간편\s*입력|quick\s*login"   # 계정 안내 영역 글자
DEMO_FILL_RE = r"입력|채우기|채움|사용|적용|선택|불러오기|fill|use|apply"   # 그 영역 안의 '계정 채우기' 버튼 글자
MEMBER_TEST = True           # 로그인이 확인되면 로그인 상태로 회원 전용 화면의 폼을 제출해, 제출 뒤 뜨는 인증창(결제 인증 등)을 확인
MEMBER_MAX_ROUTES = 12       # 로그인 상태에서 새로 발견한 화면을 몇 개까지 열어 볼지(비로그인 때 본 화면은 모두 다시 엶)
MEMBER_MAX_FORMS = 8         # 로그인 상태에서 제출해 볼 폼 수
MEMBER_PREP_MAX = 3          # '바로 주문' 같은 버튼을 몇 번까지 눌러 다음 화면(주문서 등)으로 넘어가 볼지
MEMBER_PREP_RE = r"바로\s*(주문|구매|결제)|구매하기|주문하기|결제하기|예매하기|buy now|order now|checkout"
MEMBER_SKIP_RE = r"탈퇴|삭제|해지|초기화|withdraw|delete|remove|reset"   # 로그인 상태에서 제출하지 않을 폼(제출 버튼 글자)
# ── v4 추가 설정 ──
ENTER_SUBMIT_CHECK = True    # 제출 처리가 없는 <form>이 버튼 클릭으로는 동작할 때, 입력칸에서 Enter를 눌러 새로고침되는지도 확인
# ── v5 추가 설정 ──
# 로그인 성공을 알리는 안내 문구(이 문구가 새로 나타나면, 옮겨 간 화면 본문의 '실패' 같은 낱말을 로그인 실패로 보지 않음)
LOGIN_SUCCESS_WORDS = ("로그인했", "로그인되었", "로그인 되었", "로그인에 성공", "로그인 성공", "로그인 완료", "환영합니다",
                       "welcome", "signed in", "logged in", "login success")
LOGOUT_SEARCH = True         # 로그아웃 버튼이 지금 화면에 없으면 '마이페이지'·'내 정보' 같은 메뉴를 눌러 그 화면에서 찾음
LOGOUT_SEARCH_MAX = 3        # 그런 메뉴를 몇 개까지 눌러 볼지
ACCOUNT_LINK_RE = r"마이\s*페이지|내\s*정보|내\s*계정|회원\s*정보|계정\s*(설정|관리|정보)?$|프로필|my ?page|my ?account|^account$|profile|^설정$|^settings$|.{1,10}님$"
NO_TARGET_MSG = "action·onsubmit·submit 리스너가 모두 없는 <form> 태그 (전송 대상 불명)"
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
# 겉모습(위치·크기·색·투명도) 서명: innerHTML이 같아도 CSS만 바뀐 경우를 반응으로 잡기 위함
VISUAL_JS = """() => {
  if (!document.body) return '';
  const de = document.documentElement, out = [document.title, de.className, de.getAttribute('style') || ''];
  let n = 0;
  for (const el of document.body.querySelectorAll('*')) {
    if (++n > 1500) break;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const s = getComputedStyle(el);
    out.push([el.tagName, Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height),
              s.opacity, s.color, s.backgroundColor, s.transform, el.scrollTop].join(','));
  }
  return out.join(';');
}"""
# 이미 선택된 항목(탭·필터·현재 페이지 번호 등)인지: 눌러도 변화 없는 것이 정상이라 '반응 없음' 경고에서 구분
SELECTED_JS = r"""(el) => {
  const a = (n) => el.getAttribute(n);
  if (a('aria-pressed') === 'true' || a('aria-selected') === 'true' || a('aria-checked') === 'true') return true;
  const cur = a('aria-current');
  if (cur !== null && cur !== 'false') return true;
  const cls = typeof el.className === 'string' ? el.className : '';
  return /(^|[\s_-])(active|selected|current|on)($|[\s_-])/i.test(cls);
}"""
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

FILL_FORM_JS = r"""
([idx, acct, mode, keep, opt]) => {
  const f = idx >= 0 ? document.querySelectorAll('form')[idx] : document.querySelector('[data-qa-root]');
  if (!f) return null;
  const pwCount = f.querySelectorAll('input[type=password]').length;
  // [v2] smart: 비밀번호 칸이 없어도 이름·전화·이메일 칸을 알아보고 맞는 값을 넣음 / natural: 미리 선택·입력된 값은 그대로 둠
  const smart = !!(opt && opt.smart), natural = !!(opt && opt.natural);
  const sem = pwCount || smart;
  const telLike = (el) => /tel/i.test(el.getAttribute('inputmode') || '') || /(^|\s)tel/i.test(el.getAttribute('autocomplete') || '');
  let hasPw = false, ambiguous = false;
  const used = {};
  // 입력칸 설명 글자: 연결된 <label>, 감싼 <label>, placeholder, aria-label, autocomplete, name, id
  const hintOf = (el) => {
    const parts = [el.getAttribute('placeholder'), el.getAttribute('aria-label'), el.getAttribute('autocomplete'),
                   el.getAttribute('name'), el.getAttribute('id'), el.getAttribute('title')];
    const id = el.getAttribute('id');
    if (id) { try { const lb = document.querySelector(`label[for="${CSS.escape(id)}"]`); if (lb) parts.push(lb.innerText); } catch (e) {} }
    const wrap = el.closest('label'); if (wrap) parts.push(wrap.innerText);
    return parts.filter(Boolean).join(' ');
  };
  const isEmail = (h) => /e-?mail|이메일|메일/i.test(h);
  // userId·loginId·mem_id·아이디·계정 등. 'valid'·'hidden'처럼 단어 안의 id는 제외
  const isId = (h) => /아이디|계정|user ?name|(^|[^a-z])(user|login|member|mem|account)?[_-]?id([^a-z]|$)/i.test(h)
                      || /[a-z](Id|ID)\b/.test(h);
  const isName = (h) => /이름|성명|닉네임|별명|nickname|full ?name|(^|[^a-z])name([^a-z]|$)/i.test(h);
  const isTel = (h) => /전화|휴대폰|핸드폰|연락처|phone|mobile|tel/i.test(h);
  const pick = (key) => { used[key] = acct[key]; return acct[key]; };
  for (const el of f.querySelectorAll('input, textarea, select')) {
    if (el.disabled || el.readOnly) continue;
    const t = (el.type || '').toLowerCase();
    // 기본 setter로 값 넣기: el.value = v 만 쓰면 React 같은 화면 프레임워크가 입력을 알아채지 못함
    const set = (v) => {
      const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const d = Object.getOwnPropertyDescriptor(proto, 'value');
      if (d && d.set && el.tagName !== 'SELECT') d.set.call(el, v); else el.value = v;
      el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true}));
    };
    if (['hidden','submit','button','reset','file','image'].includes(t)) continue;
    // keep: 체험 계정처럼 이미 채워진 칸은 그대로 두고 빈 칸·체크박스만 채움
    if (keep && !['checkbox','radio'].includes(t) && el.tagName !== 'SELECT' && el.value) continue;
    const h = hintOf(el);
    if (t === 'password') { hasPw = true; set(pick('password')); }
    else if (t === 'email') set(pick('email'));
    else if (t === 'tel') set(pick('phone'));
    else if (t === 'number' || t === 'range') set(el.min || '1');
    else if (t === 'date') set('2026-10-30');
    else if (t === 'time') set('10:00');
    else if (t === 'url') set('https://example.com');
    else if (t === 'checkbox') {
      if (natural && !el.required && !/동의|확인|agree|accept|약관|terms/i.test(h)) continue;   // 필수·동의 체크만, 나머지는 기본값 유지
      el.checked = true; el.dispatchEvent(new Event('change', {bubbles:true}));
    }
    else if (t === 'radio') {
      if (natural) {   // 묶음에서 이미 선택된 것이 있으면 그대로, 없으면 첫 번째 것만 선택
        const group = el.name ? [...f.querySelectorAll('input[type=radio]')].filter(r => r.name === el.name) : [el];
        if (group.some(r => r.checked) || group.find(r => !r.disabled) !== el) continue;
      }
      el.checked = true; el.dispatchEvent(new Event('change', {bubbles:true}));
    }
    else if (el.tagName === 'SELECT') {
      if (natural) {   // 유효한 값이 이미 선택돼 있으면 그대로, 아니면 고를 수 있는 첫 항목
        const cur = el.options[el.selectedIndex];
        if (cur && cur.value !== '' && !cur.disabled) continue;
        const i = [...el.options].findIndex(o => o.value !== '' && !o.disabled);
        if (i >= 0) el.selectedIndex = i;
      } else if (el.options.length > 1) el.selectedIndex = 1;
      el.dispatchEvent(new Event('change', {bubbles:true}));
    }
    else if (sem && isEmail(h) && isId(h) && /또는|혹은|\bor\b|\//i.test(h)) { ambiguous = true; set(pick(mode)); }  // '이메일 또는 아이디'
    else if (sem && isEmail(h)) set(pick('email'));          // '이메일 아이디'처럼 이메일이 들어간 칸은 이메일
    else if (sem && isId(h)) set(pick('id'));
    else if (sem && (isTel(h) || telLike(el))) set(pick('phone'));
    else if (sem && isName(h)) set(pick('name'));
    else if (pwCount === 1 && el.tagName === 'INPUT') { ambiguous = true; set(pick(mode)); }  // 설명 없는 로그인 칸
    else set(el.minLength > 0 ? '테스트'.padEnd(el.minLength, '1') : '테스트');
  }
  // f.id 대신 getAttribute 사용: <input name="id">가 있으면 f.id가 그 input을 가리킴
  const name = (f.getAttribute('id') || f.getAttribute('name') || f.getAttribute('class') || ('form' + idx)).slice(0, 30);
  return { hasPw, name, ambiguous, used };
}
"""

# 저절로 떠 있는 팝업을 찾아, 닫기 버튼에 번호표(data-qa-close)를 붙임.
# 입력칸이 있는 팝업(로그인·검색 창 등)은 기능이므로 닫지 않음
POPUP_SCAN_JS = r"""
([nameRe, closeRe]) => {
  const vis = (e) => { const r = e.getBoundingClientRect(); const st = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none' && +st.opacity > 0; };
  const nm = new RegExp(nameRe, 'i'), cl = new RegExp(closeRe, 'i');
  document.querySelectorAll('[data-qa-close]').forEach(e => e.removeAttribute('data-qa-close'));
  const name = (e) => ((typeof e.className === 'string' ? e.className : '') + ' ' + (e.id || ''));
  for (const el of document.body.querySelectorAll('*')) {
    const st = getComputedStyle(el);
    const floating = st.position === 'fixed' || (st.position === 'absolute' && (+st.zIndex || 0) >= 10);
    const isPopup = el.getAttribute('role') === 'dialog' || el.getAttribute('aria-modal') === 'true'
                    || el.tagName === 'DIALOG' || nm.test(name(el));
    if (!floating || !isPopup || !vis(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 120 || r.height < 60) continue;
    if (el.querySelector('input:not([type=checkbox]):not([type=hidden]), textarea, select')) continue;
    const btn = [...el.querySelectorAll('button, a, [role=button], [onclick], input[type=button]')].find(b => {
      if (!vis(b)) return false;
      const t = (b.innerText || b.value || '').trim().replace(/\s+/g, ' ').toLowerCase();
      const a = ((b.getAttribute('aria-label') || '') + ' ' + name(b)).toLowerCase();
      return cl.test(t) || /close|닫기|btn[_-]?x/.test(a);
    });
    const label = ((el.innerText || '').trim().split('\n')[0] || name(el).trim()).slice(0, 20);
    if (btn) { btn.setAttribute('data-qa-close', '1'); return { label, button: true }; }
    return { label, button: false };
  }
  return null;
}
"""

# 폼의 '제출 버튼'을 찾아 번호표(data-qa-submit)를 붙임. 사람처럼 버튼을 눌러 제출하기 위함
# 1) type=submit 버튼  2) 폼 안의 일반 버튼 중 '가입·로그인·확인' 글자
# 3) [v3] 검색·조회 폼의 '검색·조회·찾기·적용' 버튼  4) 폼 밖(모달 아래쪽 등)의 '가입·로그인' 버튼
# kind='precheck'면 '중복확인' 같은 사전 확인 버튼들에 번호표를 붙임
SUBMIT_TARGET_JS = r"""
([idx, kind, precheckRe]) => {
  const f = idx >= 0 ? document.querySelectorAll('form')[idx] : document.querySelector('[data-qa-root]');
  if (!f) return null;
  document.querySelectorAll('[data-qa-submit],[data-qa-pre]').forEach(e => { e.removeAttribute('data-qa-submit'); e.removeAttribute('data-qa-pre'); });
  const txt = (e) => (e.innerText || e.value || e.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
  const visible = (e) => {
    const { width, height } = e.getBoundingClientRect();
    return width > 0 && height > 0 && getComputedStyle(e).visibility === 'visible';
  };
  const fid = f.getAttribute('id');
  const candidates = [...f.querySelectorAll('button, input[type=submit], input[type=button], [role=button], a[onclick], [onclick]')];
  if (fid) { try { candidates.push(...document.querySelectorAll(`[form="${CSS.escape(fid)}"]`)); } catch (e) {} }
  const own = candidates.filter(visible);
  const pre = new RegExp(precheckRe, 'i');
  if (kind === 'precheck') {
    const list = own.filter(e => pre.test(txt(e)) && !e.disabled);
    list.forEach((e, i) => e.setAttribute('data-qa-pre', String(i)));
    return list.map(txt);
  }
  // [v2] '인증번호 받기'·'본인 인증'은 제출 버튼이 아니지만, '회원가입 인증'·'로그인 인증'처럼 제출 자체가 인증인 버튼은 제출 버튼으로 봄
  const skipRe = /취소|닫기|중복|찾기|보기|숨기기|cancel|close|check/i;
  const skip = { test: (t) => skipRe.test(t) || (/인증/.test(t) && !/로그인|가입|회원|log ?in|sign/i.test(t)) };
  const go = /가입|등록|로그인|확인|완료|제출|다음|join|sign|log ?in|submit|register|ok/i;
  let el = own.find(e => (e.type === 'submit' || (e.tagName === 'BUTTON' && !e.getAttribute('type'))) && !skip.test(txt(e)))
        || own.find(e => go.test(txt(e)) && !skip.test(txt(e)));
  // [v3] 검색·조회·필터 폼: 동작이 버튼 클릭에만 연결된 type=button '검색'·'조회'·'찾기'·'적용' 버튼
  //      위 두 단계에서 못 찾았을 때만 봄('가입하기'보다 '우편번호 검색'을 먼저 누르지 않도록 우선순위를 낮춤)
  //      '주소 검색'·'비밀번호 찾기'·'쿠폰 적용'처럼 다른 칸을 채우는 보조 버튼과 비밀번호가 있는 폼은 제외
  if (!el && !f.querySelector('input[type=password]')) {
    const act = /(검색|조회|찾기|적용)(하기)?[^0-9A-Za-z가-힣]*$|\b(search|find|look ?up|apply|filter)\b/i;
    const aux = /아이디|비밀번호|비번|패스워드|계정|\bid\b|\bpw\b|password|username|account|주소|우편|address|zip|postal|post ?code|쿠폰|coupon|할인|포인트|point|적립|상품권|voucher|promo|파일|file|첨부|upload|이미지|사진|image|photo|중복|인증|추천|코드|code/i;
    const skip3 = /취소|닫기|보기|숨기기|초기화|cancel|close|check|reset|clear/i;
    el = own.filter(e => !e.disabled && e.type !== 'reset' && act.test(txt(e)) && !aux.test(txt(e)) && !skip3.test(txt(e)))
            .sort((a, b) => txt(a).length - txt(b).length)[0] || null;   // 여러 개면 글자가 가장 짧은 것('상세 검색'보다 '검색')
  }
  if (!el) {   // 폼 밖 가까운 곳(모달 아래쪽 버튼 등)
    // [v4] 다른 폼에 속한 버튼은 이 폼의 제출 버튼이 아님(옆에 있는 로그인 폼의 '로그인' 버튼을 대신 누르지 않도록)
    const myForm = f.tagName === 'FORM' ? f : f.closest('form');
    const inOtherForm = (e) => { const ef = e.form || e.closest('form'); return !!ef && ef !== myForm; };
    let box = f.parentElement;
    for (let k = 0; k < 3 && box && !el; k++, box = box.parentElement) {
      el = [...box.querySelectorAll('button, input[type=button], [role=button], [onclick]')]
        .find(e => !f.contains(e) && !inOtherForm(e) && /가입|로그인|join|sign ?up|log ?in|register/i.test(txt(e)) && !skip.test(txt(e))
                   && !e.closest('nav, header') && visible(e));
    }
  }
  if (!el) return null;
  el.setAttribute('data-qa-submit', '1');
  return txt(el).slice(0, 20) || el.tagName.toLowerCase();
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
  const pwVis = [...f.querySelectorAll('input[type=password]')].filter(i => {   // 탭 전환형: 숨은 '비밀번호 확인' 칸은 제외
    const r = i.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(i).visibility !== 'hidden'; }).length;
  const btn = [...f.querySelectorAll('button:not([type]), button[type=submit], input[type=submit]')]
    .map(b => (b.innerText || b.value || '')).join(' ');
  const attrs = [f.getAttribute('id'), f.getAttribute('name'), f.getAttribute('class'), f.getAttribute('action')].join(' ');
  const signup = pwVis >= 2 || /가입|등록|sign ?up|register|join/i.test(btn) || /signup|sign-up|register|join/i.test(attrs);
  const name = (f.getAttribute('id') || f.getAttribute('name') || f.getAttribute('class') || ('form' + idx)).slice(0, 30);
  // [v2] 비밀번호 없이 이름·휴대폰(이메일)만 넣고 인증번호로 확인하는 폼: 제출 버튼이 '인증·로그인·가입'류이고 연락처 칸이 있음
  const btnText = btn.trim().replace(/\\s+/g, ' ').slice(0, 30);
  const contact = [...f.querySelectorAll('input')].some(i => {
    const t = (i.type || 'text').toLowerCase();
    if (['hidden', 'checkbox', 'radio', 'submit', 'button', 'file', 'image', 'password'].includes(t)) return false;
    const own = [i.getAttribute('inputmode'), i.getAttribute('autocomplete'), i.getAttribute('name'), i.id, i.getAttribute('placeholder')].filter(Boolean).join(' ');
    return t === 'tel' || t === 'email' || /tel|phone|mobile|e-?mail|전화|휴대폰|핸드폰|연락처|이메일/i.test(own);
  });
  const authish = /인증|로그인|본인\\s*확인|log ?in|sign ?in|verify/i.test(btn) || /가입|sign ?up|register|join/i.test(btn);
  const isSearch = f.getAttribute('role') === 'search' || !!f.querySelector('input[type=search]');
  const auth = pw === 0 && contact && authish && !isSearch;
  return { pw, signup, name, auth, btn: btnText };
}
"""

# 화면을 다시 그리면 폼 순서가 바뀔 수 있으므로 이름과 비밀번호 필드로 로그인 폼을 다시 찾음.
LOGIN_FORM_HELPER_JS = """
  // [v2] key가 '폼 이름\\u0001제출 버튼 글자'이면 비밀번호 없는 인증 폼: 제출 버튼 글자로 탭(로그인·가입·비회원)을 구분
  const findLoginForm = (key) => {
    const [name, want] = String(key).split('\\u0001');
    return Array.from(document.forms).find((form, idx) => {
      const identity = (form.getAttribute('id') || form.getAttribute('name') || form.getAttribute('class') || ('form' + idx)).slice(0, 30);
      if (identity !== name) return false;
      if (want === undefined) {
        const pwShown = [...form.querySelectorAll('input[type=password]')].filter(i => { const r = i.getBoundingClientRect(); return r.width > 0 && r.height > 0; }).length;
        if (pwShown !== 1) return false;
      } else {
        const btn = [...form.querySelectorAll('button:not([type]), button[type=submit], input[type=submit]')]
          .map(b => (b.innerText || b.value || '')).join(' ').trim().replace(/\\s+/g, ' ').slice(0, 30);
        if (btn !== want) return false;
      }
      const { width, height } = form.getBoundingClientRect();
      return width > 0 && height > 0 && getComputedStyle(form).visibility !== 'hidden';
    });
  };
"""

LOGIN_FORM_INDEX_JS = """
(name) => {
""" + LOGIN_FORM_HELPER_JS + """
  return Array.from(document.forms).indexOf(findLoginForm(name));
}
"""

# 완료 알림이나 안내 문구와 구별하기 위해 로그아웃 컨트롤의 이름만 읽음.
LOGOUT_CONTROL_JS = """
  const logoutWords = ['로그아웃', 'logout', 'log out', 'sign out'];
  const logoutControls = () => [...document.querySelectorAll('a, button, [role=button], input[type=button], input[type=submit], [onclick]')]
    .filter(vis)
    .map(el => {
      const labels = [el.innerText || el.value, el.getAttribute('aria-label')].filter(Boolean).map(norm);
      return {el, labels: labels.filter(label => logoutWords.some(word => label.includes(word)))};
    })
    .filter(({labels}) => labels.length);
"""

# 로그인 상태 스냅샷: 비로그인용 버튼, 로그인 표시, 입력칸에 남은 값, 지정 선택자
LOGIN_STATE_JS = """
([guestWords, memberWords, guestSel, memberSel, loginName, typedVals]) => {
""" + LOGIN_FORM_HELPER_JS + """
  const vis = (e) => { if (!e) return false; const r = e.getBoundingClientRect(); const st = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
  const norm = (t) => (t || '').trim().replace(/\\s+/g, ' ').toLowerCase();
  // 투명·화면 밖·숨김 조상 아래에 있는 요소는 '보임'으로 보지 않음
  const shown = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0 || r.right <= 0 || r.left >= innerWidth) return false;
    for (let e = el; e && e !== document.documentElement; e = e.parentElement) {
      const st = getComputedStyle(e);
      if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity) < 0.05) return false;
    }
    return true;
  };
""" + LOGOUT_CONTROL_JS + """
  const guest = [];
  for (const el of document.querySelectorAll('a, button, [role=button], input[type=button], input[type=submit], [onclick]')) {
    if (el.closest('form') || !vis(el)) continue;
    const t = norm(el.innerText || el.value);
    if (guestWords.includes(t) && !guest.includes(t)) guest.push(t);
  }
  const text = norm(document.body ? document.body.innerText : '');
  const logout = logoutControls();
  const member = memberWords.filter(w => logoutWords.includes(w)
    ? logout.some(({labels}) => labels.some(label => label.includes(w)))
    : text.includes(w));
  const pw = [...document.querySelectorAll('input[type=password]')].filter(i => i.value);
  // 로그인·가입 폼(비밀번호 칸이 있는 폼) 안의 입력칸만 봄. 검색창 등에 남은 값은 제외
  const typed = [...document.querySelectorAll('form')].filter(f => f.querySelector('input[type=password]'))
    .flatMap(f => [...f.querySelectorAll('input')]).filter(i => typedVals.includes(i.value)
    && !['hidden', 'checkbox', 'radio', 'submit', 'button'].includes((i.type || '').toLowerCase()));
  const q = (sel) => { try { return document.querySelector(sel); } catch (e) { return null; } };
  return {
    guest, member,
    pwVisible: pw.filter(vis).length, pwAny: pw.length,
    typedVisible: typed.filter(vis).length, typedAny: typed.length,
    guestSel: guestSel.filter(sel => vis(q(sel))),
    memberSel: memberSel.filter(sel => vis(q(sel))),
    loginFormVisible: (() => { const f = findLoginForm(loginName); return !!f && shown(f); })(),
  };
}
"""

# 보이는 '로그아웃' 버튼에 번호표를 붙이고 글자를 돌려줌
LOGOUT_TAG_JS = """
() => {
  document.querySelectorAll('[data-qa-logout]').forEach(e => e.removeAttribute('data-qa-logout'));
  const vis = (e) => { const r = e.getBoundingClientRect(); const st = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
  const norm = (t) => t.trim().replace(/\\s+/g, ' ').toLowerCase();
""" + LOGOUT_CONTROL_JS + """
  const controls = logoutControls();
  const match = controls.find(({labels}) => labels.some(label => logoutWords.includes(label)))
    || controls.find(({labels}) => labels.some(label => label.length < 15));
  if (!match) return null;
  const {el} = match;
  el.setAttribute('data-qa-logout', '1');
  return el.getAttribute('aria-label') || (el.innerText || el.value || '').trim();
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
VISIBLE_FORMS_JS = """
(plainOnly) => {
  const modal = document.querySelector('dialog:modal');
  return [...document.querySelectorAll('form')].flatMap((form, index) => {
    if (form.closest('[inert]') || (modal && !modal.contains(form))) return [];
    const { width, height } = form.getBoundingClientRect();
    const visible = width > 0 && height > 0 && getComputedStyle(form).visibility === 'visible';
    return visible && (!plainOnly || !form.querySelector('input[type=password]')) ? [index] : [];
  });
}
"""

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

# ───────────── 체험 계정 · 회원가입 버튼 · 인증창을 찾는 JS ─────────────
# 로그인 폼 안 → 폼을 감싼 3단계 상위 순서로 '체험 계정 입력' 버튼을 찾아 번호표(data-qa-demo)를 붙임
DEMO_SCAN_JS = r"""
([idx, re]) => {
  const f = document.querySelectorAll('form')[idx];
  if (!f) return null;
  document.querySelectorAll('[data-qa-demo]').forEach(e => e.removeAttribute('data-qa-demo'));
  const vis = (e) => { const r = e.getBoundingClientRect(); const st = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
  const txt = (e) => (e.innerText || e.value || e.getAttribute('aria-label') || e.title || '').trim().replace(/\s+/g, ' ');
  const rx = new RegExp(re, 'i');
  const clickable = (e) => /^(BUTTON|A|SUMMARY|INPUT)$/.test(e.tagName) || e.hasAttribute('onclick')
    || e.getAttribute('role') === 'button' || getComputedStyle(e).cursor === 'pointer';
  const pick = (root) => {
    const list = [...root.querySelectorAll('button, a, [role=button], [onclick], input[type=button], summary, div, span')]
      .filter(e => vis(e) && !e.disabled && txt(e) && txt(e).length <= 30 && rx.test(txt(e)) && clickable(e));
    return list.find(e => !list.some(o => o !== e && e.contains(o)));   // 가장 안쪽 요소
  };
  let el = pick(f), box = f.parentElement;
  for (let k = 0; k < 3 && box && !el; k++, box = box.parentElement) el = pick(box);
  if (!el) return null;
  el.setAttribute('data-qa-demo', '1');
  return txt(el).slice(0, 30);
}
"""

# 폼(idx) 또는 <form> 없는 입력 묶음(idx=-1)의 입력칸 값 목록
FORM_FIELDS_JS = r"""
(idx) => {
  const f = idx >= 0 ? document.querySelectorAll('form')[idx] : document.querySelector('[data-qa-root]');
  if (!f) return [];
  return [...f.querySelectorAll('input')]
    .filter(i => !['hidden', 'submit', 'button', 'checkbox', 'radio', 'reset', 'image', 'file'].includes((i.type || 'text').toLowerCase()))
    .map(i => ({ type: (i.type || 'text').toLowerCase(), name: i.getAttribute('name') || i.id || i.type, value: i.value || '' }));
}
"""

# 로그인 폼 주변에 적힌 글자('체험 계정: demo@example.com / Demo1234!' 같은 안내를 찾기 위함)
DEMO_TEXT_JS = r"""
(idx) => {
  const f = document.querySelectorAll('form')[idx];
  if (!f) return [];
  const out = [];
  let box = f;
  for (let k = 0; k < 4 && box && box !== document.body; k++, box = box.parentElement) {
    for (const t of (box.innerText || '').split('\n')) { const s = t.trim(); if (s && !out.includes(s)) out.push(s); }
    if (out.length > 150) break;
  }
  return out.slice(0, 150);
}
"""

# 글자가 re와 맞는 보이는 버튼·링크·탭 하나에 번호표(attr)를 붙이고 글자를 돌려줌. 로그인 폼 가까운 것을 먼저 고름
FIND_TRIGGER_JS = r"""
([attr, re, loginName]) => {
""" + LOGIN_FORM_HELPER_JS + r"""
  document.querySelectorAll('[' + attr + ']').forEach(e => e.removeAttribute(attr));
  const vis = (e) => { const r = e.getBoundingClientRect(); const st = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
  const txt = (e) => (e.innerText || e.value || e.getAttribute('aria-label') || e.title || '').trim().replace(/\s+/g, ' ');
  const rx = new RegExp(re, 'i');
  const clickable = (e) => /^(BUTTON|A|SUMMARY|INPUT)$/.test(e.tagName) || e.hasAttribute('onclick')
    || ['button', 'tab', 'link', 'menuitem'].includes(e.getAttribute('role')) || getComputedStyle(e).cursor === 'pointer';
  const all = [...document.querySelectorAll('a, button, [role], [onclick], input[type=button], summary, div, span, li')]
    .filter(e => vis(e) && !e.disabled && clickable(e) && txt(e) && txt(e).length <= 24 && rx.test(txt(e)));
  const inner = all.filter(e => !all.some(o => o !== e && e.contains(o)));
  if (!inner.length) return null;
  const lf = loginName ? findLoginForm(loginName) : null;
  let near = null;
  if (lf) { near = lf; for (let k = 0; k < 4 && near.parentElement && near.parentElement !== document.body; k++) near = near.parentElement; }
  inner.sort((a, b) => ((near && near.contains(a)) ? 0 : 1) - ((near && near.contains(b)) ? 0 : 1));
  inner[0].setAttribute(attr, '1');
  return txt(inner[0]).slice(0, 20);
}
"""

# <form> 태그 없이 만든 가입 화면: 로그인 폼 밖에 보이는 비밀번호 칸을 감싼 묶음을 찾아 data-qa-root 번호표를 붙임
SIGNUP_ROOT_JS = r"""
([loginName]) => {
""" + LOGIN_FORM_HELPER_JS + r"""
  const vis = (e) => { const r = e.getBoundingClientRect(); const st = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
  document.querySelectorAll('[data-qa-root]').forEach(e => e.removeAttribute('data-qa-root'));
  const lf = findLoginForm(loginName);
  const pws = [...document.querySelectorAll('input[type=password]')].filter(e => vis(e) && !(lf && lf.contains(e)));
  if (!pws.length) return null;
  const SKIP = ['hidden', 'submit', 'button', 'reset', 'image', 'checkbox', 'radio', 'file'];
  const fields = (box) => [...box.querySelectorAll('input, textarea, select')].filter(e => vis(e) && !SKIP.includes((e.type || '').toLowerCase()));
  const pwIn = (box) => [...box.querySelectorAll('input[type=password]')].filter(vis).length;
  let box = pws[0], best = null;
  for (let k = 0; k < 6 && box.parentElement && box.parentElement !== document.body; k++) {
    box = box.parentElement;
    if (lf && box.contains(lf)) break;   // 로그인 폼까지 포함하면 너무 넓음
    if (pwIn(box) >= 2 || fields(box).length >= 3) best = box;
  }
  if (!best) return null;
  best.setAttribute('data-qa-root', '1');
  return { name: (best.getAttribute('id') || best.getAttribute('class') || best.tagName.toLowerCase()).slice(0, 30), fields: fields(best).length };
}
"""

# 가입 폼 안의 '인증번호 받기' 같은 인증 요청 버튼에 번호표(data-qa-auth-send)를 붙임('인증 확인'류는 제외)
AUTH_SEND_JS = r"""
([idx, sendRe]) => {
  document.querySelectorAll('[data-qa-auth-send]').forEach(e => e.removeAttribute('data-qa-auth-send'));
  const f = idx >= 0 ? document.querySelectorAll('form')[idx] : document.querySelector('[data-qa-root]');
  if (!f) return null;
  const vis = (e) => { const r = e.getBoundingClientRect(); const st = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
  const txt = (e) => (e.innerText || e.value || e.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
  const rx = new RegExp(sendRe, 'i'), not = /확인|완료|confirm|submit|제출/i;
  const el = [...f.querySelectorAll('button, input[type=button], a, [role=button], [onclick]')]
    .find(e => vis(e) && !e.disabled && rx.test(txt(e)) && !not.test(txt(e)));
  if (!el) return null;
  el.setAttribute('data-qa-auth-send', '1');
  return txt(el).slice(0, 20);
}
"""

# 화면에 보이는 인증번호 입력칸(data-qa-auth-code)과 그 옆 '확인' 버튼(data-qa-auth-ok)에 번호표를 붙임
# [v2] 열려 있는 창(모달) 안에서만 찾고, one-time-code·'인증번호' 표시가 있는 칸을 우선함. 이름·전화·쿠폰 칸은 제외
AUTH_CODE_JS = r"""
([hintRe, okRe]) => {
  document.querySelectorAll('[data-qa-auth-code],[data-qa-auth-ok]').forEach(e => { e.removeAttribute('data-qa-auth-code'); e.removeAttribute('data-qa-auth-ok'); });
  const vis = (e) => { const r = e.getBoundingClientRect(); const st = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
  const txt = (e) => (e.innerText || e.value || e.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
  const weak = new RegExp(hintRe, 'i'), ox = new RegExp(okRe, 'i');
  const STRONG = /인증\s*번호|인증\s*코드|보안\s*코드|확인\s*코드|otp|one[-_ ]?time|verification|verify[-_ ]?code|auth[-_ ]?(code|num|no)|authnum|cert[-_ ]?(code|num|no)|sms[-_ ]?code|\bpin\b/i;
  const NOT = /이름|성명|닉네임|name|e-?mail|이메일|메일|전화|휴대폰|핸드폰|연락처|phone|mobile|아이디|user|주소|address|검색|search|쿠폰|coupon|선물|gift|초대|invite|추천|referr|promo|할인|우편|zip|postal|상품권|voucher/i;
  const modals = [...document.querySelectorAll('dialog[open], [aria-modal="true"], [role=dialog], [role=alertdialog]')].filter(vis);
  const top = document.querySelector('dialog:modal') || modals[modals.length - 1] || null;
  const hintOf = (e) => {
    const parts = [e.getAttribute('placeholder'), e.getAttribute('aria-label'), e.getAttribute('name'), e.id, e.title];
    if (e.id) { try { const lb = document.querySelector(`label[for="${CSS.escape(e.id)}"]`); if (lb) parts.push(lb.innerText); } catch (err) {} }
    const wrap = e.closest('label'); if (wrap) parts.push(wrap.innerText);
    return parts.filter(Boolean).join(' ');
  };
  let input = null, best = 0;
  for (const e of (top || document).querySelectorAll('input, textarea')) {
    const t = (e.type || 'text').toLowerCase();
    if (['hidden', 'password', 'checkbox', 'radio', 'submit', 'button', 'file', 'image', 'email', 'date', 'time', 'range', 'color', 'search', 'url'].includes(t)) continue;
    if (!vis(e) || e.disabled || e.readOnly) continue;
    const otc = /one-time-code/i.test(e.getAttribute('autocomplete') || '');
    const own = hintOf(e);
    const strong = otc || STRONG.test(own);
    // 이름·전화·검색·쿠폰 칸은 'auth-name'·'gift-code'처럼 글자가 비슷해도 인증번호 칸이 아님
    if (!strong && (t === 'tel' || NOT.test(own) || !weak.test(own))) continue;
    const ml = e.maxLength > 0 ? e.maxLength : 0;
    const score = (otc ? 10 : 0) + (STRONG.test(own) ? 6 : 0) + (weak.test(own) ? 2 : 0) + (ml >= 4 && ml <= 8 ? 2 : 0)
                + (/numeric|decimal/i.test(e.getAttribute('inputmode') || '') ? 1 : 0);
    if (score > best) { input = e; best = score; }
  }
  if (!input) return null;
  input.setAttribute('data-qa-auth-code', '1');
  const NOT_OK = /재전송|다시|resend|받기|요청|발송|취소|닫기|중복|cancel|close/i;
  // 확인 버튼: ⓪ 인증번호 칸만 감싼 묶음(같은 줄) 안의 '확인·완료'류 버튼 ① 입력칸이 속한 폼의 제출 버튼 ② 가까운 상위 요소의 '확인·완료'류 버튼
  const okIn = (root) => [...root.querySelectorAll('button, input[type=button], input[type=submit], [role=button], [onclick], a')]
    .find(e => vis(e) && !e.disabled && ox.test(txt(e)) && !NOT_OK.test(txt(e))) || null;
  // [v6] 가입 폼처럼 입력칸이 여러 개인 폼 안의 인증번호 칸: 폼의 제출 버튼('가입하기')이 아니라 그 칸 옆의 '확인' 버튼이 인증 확인 버튼
  //      (인증을 끝내지 않은 채 '가입하기'를 눌러 '휴대폰 인증을 완료해주세요'에 막히던 문제)
  //      다른 입력칸이 섞인 묶음·폼 자체까지는 올라가지 않음 → 인증번호 칸만 있는 폼(2단계 인증 등)은 기존대로 ①
  const FIELD_SKIP = ['hidden', 'checkbox', 'radio', 'submit', 'button', 'reset', 'image', 'file'];
  const hasOtherField = (root) => [...root.querySelectorAll('input, textarea, select')]
    .some(e => e !== input && vis(e) && !FIELD_SKIP.includes((e.type || '').toLowerCase()));
  let ok = null;
  for (let row = input.parentElement, k = 0; k < 4 && row && row !== input.form && row !== document.body && !ok && !hasOtherField(row); k++, row = row.parentElement) ok = okIn(row);
  if (!ok && input.form) ok = [...input.form.querySelectorAll('button:not([type]), button[type=submit], input[type=submit]')]
    .find(e => vis(e) && !e.disabled && !NOT_OK.test(txt(e))) || null;
  let box = input;
  for (let k = 0; k < 4 && box.parentElement && !ok; k++) {
    box = box.parentElement;
    ok = okIn(box);
  }
  if (ok) ok.setAttribute('data-qa-auth-ok', '1');
  // 인증번호가 적혀 있을 수 있는 주변 글자(창 또는 입력칸을 감싼 폼)
  const around = top || input.form || input.parentElement;
  const ctx = ((around && around.innerText) || '').split('\n').map(s => s.trim()).filter(Boolean).slice(0, 80);
  return { maxlength: input.maxLength > 0 ? input.maxLength : 0, ok: ok ? txt(ok).slice(0, 20) : null, ctx,
           field: (input.id || input.getAttribute('name') || '').slice(0, 30) };
}
"""

# [v2] 눌렀던 인증 확인 버튼의 지금 글자·상태(인증 뒤 버튼이 '인증완료'로 바뀌는 화면을 알아보기 위함)
AUTH_OK_STATE_JS = r"""
() => { const b = document.querySelector('[data-qa-auth-ok]');
  return b ? { text: (b.innerText || b.value || '').trim().replace(/\s+/g, ' '), disabled: !!b.disabled } : null; }
"""

# [v2] 버튼·링크·라벨에 적힌 글자 목록(성공·실패 '문구'와 구별하기 위함)
CONTROL_LABELS_JS = r"""
() => { const out = new Set();
  for (const e of document.querySelectorAll('button, a, [role=button], [role=tab], input[type=button], input[type=submit], label, legend, option, summary')) {
    for (const s of ((e.innerText || e.value || '') + '').split('\n')) { const t = s.trim(); if (t) out.add(t); } }
  return [...out].slice(0, 3000); }
"""

# [v2] 열려 있는 창 안에 입력칸이 없고 '동의하고 계속하기' 같은 버튼만 있으면 그 버튼에 번호표(data-qa-continue)를 붙임
MODAL_CONTINUE_JS = r"""
(re) => {
  document.querySelectorAll('[data-qa-continue]').forEach(e => e.removeAttribute('data-qa-continue'));
  const vis = (e) => { const r = e.getBoundingClientRect(); const st = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
  const txt = (e) => (e.innerText || e.value || e.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
  const modals = [...document.querySelectorAll('dialog[open], [aria-modal="true"], [role=dialog], [role=alertdialog]')].filter(vis);
  const top = document.querySelector('dialog:modal') || modals[modals.length - 1];
  if (!top) return null;
  // 입력칸이 보이는 단계는 사람이 값을 넣어야 하므로 넘기지 않음
  if ([...top.querySelectorAll('input:not([type=hidden]):not([type=checkbox]):not([type=radio]), textarea, select')].some(e => vis(e) && !e.disabled)) return null;
  const rx = new RegExp(re, 'i'), not = /취소|닫기|거부|나중|cancel|close|deny|later|skip/i;
  const el = [...top.querySelectorAll('button, [role=button], input[type=button], input[type=submit], a[onclick], [onclick]')]
    .find(e => vis(e) && !e.disabled && rx.test(txt(e)) && !not.test(txt(e)));
  if (!el) return null;
  el.setAttribute('data-qa-continue', '1');
  return txt(el).slice(0, 20);
}
"""

# [v2] 로그인 폼 주변에서 '빠른 로그인'·'체험 계정' 같은 계정 안내 영역을 찾아, 그 안의 '입력'·'채우기' 버튼에 번호표(data-qa-demo)를 붙임
DEMO_ZONE_JS = r"""
([idx, zoneRe, fillRe]) => {
  const f = document.querySelectorAll('form')[idx];
  if (!f) return null;
  document.querySelectorAll('[data-qa-demo]').forEach(e => e.removeAttribute('data-qa-demo'));
  const vis = (e) => { const r = e.getBoundingClientRect(); const st = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
  const txt = (e) => (e.innerText || e.value || e.getAttribute('aria-label') || e.title || '').trim().replace(/\s+/g, ' ');
  const zx = new RegExp(zoneRe, 'i'), fx = new RegExp(fillRe, 'i');
  let box = f.parentElement;
  for (let k = 0; k < 3 && box && box !== document.body; k++, box = box.parentElement) {
    const zones = [...box.querySelectorAll('div, section, aside, ul, ol, li, table, tr, fieldset, p')]
      .filter(z => !z.contains(f) && !f.contains(z) && vis(z) && (z.innerText || '').length <= 400 && zx.test(z.innerText || ''));
    const inner = zones.filter(z => !zones.some(o => o !== z && z.contains(o)));   // 가장 작은 묶음부터
    for (const z of inner) {
      const btn = [...z.querySelectorAll('button, [role=button], input[type=button], a[onclick], [onclick]')]
        .find(b => vis(b) && !b.disabled && txt(b).length <= 20 && fx.test(txt(b)));
      if (btn) { btn.setAttribute('data-qa-demo', '1');
        return { label: txt(btn).slice(0, 20), zone: ((z.innerText || '').trim().split('\n')[0] || '').trim().slice(0, 20) }; }
    }
  }
  return null;
}
"""

# [v2] 지금 보이는 폼 목록(번호·이름·비밀번호 칸 수). 창(dialog)이 열려 있으면 그 안의 폼만
FORMS_INFO_JS = """
() => {
  const modal = document.querySelector('dialog:modal');
  return [...document.querySelectorAll('form')].flatMap((form, index) => {
    if (form.closest('[inert]') || (modal && !modal.contains(form))) return [];
    const { width, height } = form.getBoundingClientRect();
    if (!(width > 0 && height > 0 && getComputedStyle(form).visibility === 'visible')) return [];
    const name = (form.getAttribute('id') || form.getAttribute('name') || form.getAttribute('class') || ('form' + index)).slice(0, 30);
    return [{ idx: index, name, pw: form.querySelectorAll('input[type=password]').length }];
  });
}
"""

# [v2] 글자가 같은 클릭 요소 하나에 번호표(data-qa-opener)를 붙임(클릭해야 나타나는 로그인 창을 다시 열기 위함)
OPENER_JS = r"""
([sel, tag, text]) => {
  document.querySelectorAll('[data-qa-opener]').forEach(e => e.removeAttribute('data-qa-opener'));
  for (const el of document.querySelectorAll(sel)) {
    if (el.tagName.toLowerCase() !== tag || el.disabled) continue;
    const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
    if (!(r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none')) continue;
    const t = (el.innerText || el.value || el.getAttribute('aria-label') || el.title || '').trim().replace(/\s+/g, ' ').slice(0, 40);
    if (t === text) { el.setAttribute('data-qa-opener', '1'); return true; }
  }
  return false;
}
"""

# [v2] '바로 주문' 같은 버튼(폼 밖) 하나에 번호표(data-qa-prep)를 붙임
PREP_BTN_JS = r"""
(re) => {
  document.querySelectorAll('[data-qa-prep]').forEach(e => e.removeAttribute('data-qa-prep'));
  const rx = new RegExp(re, 'i');
  for (const el of document.querySelectorAll('button, a, [role=button], input[type=button]')) {
    if (el.closest('form') || el.disabled) continue;
    const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
    if (!(r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none')) continue;
    const t = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
    if (t && t.length <= 20 && rx.test(t)) { el.setAttribute('data-qa-prep', '1'); return t; }
  }
  return null;
}
"""

# [v4] 폼의 첫 글자 입력칸에 번호표(data-qa-enter)를 붙임(Enter 키 제출 확인용). 폼 이름이 다르면(화면이 바뀜) 붙이지 않음
ENTER_TARGET_JS = """
([idx, name]) => {
  document.querySelectorAll('[data-qa-enter]').forEach(e => e.removeAttribute('data-qa-enter'));
  const f = document.querySelectorAll('form')[idx];
  if (!f) return false;
  const identity = (f.getAttribute('id') || f.getAttribute('name') || f.getAttribute('class') || ('form' + idx)).slice(0, 30);
  if (identity !== name) return false;
  const el = [...f.querySelectorAll('input')].find(i => {
    const t = (i.type || 'text').toLowerCase();
    if (!['text', 'search', 'email', 'tel', 'url', 'number'].includes(t) || i.disabled || i.readOnly) return false;
    const r = i.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(i).visibility !== 'hidden';
  });
  if (!el) return false;
  el.setAttribute('data-qa-enter', '1');
  return true;
}
"""

# [v5] '마이페이지'·'내 정보' 같은 계정 메뉴(폼 밖, 보이는 것) 하나에 번호표(data-qa-account)를 붙임. tried에 있는 글자는 건너뜀
ACCOUNT_LINK_JS = r"""
([re, tried]) => {
  document.querySelectorAll('[data-qa-account]').forEach(e => e.removeAttribute('data-qa-account'));
  const rx = new RegExp(re, 'i');
  for (const el of document.querySelectorAll('a, button, [role=button], [role=menuitem], [role=tab], summary, [onclick]')) {
    if (el.disabled || el.closest('form')) continue;
    const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
    if (!(r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none')) continue;
    const t = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
    if (!t || t.length > 20 || tried.includes(t) || !rx.test(t)) continue;
    el.setAttribute('data-qa-account', '1');
    return t;
  }
  return null;
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
def state_hash(page, with_values=False):
    try:
        text = page.evaluate(STATE_JS)
        if with_values:
            text += "|" + page.evaluate(FIELD_VALUES_JS)
        return hashlib.md5(text.encode("utf-8")).hexdigest()
    except PWError:
        return ""


def visual_hash(page):
    try:
        return hashlib.md5(page.evaluate(VISUAL_JS).encode("utf-8")).hexdigest()
    except PWError:
        return ""


def reaction_detail(url_ch, dom_ch, vis_ch, has_event, vis_skipped=False, with_values=True):
    """'반응 없음' 판정에 쓴 비교 항목별 결과를 한 줄로 만듦"""
    yn = lambda ch: "변화 있음" if ch else "변화 없음"
    vis = "겉모습 비교 제외(화면이 혼자 움직여 구분 불가)" if vis_skipped else f"겉모습(위치·색·투명도) {yn(vis_ch)}"
    return (f"주소 {yn(url_ch)} / 화면 구조{'·입력값' if with_values else ''} {yn(dom_ch)} / {vis} / "
            f"알림·새 탭·다운로드 {'있음' if has_event else '없음'}")


def pattern(text):
    """'favorite('ST-012')' / '#/stations/12' 같은 반복 요소를 같은 패턴으로 묶기"""
    text = re.sub(r"\(.*\)", "()", text or "")
    text = re.sub(r"\d+", "N", text)
    if text.count("/") >= 2:                     # #/regions/서울 → #/regions/*
        text = text.rsplit("/", 1)[0] + "/*"
    text = re.sub(r"(id|no|seq|item)=[^&#]*", r"\1=*", text)
    return text


def account_text(keys=("email", "password")):
    """수동 체크 흐름에 보여줄 테스트 계정 문자열 (예: test@test.com / test123456)"""
    return " / ".join(TEST_ACCOUNT[k] for k in keys)


EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def parse_demo_credentials(lines):
    """
    화면 글자에서 '체험 계정: demo@example.com / Demo1234!' 또는 '아이디: demo  비밀번호: 1234' 같은 안내를 찾아
    {'email' 또는 'id': 값, 'password': 값}을 돌려줌. 못 찾으면 None.
    """
    for i, line in enumerate(lines):
        m0 = re.search(DEMO_LINE_RE, line, re.I)
        if not m0:
            continue
        text = " ".join(lines[i:i + 2])
        m0 = re.search(DEMO_LINE_RE, text, re.I)
        text = text[m0.start():]
        m = re.search(r"(?:아이디|\bid\b|이메일|\be-?mail\b)\s*[:：=]?\s*([^\s,/|·]+).{0,12}?"
                      r"(?:비밀번호|비번|password|\bpw\b|\bpass\b)\s*[:：=]?\s*([^\s,/|·]{3,40})", text, re.I)
        if m:
            user, pw = m.group(1), m.group(2)
        else:
            em = EMAIL_RE.search(text)
            if not em:
                continue
            m2 = re.match(r"[\s/,|·:：]*(?:비밀번호|비번|password|\bpw\b|\bpass\b)?\s*[:：=]?\s*([^\s,/|·]{3,40})",
                          text[em.end():], re.I)
            if not m2:
                continue
            user, pw = em.group(0), m2.group(1)
        return {("email" if "@" in user else "id"): user.rstrip(".,;)"), "password": pw.rstrip(".,;)")}
    # [v2] '빠른 로그인' 같은 안내 근처에 'demo@example.com / Demo1234!'처럼 이메일 / 비밀번호만 적힌 줄
    for i, line in enumerate(lines):
        em = EMAIL_RE.search(line)
        if not em or not any(re.search(DEMO_ZONE_RE, x, re.I) for x in lines[max(0, i - 3):i + 1]):
            continue
        m2 = re.match(r"\s*[/|,·:：]\s*(?:비밀번호|비번|password|\bpw\b|\bpass\b)?\s*[:：=]?\s*([^\s,/|·]{4,40})\s*$", line[em.end():], re.I)
        if m2:
            return {"email": em.group(0).rstrip(".,;)"), "password": m2.group(1).rstrip(".,;)")}
    return None


AUTH_CODE_NEAR_RE = re.compile(r"(?:인증\s*번호|인증\s*코드|보안\s*코드|확인\s*코드|otp|verification code|코드|code)"
                               r"\D{0,15}?(?<![\d-])(\d{4,8})(?![\d-])", re.I)


def extract_auth_code(texts, strict=False):
    """
    알림·화면 문구에서 '인증번호: 482913' 같은 안내 번호를 찾음. (번호, 화면에 안내된 값인지). 없으면 ('', False)
    [v2] '인증번호' 같은 말 바로 뒤에 오는 번호를 먼저 찾음.
         strict=True면 그런 번호만 인정(인증창 안의 다른 숫자를 인증번호로 오인하지 않도록).
    """
    for t in texts:
        m = AUTH_CODE_NEAR_RE.search(t)
        if m:
            return m.group(1), True
    if strict:
        return "", False
    for t in texts:
        if not re.search(r"인증|코드|번호|code|otp|pin", t, re.I):
            continue
        m = re.search(r"(?<![\d-])(\d{4,8})(?![\d-])", t)
        if m:
            return m.group(1), True
    return "", False


def classify_click_error(full_msg):
    """
    Playwright 예외 전문(콜 로그 포함)에서 실제 원인을 찾아 (구분, 내용)으로 돌려줌.
    첫 줄만 보면 'Timeout 2000ms exceeded'만 남아 원인을 알 수 없으므로 전체를 검사.
    """
    m = re.search(r"(<[^>\n]{1,200}>)[^\n]*intercepts pointer events", full_msg)
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


class CoveredError(PWError):
    """클릭이 다른 요소에 계속 가려져 실패. info에 가리는 요소 정보가 들어 있음"""
    info = None


# 요소 가운데 지점에서 맨 위에 있는 요소를 조사(가림 진단). 가려져 있지 않으면 null
COVER_AT_JS = r"""
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  el.scrollIntoView({ block: 'center', inline: 'center' });
  const r = el.getBoundingClientRect();
  if (!r.width || !r.height) return null;
  const x = Math.min(Math.max(r.left + r.width / 2, 0), innerWidth - 1), y = Math.min(Math.max(r.top + r.height / 2, 0), innerHeight - 1);
  const top = document.elementFromPoint(x, y);
  if (!top || el === top || el.contains(top)) return null;
  const lab = top.closest('label');
  if (lab && lab.control === el) return null;
  const st = getComputedStyle(top), tr = top.getBoundingClientRect();
  const area = Math.round(100 * Math.min(tr.width, innerWidth) * Math.min(tr.height, innerHeight) / (innerWidth * innerHeight));
  const cls = (typeof top.className === 'string' && top.className.trim()) ? '.' + top.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
  const bg = st.backgroundColor;
  const clear = parseFloat(st.opacity) < 0.1 || ((bg === 'rgba(0, 0, 0, 0)' || /,\s*0(\.0\d*)?\)$/.test(bg)) && !(top.innerText || '').trim() && !top.querySelector('img, svg, canvas'));
  return { who: '<' + top.tagName.toLowerCase() + (top.id ? '#' + top.id : '') + cls + '>', pos: st.position, z: st.zIndex,
           area, fixed: st.position === 'fixed' || st.position === 'sticky', clear, w: innerWidth, h: innerHeight };
}
"""


class FileTester:
    def __init__(self, browser, html_file: Path, origin: str, inner_bar: tqdm, stage_cb=None, label=""):
        self.file = html_file
        self.stage_cb = stage_cb      # 단계가 바뀔 때 호출(전체 진행률 갱신용)
        self.label = label            # 안쪽 진행 막대 앞에 붙일 '파일 3/100 이름'
        self.demo_ok = set()          # 체험 계정으로 로그인이 확인된 로그인 폼
        self.last_demo = None         # 직전 제출에서 쓴 체험 계정 정보
        self.last_auth = None         # 직전 제출 직후 인증창 결과(ok/fail/unknown/None)
        # ── [v2] 인증 패치용 상태 ──
        self.revealed_forms = []      # 버튼을 눌러야 나타나는 로그인 폼 {url, name, tag, text, label}
        self.revealed_names = set()
        self.route_forms = {}         # url -> 처음부터 보이는 폼 이름
        self.guest_form_names = set() # 비로그인 상태에서 본 폼 이름(회원 전용 화면에서 '새 폼'을 가려내기 위함)
        self.guest_routes = []        # 비로그인 상태에서 찾은 화면 목록
        self.login_ok = set()         # 제출(+인증번호) 뒤 로그인 상태 표시까지 확인된 폼
        self.soft_where = set()       # 클릭해야 나타나는 창의 폼(문제는 '수동'으로 낮춰 기록)
        self.last_steps = []          # 직전 제출 뒤 넘긴 중간 단계 버튼('동의하고 계속하기' 등)
        self._chain_login = None      # 가입 → 로그인 연속 검사에 쓴 로그인 폼
        self._mute = False            # True인 동안은 결과를 기록하지 않음(준비 단계용)
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
        # 로그인 폼 단독 제출 때 나온 실패 문구. 가입 전에는 계정이 없어 실패하는 게 당연하므로 바로 기록하지 않고
        # '가입 → 로그인' 연속 검사 결과를 본 뒤 결정. where -> (실패 문구, 체크 흐름)
        self.login_fail_pending = {}
        self.closed_popups = set()    # 검사 전에 자동으로 닫은 팝업 이름
        self.chain_passed = False
        self.last_had_error = False
        self.login_state_checked = False
        self.cal_status = set()       # 캘린더 점검 결과 종류: 일치/불일치/확인 필요
        self.cal_lib_noted = set()
        self.events = []     # 클릭 중 발생한 이벤트
        self.cdn_failed = set()   # 불러오지 못한 외부 스크립트/CSS 호스트
        self.persistent_cover = False  # 오래 가리는 요소를 이미 발견했는지(이후 대기 시간을 줄임)
        self.context = browser.new_context(accept_downloads=True,
                                           viewport={"width": VIEWPORT_SIZE[0], "height": VIEWPORT_SIZE[1]})
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
        if self._mute:   # [v2] 준비 단계(회원 전용 화면 검사를 위한 로그인 등)에서는 기록하지 않음
            return
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
        self.close_popups()

    def close_popups(self, tries=3):
        """
        저절로 떠 있는 팝업을 닫음. 닫기 버튼이 있으면 누르고, 없으면 Esc를 누르고 잠시 기다림(로딩 화면 등).
        닫은 팝업 이름은 self.closed_popups에 모아 '수동' 항목으로 남김. 닫지 못하면 그대로 둠.
        """
        if not CLOSE_POPUPS:
            return
        for _ in range(tries):
            try:
                found = self.page.evaluate(POPUP_SCAN_JS, [POPUP_NAME_RE, POPUP_CLOSE_TEXT_RE])
            except PWError:
                return
            if not found:
                return
            before = state_hash(self.page)
            try:
                if found["button"]:
                    self.page.locator("[data-qa-close]").first.click(timeout=1000)
                else:
                    self.page.keyboard.press("Escape")
                    self.page.wait_for_timeout(500)
            except PWError:
                pass
            self.page.wait_for_timeout(CLICK_WAIT_MS)
            self.wait_settled()
            if state_hash(self.page) == before:
                return   # 닫히지 않음 → 더 시도해도 같으므로 중단
            self.closed_popups.add(found["label"])

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
            digits = [pr for pr in props["result"] if pr["name"].isdigit()]
            for k, prop in enumerate(digits):
                ls = cdp.send("DOMDebugger.getEventListeners", {"objectId": prop["value"]["objectId"]})["listeners"]
                if any(l["type"] in CLICK_EVENT_TYPES for l in ls):
                    # 요소 자신 / 상위 요소 / 문서 전체(body·html·document·window — 분석·프레임워크 위임일 수 있음)
                    return "own" if k == 0 else ("global" if k >= len(digits) - 4 else "ancestor")
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
        self.guest_routes = list(routes)   # [v2] 회원 전용 화면 검사 때 다시 열어 볼 목록
        return routes

    # ── 2단계: 모든 클릭 요소 테스트 (+ 클릭 후 나타난 버튼까지 한 단계 더) ──
    def _prepare(self, url):
        """화면을 새로 열고 번호표를 다시 붙임(번호는 같은 화면이면 항상 같은 순서)"""
        self.goto(url)
        self.page.evaluate(TAG_ELEMENTS_JS, CLICKABLE_SELECTOR)
        self.events = []

    def _storage(self):
        try:
            return self.page.evaluate(STORAGE_JS)
        except PWError:
            return {}

    def _cover_at(self, selector):
        try:
            return self.page.evaluate(COVER_AT_JS, selector)
        except PWError:
            return None

    def _wait_uncovered(self, selector):
        """다른 요소가 덮고 있으면 풀리길 기다림(로딩 화면 등). 끝까지 가려져 있으면 가리는 요소 정보, 풀리면 None"""
        limit = 1500 if self.persistent_cover else COVER_WAIT_MS   # 오래 가리는 요소를 이미 봤다면 길게 기다리지 않음
        waited, info = 0, self._cover_at(selector)
        while info and waited < limit:
            self.page.wait_for_timeout(300)
            waited += 300
            info = self._cover_at(selector)
        if info:
            self.persistent_cover = True
        return info

    def _probe_js_click(self, selector):
        """사람은 못 누르지만 코드로 직접 누르면 동작하는지: 'yes'(동작함) / 'no'(변화 없음) / None(확인 못함)"""
        try:
            before_url, before_state = self.page.url, state_hash(self.page, with_values=True)
            self.events = []
            if not self.page.evaluate("(s) => { const e = document.querySelector(s); if (!e) return false; e.click(); return true; }", selector):
                return None
            self.page.wait_for_timeout(CLICK_WAIT_MS)
            self.wait_settled()
            seen = any(k in ("dialog", "popup", "download") for k, _ in self.events)
            self.events = []
            changed = (seen or before_url.split("#", 1)[0] != self.page.url.split("#", 1)[0]
                       or before_state != state_hash(self.page, with_values=True))
            return "yes" if changed else "no"
        except PWError:
            return None

    def _click_error(self, e, selector, where, step, flow=None):
        """클릭 예외를 기록. 가려짐이면 가리는 요소의 정체와 '코드로 누르면 동작하는지'까지 적음"""
        text = str(e)
        level, msg = classify_click_error(text)
        if "intercepts pointer events" in text:
            info = getattr(e, "info", None) or self._cover_at(selector)
            probe = self._probe_js_click(selector)
            tail = {"yes": " · 코드로 직접 누르면 동작함(기능은 구현돼 있고 위치 겹침이 문제)",
                    "no": " · 코드로 직접 눌러도 변화 없음(가려짐과 별개로 반응이 없음)", None: ""}[probe]
            if not info:
                level, msg = "주의", "다른 요소에 가려져 클릭 불가(가리는 요소는 확인하지 못함 — 일시적인 로딩·애니메이션일 수 있음)" + tail
            else:
                if info["area"] >= 50:
                    kind = (f"화면의 {info['area']}%를 덮는 {info['who']}(position:{info['pos']}, z-index:{info['z']})가 위에 있음"
                            f" — 모달·로딩 화면·안내 배너가 닫히지 않은 상태일 수 있음")
                elif info["fixed"]:
                    kind = (f"고정 영역 {info['who']}(position:{info['pos']})가 가림 — 스크롤해도 같은 자리에서 가려짐"
                            f"(화면 {info['w']}x{info['h']} 기준)")
                else:
                    kind = (f"{info['who']}(position:{info['pos']}, z-index:{info['z']}{', 투명' if info['clear'] else ''})가 위에 겹쳐 있음"
                            f" — 위쪽 요소의 z-index·pointer-events 확인")
                level, msg = "주의", f"다른 요소에 가려져 클릭 불가: {kind}{tail}"
        self.add(level, where, msg, flow or f"{step} → 눌리는지, 다른 요소에 가려지거나 숨겨져 있지 않은지 확인")

    def _judge_click(self, selector, where, step, href):
        """
        selector 요소를 클릭하고 반응을 판정해 기록. (changed, url_changed)를 돌려줌.
        요소가 없으면 None. 클릭 예외는 호출한 쪽에서 처리.
        """
        loc = self.page.locator(selector)
        if loc.count() == 0:
            return None
        try:
            loc.first.hover(timeout=1000)   # hover 효과를 클릭 반응으로 오인하지 않도록 먼저 올려 둠
        except PWError:
            pass
        self.page.wait_for_timeout(120)
        before_visual = visual_hash(self.page)
        self.page.wait_for_timeout(150)
        animated = before_visual != visual_hash(self.page)   # 혼자 움직이는 화면은 겉모습 비교 제외
        before_url, before_state = self.page.url, state_hash(self.page, with_values=True)
        store_before = self._storage()
        handler = self.has_click_handler(selector)   # 클릭 전에 확인(클릭 후엔 화면이 바뀔 수 있음)
        try:
            selected = bool(loc.first.evaluate(SELECTED_JS))   # 클릭 전 상태로 확인(클릭 후엔 바뀔 수 있음)
        except PWError:
            selected = False
        try:
            loc.first.click(timeout=2000)
        except PWError as e:
            # 다른 요소에 가려졌으면: 떠 있는 팝업 닫기 → 가림이 풀리길 기다림(로딩 화면 등) → 한 번 더 클릭
            # (고정 헤더·잠깐 떴다 사라지는 안내창·로딩 화면 때문에 사람은 되는데 자동 클릭만 막히는 경우)
            if "intercepts pointer events" not in str(e):
                raise
            self.close_popups()
            info = self._wait_uncovered(selector)
            if info:   # 끝까지 가려져 있음 → 가리는 요소 정보를 붙여 호출한 쪽에 전달
                err = CoveredError(str(e))
                err.info = info
                raise err from e
            before_url, before_state = self.page.url, state_hash(self.page, with_values=True)
            before_visual = visual_hash(self.page)
            store_before = self._storage()
            animated = False
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
        visual_changed = (not animated) and before_visual != visual_hash(self.page)
        changed = url_changed or (before_state != after_state) or bool(rest) or visual_changed
        waited = 0
        if not changed and not self.last_had_error:
            if self._storage() != store_before:   # 화면은 그대로이고 저장소만 바뀜 → 저장·찜 같은 기능
                changed = True
                self.add("수동", where, "화면 변화 없이 저장소(localStorage·sessionStorage)만 바뀜 — 저장·찜 같은 기능이면 정상", step)
            elif LATE_WAIT_MS > 0 and handler is not False:   # 반응이 늦게 나타나는지 더 기다림
                while waited < LATE_WAIT_MS and not changed:
                    self.page.wait_for_timeout(300)
                    waited += 300
                    changed = (before_url.split("#", 1)[0] != self.page.url.split("#", 1)[0]
                               or state_hash(self.page, with_values=True) != before_state
                               or ((not animated) and visual_hash(self.page) != before_visual)
                               or bool(self.events) or self._storage() != store_before)
                rest2 = self.flush_errors(where, step)
                self.check_downloads(rest2, where, step)
                changed = changed or bool(rest2)
                url_changed = before_url.split("#", 1)[0] != self.page.url.split("#", 1)[0]
                if changed:
                    self.add("수동", where, f"반응이 늦음: 클릭 후 약 {CLICK_WAIT_MS + waited}ms 뒤에 화면·알림이 바뀜", step)
        href = (href or "").strip()
        if not changed and self.last_had_error:
            pass   # 오류가 이미 원인으로 기록됨('반응 없음' 중복 방지)
        elif not changed and handler is False:
            self.add("경고", where, "클릭해도 반응 없음(연결된 클릭 이벤트가 전혀 없음 — 미구현 메뉴/버튼)",
                     f"{step} → 반응이 없으면 onclick·링크 연결 누락")
        elif not changed and href in DEAD_HREFS and href:
            self.add("주의", where, f"href='{href}' 링크 클릭 시 반응 없음",
                     f"{step} → 의도된 빈 링크인지 확인(아니면 실제 주소·동작 연결)")
        elif not changed and selected:
            self.add("수동", where, "이미 선택된 항목이라 클릭해도 변화 없음(정상일 가능성 높음)",
                     f"{step} → 다른 항목으로 바꾼 뒤 이 항목을 다시 눌러 정상 전환되는지 확인")
        elif not changed and REPORT_NO_RESPONSE:
            detail = (f"{step} → 1~2초 기다려 화면 변화·알림·이동이 있는지 확인"
                      f" | 판정 근거: {reaction_detail(url_changed, before_state != after_state, visual_changed, bool(rest), animated)}"
                      f" / 클릭 후 {CLICK_WAIT_MS + waited}ms + 화면 안정 대기 / 클릭 처리 위치: {handler or '확인 불가'}")
            watched = f"클릭 후 약 {CLICK_WAIT_MS + waited}ms 동안 주소·화면 구조·입력칸 값·겉모습·알림·저장소를 비교했으나 변화 없음"
            if handler == "global":
                self.add("경고", where, f"클릭해도 반응 없음 · 이 요소·상위 요소에는 클릭 처리가 없고 문서 전체(document·window·body) 리스너만 있음"
                                        f" — 미구현 가능성 높음({watched})", detail)
            else:
                known = "클릭 처리는 연결돼 있음" if handler else "클릭 처리 연결 여부는 확인 못함"
                self.add("주의", where, f"클릭해도 화면 변화 없음 · {known}({watched}) — 체크·입력 같은 조건이 필요하거나 저장만 하는 버튼이면 정상일 수 있음", detail)
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
                self.route_forms[url] = self._form_names()   # [v2] 처음부터 보이는 폼(클릭 후 새로 나타난 폼과 구별)
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
                        self._note_revealed_forms(url, el, label)   # [v2] 클릭으로 나타난 로그인 창
                        kids = self._new_clickables(url)
                        if kids:
                            self.test_children(url, el, where, step, kids)
                            dirty = True
            except PWError as e:
                self._click_error(e, f'[data-qa-id="{el["id"]}"]', where, step)
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
            sel = f'[data-qa-id="{parent["id"]}"]'
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
                    sel = f'[data-qa-cid="{match["cid"]}"]'
                    self._judge_click(sel, where, step, k["href"])
            except PWError as e:
                self._click_error(e, sel, where, step)
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
            sel = "[data-qa-hover]"
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
                sel = "[data-qa-hid]"
                self._judge_click(sel, where, step, "")
            except PWError as e:
                self._click_error(e, sel, f"{self.route_name(url)} > '{text}'(hover 메뉴)", "",
                                  flow=f"{self.open_step(url)} → 상위 메뉴에 마우스 올리기 → '{text}' 클릭되는지 확인")
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
    def _fill_form(self, idx, mode=None, acct=None, keep=False, opt=None):
        return self.page.evaluate(FILL_FORM_JS, [idx, acct or TEST_ACCOUNT, mode or LOGIN_KEY_ORDER[0], keep, opt or {}])

    def _press(self, selector):
        self.page.locator(selector).first.click(timeout=2000)

    def _submit_form(self, idx, mode=None, precheck=False, demo=False, where=None, flow="", post_auth=False,
                     keep=False, fill_opt=None, steps=False):
        """
        폼 idx를 채워 제출. (info, changed, 새로 나타난 문구·알림 목록, rest)를 돌려줌.
        idx=-1이면 <form> 태그 없이 만든 입력 묶음(data-qa-root)을 같은 방식으로 채워 제출.
        사람처럼 '제출 버튼'을 눌러 제출함. 가입 버튼에 onclick만 달린 화면(<form onsubmit="return false">
        + <button type="button" onclick="signup()">)은 폼 제출 이벤트만 보내면 아무 일도 안 일어나기 때문.
        버튼을 못 찾을 때만 폼 제출 이벤트(requestSubmit)를 보냄. precheck=True면 '중복확인' 버튼을 먼저 누름.
        demo=True면 체험 계정(처음부터 채워진 값 → 자동 입력 버튼 → 화면에 적힌 계정 순)을 TEST_ACCOUNT보다 먼저 사용.
        where를 주면 인증창도 확인: precheck=True면 제출 전에 '인증번호 받기 → 번호 입력 → 확인',
        post_auth=True면 제출 직후 새로 뜬 인증창(로그인 2단계 인증 등)에서 같은 확인을 함.
        """
        if idx >= 0 and idx not in self.page.evaluate(VISIBLE_FORMS_JS, False):
            return None, False, [], []
        self.last_demo, self.last_auth, self.last_steps = None, None, []
        if demo:
            self.last_demo = self._prepare_demo(idx, where or "로그인 폼", flow)
        d = self.last_demo
        if d:
            info = self._fill_form(idx, d.get("mode") or mode, d.get("acct"), d.get("keep", False))
            if info:
                info["used"] = {"체험 계정": d["how"]}
        else:
            info = self._fill_form(idx, mode, None, keep, fill_opt)   # [v2] keep·fill_opt: 회원 전용 화면·인증 폼용
        if not info:
            return None, False, [], []
        if precheck:
            pres = self.page.evaluate(SUBMIT_TARGET_JS, [idx, "precheck", PRECHECK_RE]) or []
            for i in range(len(pres)):
                try:
                    self._press(f'[data-qa-pre="{i}"]')
                    self.page.wait_for_timeout(CLICK_WAIT_MS)
                except PWError:
                    pass
            if pres:
                self.wait_settled()
            info["precheck"] = pres
            if where and AUTH_TEST:
                self._run_auth(idx, where, flow, allow_send=True)   # 가입 중 인증창이 실제로 되는지
        had_code = bool(self._auth_info()) if (post_auth and where and AUTH_TEST) else False
        # 번호표(data-qa-submit) 붙이기가 화면 지문을 바꾸므로, 비교 기준은 번호표를 붙인 뒤에 잡음
        label = self.page.evaluate(SUBMIT_TARGET_JS, [idx, "submit", PRECHECK_RE])
        info["via"] = label
        before_url, before_state = self.page.url, state_hash(self.page)
        before_visual = visual_hash(self.page)
        before_text = set(self.page.evaluate(TEXT_LINES_JS))
        try:
            self.page.evaluate("() => { window.__qaAlive = 1 }")   # [v4] 제출로 화면이 통째로 다시 열렸는지 알아보기 위한 표시
        except PWError:
            pass
        if label:
            self._press("[data-qa-submit]")
        elif idx >= 0:
            self.page.evaluate("(i) => { const f = document.querySelectorAll('form')[i]; f.requestSubmit ? f.requestSubmit() : f.submit(); }", idx)
        else:   # <form> 태그가 없고 제출 버튼도 못 찾음 → 마지막 입력칸에서 Enter
            self.page.evaluate("() => { const r = document.querySelector('[data-qa-root]'); const l = r && [...r.querySelectorAll('input')]"
                               ".filter(i => !['hidden','checkbox','radio','submit','button'].includes(i.type)).pop(); if (l) l.focus(); }")
            self.page.keyboard.press("Enter")
        self.page.wait_for_timeout(CLICK_WAIT_MS + 200)
        try:
            self.page.locator('[data-qa-submit][aria-busy="true"]:visible, form[aria-busy="true"]:visible').first.wait_for(
                state="hidden", timeout=12000)
        except PWTimeout as e:
            raise PWError("제출 처리 중 상태가 12초 안에 해제되지 않음") from e
        self.wait_settled()

        def _changed():
            return (before_url != self.page.url or before_state != state_hash(self.page)
                    or before_visual != visual_hash(self.page))
        waited = 0
        while not _changed() and not self.events and waited < SUBMIT_WAIT_MS:   # 느린 응답 대기
            self.page.wait_for_timeout(100)
            waited += 100
        try:
            new_text = [t for t in self.page.evaluate(TEXT_LINES_JS) if t not in before_text]
        except PWError:
            new_text = []
        url_ch = before_url != self.page.url
        dom_ch = before_state != state_hash(self.page)
        vis_ch = before_visual != visual_hash(self.page)
        changed = url_ch or dom_ch or vis_ch
        try:
            reloaded = not self.page.evaluate("() => window.__qaAlive === 1")   # [v4] 표시가 사라졌으면 화면이 다시 열린 것(새로고침·이동)
        except PWError:
            reloaded = True
        self.last_submit = {   # '반응 없음' 메시지에 근거로 보여 줄 값
            "via": label, "used": info.get("used") or {}, "url": url_ch, "dom": dom_ch, "vis": vis_ch,
            "events": any(k not in ("jserror", "console", "resource", "brokenlink") for k, _ in self.events),
            "waited": CLICK_WAIT_MS + 200 + waited, "reloaded": reloaded,
        }
        # 제출 직후 '새로' 뜬 인증창(로그인 2단계 인증 등): 오류로 보지 않고 실제로 되는지 확인
        if post_auth and where and AUTH_TEST and not had_code:
            if steps and not self._auth_info():
                self.last_steps = self._pass_modal_steps()   # [v2] '동의하고 계속하기' 같은 중간 단계를 넘김
            if self._auth_info():
                try:
                    now_text = self.page.evaluate(TEXT_LINES_JS)
                except PWError:
                    now_text = []
                # 인증번호가 알림·화면에 적혀 있을 수 있음
                seed = [v for k, v in self.events if k == "dialog"] + [t for t in now_text if t not in before_text]
                self.last_auth = self._run_auth(None, where, flow, allow_send=False, seed_texts=seed)
                changed = True
                if self.last_auth == "ok":   # 인증까지 끝난 뒤 화면 기준으로 다시 비교
                    new_text = [t for t in self.page.evaluate(TEXT_LINES_JS) if t not in before_text]
                else:
                    new_text = []   # 인증창 문구를 로그인 실패 문구로 오인하지 않음(인증창 결과는 따로 기록됨)
            elif self.last_steps:
                changed = True
                new_text = [t for t in self.page.evaluate(TEXT_LINES_JS) if t not in before_text]
        return info, changed, new_text, []

    def _submit_detail(self):
        """직전 제출의 눌린 버튼·입력값·비교 결과·대기 시간을 '확인 방법' 칸에 붙일 글로 만듦"""
        d = getattr(self, "last_submit", None)
        if not d:
            return ""
        names = {"id": "아이디", "email": "이메일", "password": "비밀번호", "name": "이름", "phone": "전화번호"}
        used = ", ".join(names.get(k, k) if k == "password" else f"{names.get(k, k)}({v})"
                         for k, v in d["used"].items()) or "없음"
        via = f"'{d['via']}' 버튼 클릭" if d["via"] else "제출 버튼을 못 찾아 폼 제출 이벤트(requestSubmit)로 제출"
        return (f" | 눌린 버튼: {via} / 자동 입력한 값: {used}"
                f" / 판정 근거: {reaction_detail(d['url'], d['dom'], d['vis'], d['events'], with_values=False)}"
                f" / 제출 후 {d['waited']}ms 이상 대기"
                f" / 추정: 응답이 더 늦게 오거나, 잠깐 떴다 사라지는 안내이거나, 화면에 드러나지 않는 처리(저장만 하는 경우)일 수 있음")

    # ── [v2] 인증 패치: 보조 함수 ──
    def _forms_info(self):
        try:
            return self.page.evaluate(FORMS_INFO_JS)
        except PWError:
            return []

    def _form_names(self):
        return {f["name"] for f in self._forms_info()}

    def _control_labels(self):
        """버튼·링크·라벨에 적힌 글자 모음(이 글자는 성공·실패 '문구'로 보지 않음)"""
        try:
            return set(self.page.evaluate(CONTROL_LABELS_JS))
        except PWError:
            return set()

    def _note_revealed_forms(self, url, el, label):
        """클릭으로 새로 나타난 로그인 폼(비밀번호 칸이 있는 폼)을 적어 둠 → 폼 검사 단계에서 같은 버튼을 눌러 검사"""
        if not REVEALED_FORM_TEST or not el.get("text") or len(self.revealed_forms) >= REVEALED_FORM_MAX:
            return
        base = self.route_forms.get(url, set())
        for f in self._forms_info():
            if not f["pw"] or f["name"] in base or f["name"] in self.revealed_names:
                continue
            self.revealed_names.add(f["name"])
            self.revealed_forms.append({"url": url, "name": f["name"], "tag": el["tag"], "text": el["text"], "label": label})

    def _open_by(self, opener):
        """적어 둔 버튼(글자가 같은 것)을 다시 눌러 로그인 창을 엶"""
        try:
            if not self.page.evaluate(OPENER_JS, [CLICKABLE_SELECTOR, opener["tag"], opener["text"]]):
                return False
            self.page.locator("[data-qa-opener]").first.click(timeout=2000)
            self.page.wait_for_timeout(CLICK_WAIT_MS)
            self.wait_settled()
            return True
        except PWError:
            return False

    def _pass_modal_steps(self):
        """로그인 제출 뒤 열려 있는 창에 '동의하고 계속하기' 같은 버튼만 있으면 눌러 다음 단계로 넘김. 누른 버튼 글자 목록을 돌려줌"""
        done = []
        for _ in range(LOGIN_STEP_MAX):
            try:
                label = self.page.evaluate(MODAL_CONTINUE_JS, LOGIN_CONTINUE_RE)
                if not label:
                    break
                self.page.locator("[data-qa-continue]").first.click(timeout=2000)
                self.page.wait_for_timeout(CLICK_WAIT_MS)
                self.wait_settled()
            except PWError:
                break
            done.append(label)
            if self._auth_info():
                break
        return done

    def _login_fail(self, new_text, dialogs, key, before=None):
        """
        실패 문구 찾기. 알림창에 뜬 실패 문구는 그대로 실패로 봄.
        화면 글자에서 찾은 경우에는, 로그인 폼이 사라졌고 로그인됐다는 근거가 있으면 옮겨 간 화면의 본문 글자이므로 실패로 보지 않음.
        근거: 로그아웃 버튼이 보임 / 로그인 표시가 새로 나타남 / '로그인했습니다' 같은 안내가 새로 나타남
        ([v5] 로그아웃 버튼을 마이페이지에만 둔 화면에서, 옮겨 간 화면 본문의 '실패' 낱말을 로그인 실패로 오인하던 문제)
        """
        fail = self._fail_message(new_text, dialogs)
        if not fail or self._fail_message([], dialogs):
            return fail
        st = self._login_state(key)
        if not st or st["loginFormVisible"]:
            return fail   # 로그인 폼이 그대로 보이면 실패 문구로 봄
        if any(w in st["member"] for w in ("로그아웃", "logout", "log out", "sign out")):
            return ""
        if before and (st["memberSel"] or any(w not in before["member"] for w in st["member"])):
            return ""
        if any(w in t.lower() for t in list(dialogs) + list(new_text) for w in LOGIN_SUCCESS_WORDS):
            return ""
        return fail

    def _login_result(self, where, fstep, key, before, what="로그인"):
        """제출(+중간 단계·인증번호) 뒤 로그인 상태 표시가 새로 나타났으면 '통과'로 기록"""
        after = self._login_state(key)
        if not (before and after):
            return False
        new_member = [w for w in after["member"] if w not in before["member"]]
        if not (new_member or after["memberSel"]) or after["loginFormVisible"]:
            return False
        steps = "".join(f" → '{s}'" for s in self.last_steps)
        auth = " → 인증번호 입력" if self.last_auth == "ok" else ""
        shown = ", ".join(f"'{w}'" for w in new_member[:2]) or "회원 전용 요소"
        self.add("통과", where, f"{what} 정상 동작: 제출{steps}{auth} 후 로그인 상태 표시({shown}) 확인", fstep)
        self.login_ok.add(where)
        return True

    # ── [v4] 제출 처리가 없는 <form>의 판정 ──
    def _judge_no_target(self, idx, name, where, fstep, info, changed, fresh_text, lv):
        """
        action·onsubmit·submit 리스너가 모두 없는 <form>을 제출해 본 뒤 판정.
        버튼을 눌러 (화면이 다시 열리지 않고) 동작했으면 제출 처리가 버튼 클릭에 연결된 폼이므로 '전송 대상 불명'이 아님.
        다만 그런 폼은 입력칸에서 Enter를 누르면 그대로 전송되어 새로고침될 수 있어, 실제로 눌러 보고 그럴 때만 '주의'로 기록.
        """
        d = (getattr(self, "last_submit", None) or {}) if info else {}
        via = d.get("via")
        if not (changed and via and not d.get("reloaded")):   # 버튼을 못 찾았거나, 반응이 없거나, 그대로 전송되어 화면이 다시 열림
            self.add(lv("주의"), where, NO_TARGET_MSG, f"{fstep} → 제출 후 무슨 일이 일어나야 하는지 기획과 비교")
            return
        probe = self._enter_probe(idx, name, fresh_text) if ENTER_SUBMIT_CHECK else "skip"
        self.flush_errors(where, f"{fstep} → 입력칸에서 Enter")
        if probe == "reload":
            self.add(lv("주의"), where,
                     f"'{via}' 버튼은 동작하지만 입력칸에서 Enter를 누르면 폼이 그대로 전송되어 화면이 새로고침됨"
                     "(<form>에 action·onsubmit·submit 리스너 없음)",
                     f"{fstep} → 결과 확인 → 입력칸에서 Enter → 입력한 값·결과가 사라지고 처음 화면으로 돌아가는지 확인")
        else:
            note = {"ok": "Enter를 눌러도 새로고침되지 않음",
                    "handled": "Enter를 누르면 화면이 다시 열리지만 처음 화면과 달라, 주소의 값으로 결과를 표시하는 것으로 보임",
                    "moved": "Enter를 누르면 다른 화면으로 이동함"}.get(probe, "Enter 키 동작은 확인하지 못함")
            self.add("수동", where, f"<form>에 제출 처리(action·onsubmit·submit 리스너)는 없지만 '{via}' 버튼 클릭으로 동작함({note})",
                     f"{fstep} → 입력칸에서 Enter를 눌러도 같은 동작을 하는지 직접 확인")

    def _enter_probe(self, idx, name, fresh_text):
        """
        폼의 입력칸에서 Enter를 눌러, 폼이 그대로 전송되어 처음 화면으로 새로고침되는지 확인.
        'reload'(처음 화면으로 새로고침) | 'handled'(다시 열리지만 결과 표시) | 'moved'(다른 화면) | 'ok'(그대로) | 'skip'(확인 못함)
        """
        try:
            if not self.page.evaluate(ENTER_TARGET_JS, [idx, name]):
                return "skip"
            base = self.page.url.split("#")[0].split("?")[0]
            self.page.evaluate("() => { window.__qaAlive = 2 }")
            self.page.locator("[data-qa-enter]").first.press("Enter", timeout=2000)
            self.page.wait_for_timeout(CLICK_WAIT_MS + 200)
            self.wait_settled()
            try:
                alive = self.page.evaluate("() => window.__qaAlive === 2")
            except PWError:
                alive = False
            if alive:
                return "ok"
            if self.page.url.split("#")[0].split("?")[0] != base:
                return "moved"   # 다른 화면으로 옮겨 감(의도된 이동일 수 있음)
            now = set(self.page.evaluate(TEXT_LINES_JS))
            # 같은 주소로 다시 열렸고 글자가 처음 화면과 같으면 입력한 값·결과가 사라진 것. 다르면 주소의 값으로 결과를 그리는 화면
            return "reload" if fresh_text is not None and now == fresh_text else "handled"
        except PWError:
            return "skip"

    # ── 체험 계정 ──
    def _prepare_demo(self, idx, where, flow):
        """
        로그인 폼에서 체험 계정을 찾아 입력된 상태로 만듦. 우선순위:
        ① 처음부터 채워져 있음  ② '체험 계정' 자동 입력 버튼  ③ 화면에 적힌 계정 안내. 없으면 None.
        """
        if not DEMO_FIRST:
            return None

        def pw_filled():
            return any(x["type"] == "password" and x["value"] for x in (self.page.evaluate(FORM_FIELDS_JS, idx) or []))
        try:
            if pw_filled():
                return {"how": "처음부터 채워져 있는 체험 계정", "keep": True}
            label = self.page.evaluate(DEMO_SCAN_JS, [idx, DEMO_BTN_RE])
            if label:
                step = f"{flow} → '{label}' 클릭"
                self.page.locator("[data-qa-demo]").first.click(timeout=2000)
                self.page.wait_for_timeout(CLICK_WAIT_MS)
                self.wait_settled()
                self.flush_errors(where, step)
                if pw_filled():
                    return {"how": f"'{label}' 버튼으로 자동 입력", "keep": True}
                self.add("주의", where, f"체험 계정 버튼 '{label}'을 눌러도 입력칸이 채워지지 않음(눌러서 바로 로그인되는 방식일 수 있음)",
                         f"{step} → 아이디·비밀번호 칸이 채워지는지 확인")
            # [v2] '빠른 로그인'처럼 계정 안내 영역 안의 '입력'·'채우기' 버튼(버튼 글자만으로는 체험 계정인지 알 수 없는 경우)
            zone = self.page.evaluate(DEMO_ZONE_JS, [idx, DEMO_ZONE_RE, DEMO_FILL_RE])
            if zone:
                self.page.locator("[data-qa-demo]").first.click(timeout=2000)
                self.page.wait_for_timeout(CLICK_WAIT_MS)
                self.wait_settled()
                self.flush_errors(where, f"{flow} → '{zone['label']}' 클릭")
                if pw_filled():
                    return {"how": f"'{zone['zone']}' 계정 안내의 '{zone['label']}' 버튼으로 자동 입력", "keep": True}
            cred = parse_demo_credentials(self.page.evaluate(DEMO_TEXT_JS, idx))
            if cred:
                key = "email" if "email" in cred else "id"
                acct = dict(TEST_ACCOUNT)
                acct.update(cred)
                return {"how": f"화면에 적힌 체험 계정({cred[key]})", "acct": acct, "mode": key, "keep": False}
        except PWError:
            pass
        return None

    def _demo_result(self, where, fstep, demo, fail, login_name):
        """체험 계정으로 로그인한 결과를 기록. 성공이면 '통과', 실패 문구가 나오면 '오류'(체험 계정은 되어야 하므로)"""
        how = demo["how"]
        if fail:
            self.add("오류", where, f"체험 계정({how})으로 로그인했으나 실패 문구 표시: '{fail}'",
                     f"{fstep} → 체험 계정 값과 로그인 확인 코드(저장된 계정 비교)를 확인")
        elif self.last_auth not in (None, "ok"):
            pass   # 인증창에서 막힌 경우는 인증창 결과가 따로 기록됨
        else:
            after = self._login_state(login_name)
            url_ch = bool((getattr(self, "last_submit", None) or {}).get("url"))
            logged = url_ch or bool(after and (after["member"] or after["memberSel"] or not after["loginFormVisible"]))
            if logged:
                self.add("통과", where, f"체험 계정({how})으로 로그인 정상 동작", fstep)
                self.demo_ok.add(where)
            else:
                self.add("주의", where, f"체험 계정({how}) 로그인 뒤 로그인 상태(로그아웃 버튼·로그인 창 닫힘 등)를 확인하지 못함",
                         f"{fstep} → 로그인 완료 화면이 나오는지 직접 확인")
        try:
            self._logout_if_available()   # 다음 검사가 로그인 상태에 영향받지 않도록
        except PWError:
            pass

    # ── 인증창 ──
    def _auth_info(self):
        try:
            return self.page.evaluate(AUTH_CODE_JS, [AUTH_HINT_RE, AUTH_OK_RE])
        except PWError:
            return None

    def _run_auth(self, idx, where, flow, allow_send, seed_texts=()):
        """
        인증창('인증번호 받기 → 번호 입력 → 확인')이 실제로 동작하는지 확인. 인증창이 뜨는 것 자체는 오류로 보지 않음.
        결과: 'ok'(인증 성공) / 'fail'(실패 문구) / 'unknown'(판단 못 함) / None(인증 화면 없음)
        제출 때 쌓인 알림 목록(self.events)은 건드리지 않고 되돌려 줌.
        """
        saved, self.events = self.events, []
        try:
            return self._run_auth_inner(idx, where, flow, allow_send, list(seed_texts))
        except PWError as e:
            self.add("주의", where, f"인증창 검사 중 중단: {str(e).split(chr(10))[0][:60]}", f"{flow} → 인증창을 직접 열어 확인")
            return "unknown"
        finally:
            self.events = saved

    def _run_auth_inner(self, idx, where, flow, allow_send, heard):
        step = f"{flow} → 인증창"
        send = self.page.evaluate(AUTH_SEND_JS, [idx, AUTH_SEND_RE]) if allow_send else None
        info = self._auth_info()
        if send:   # 인증 요청 버튼을 눌러 번호를 받고 인증창을 띄움
            before = set(self.page.evaluate(TEXT_LINES_JS))
            self.page.locator("[data-qa-auth-send]").first.click(timeout=2000)
            self.page.wait_for_timeout(CLICK_WAIT_MS + 200)
            self.wait_settled()
            rest = self.flush_errors(where, step)
            sent = [v for k, v in rest if k == "dialog"] + [t for t in self.page.evaluate(TEXT_LINES_JS) if t not in before]
            heard += sent
            info = self._auth_info()
            if not info:
                if sent:
                    self.add("주의", where, f"인증창: '{send}' 클릭 후 인증번호 입력칸을 찾지 못함(안내 문구: '{sent[0][:40]}')",
                             f"{step} → '{send}' 클릭 → 인증번호 입력칸이 나타나는지 확인")
                else:
                    self.add("경고", where, f"인증창: '{send}' 버튼을 눌러도 반응 없음(알림도 인증번호 입력칸도 나타나지 않음)",
                             f"{step} → '{send}' 클릭 → 알림·입력칸이 나타나는지 확인")
                return "unknown"
        if not info:
            return None
        code, known = extract_auth_code(heard)
        if not code:   # [v2] 인증창 안에 적힌 번호('인증번호 123456' 형태만 인정)
            code, known = extract_auth_code(info.get("ctx") or [], strict=True)
        if not code:
            n = info.get("maxlength") or 0
            code = AUTH_DEFAULT_CODE[:n] if 0 < n < len(AUTH_DEFAULT_CODE) else AUTH_DEFAULT_CODE
        before = set(self.page.evaluate(TEXT_LINES_JS))
        inp = self.page.locator("[data-qa-auth-code]").first
        inp.fill(code, timeout=2000)
        ok_label = info.get("ok")
        if ok_label:
            self.page.locator("[data-qa-auth-ok]").first.click(timeout=2000)
        else:
            inp.press("Enter")
        self.page.wait_for_timeout(CLICK_WAIT_MS + 200)
        self.wait_settled()
        rest = self.flush_errors(where, step)
        dlg = [v for k, v in rest if k == "dialog"]
        labels = self._control_labels()   # [v2] 버튼·라벨 글자('인증 완료' 버튼 등)는 성공·실패 문구로 보지 않음
        new = [t for t in self.page.evaluate(TEXT_LINES_JS) if t not in before and t not in labels]
        try:
            okst = self.page.evaluate(AUTH_OK_STATE_JS)   # 눌렀던 확인 버튼의 지금 글자
        except PWError:
            okst = None
        still = self._auth_info()   # 인증번호 입력칸이 아직 입력 가능한 상태로 보이는가
        via = f"'{send}' 클릭 → " if send else ""
        flow2 = f"{step} → {via}인증번호 입력({code}{'' if known else ', 화면에서 번호를 못 찾아 임의 값'}) → '{ok_label or 'Enter'}'"
        fail = self._fail_message(new, dlg)
        if fail:
            if known:
                self.add("오류", where, f"인증창: 화면·알림에 안내된 인증번호({code})를 넣었는데도 실패 문구 표시: '{fail}'",
                         flow2 + " → 안내된 번호와 확인 코드가 같은지 비교")
            else:
                self.add("주의", where, f"인증창: 자동 입력한 번호({code})로 실패 문구 표시: '{fail}' (실제 인증번호를 몰라 자동 판정 불가)",
                         flow2 + " → 실제 인증번호로 직접 확인")
            return "fail"
        ok_msg = next((t for t in dlg + new if any(w in t.lower() for w in AUTH_SUCCESS_WORDS)), "")
        if (not ok_msg and okst and ok_label and okst["text"][:20] != ok_label
                and any(w in okst["text"].lower() for w in AUTH_SUCCESS_WORDS)):
            ok_msg = okst["text"]   # [v2] 같은 확인 버튼의 글자가 '인증완료'처럼 바뀜
        # [v2] 인증 성공을 직접 말하는 문구('인증되었습니다' 등)를 우선. 인증창이 닫힌 경우 옮겨 간 화면의 '완료'류 글자(진행 단계 표시 등)는 성공 문구로 적지 않음
        strong = next((t for t in dlg + new if any(w in t.lower() for w in AUTH_SUCCESS_WORDS if w not in ("성공", "완료", "success"))), "")
        if strong:
            ok_msg = strong
        elif not still:
            ok_msg = ""
        if ok_msg:
            self.add("통과", where, f"인증창 정상 동작: {via}인증번호 입력 → 확인 후 '{ok_msg[:40]}' 표시", flow2)
            return "ok"
        if not still:
            self.add("통과", where, f"인증창 정상 동작: {via}인증번호 입력 → 확인 후 인증창이 닫힘(성공 문구는 따로 없음)", flow2)
            return "ok"
        self.add("주의", where, "인증창: 인증번호를 입력하고 확인했으나 결과(성공·실패 표시)를 찾지 못함", flow2 + " → 결과가 표시되는지 직접 확인")
        return "unknown"

    # ── 회원가입 버튼으로 가입 화면 열기 ──
    def _signup_target(self, l):
        """지금 화면에서 가입 입력칸을 찾음. (폼 번호 또는 -1, 이름, 종류) / 없으면 None"""
        for idx in self.page.evaluate(VISIBLE_FORMS_JS, False):
            peek = self.page.evaluate(FORM_PEEK_JS, idx)
            if peek and peek["pw"] and peek["signup"]:
                return idx, peek["name"], "회원가입 폼"
            if peek and AUTH_FORM_TEST and peek.get("auth") and peek["signup"] and l.get("auth"):   # [v2] 비밀번호 없는 가입 인증 폼
                return idx, peek["name"] + "\u0001" + peek["btn"], "가입 인증 폼"
        root = self.page.evaluate(SIGNUP_ROOT_JS, [l["name"]])
        if root:
            return -1, root["name"], "가입 입력칸(<form> 태그 없음)"
        return None

    def _find_signup_by_button(self, l):
        """
        가입 폼이 처음부터 보이지 않을 때: 로그인 화면의 '회원가입' 버튼·링크를 눌러 가입 입력칸을 연다.
        (가입 정보 dict, None) 또는 (None, 못 찾은 이유)
        """
        self.goto(l["url"])
        if self.page.evaluate(LOGIN_FORM_INDEX_JS, l["name"]) < 0:   # 앞 검사로 로그인된 상태일 수 있음
            self._logout_if_available()
            self.goto(l["url"])
        trig = self.page.evaluate(FIND_TRIGGER_JS, ["data-qa-signup-btn", SIGNUP_TRIGGER_RE, l["name"]])
        if not trig:
            return None, "회원가입 버튼·링크를 찾지 못함(로그인 화면에 '회원가입'·'가입하기'·'Sign up' 같은 글자의 버튼이 없음)"
        self.events = []
        self.page.locator("[data-qa-signup-btn]").first.click(timeout=2000)
        self.page.wait_for_timeout(CLICK_WAIT_MS)
        self.wait_settled()
        self.flush_errors(f"{self.route_name(l['url'])} > '{trig}'", f"{self.open_step(l['url'])} → '{trig}' 클릭")
        found = self._signup_target(l)
        if not found:
            return None, f"'{trig}' 버튼을 눌렀으나 가입 입력칸(비밀번호 칸이 있는 묶음)을 찾지 못함"
        idx, name, kind = found
        disp = name.replace("\u0001", "·")
        return {"url": self.page.url, "idx": idx, "name": name, "disp": disp, "kind": kind, "trigger": trig, "signup": True,
                "auth": "\u0001" in name,
                "where": f"{self.route_name(l['url'])} > '{trig}' 클릭 후 {kind}({disp})"}, None

    def _open_login_ui(self, l):
        """가입 뒤 로그인 폼이 안 보이면 '로그인' 탭·버튼을 눌러 새로고침 없이 로그인 창을 다시 엶"""
        trig = self.page.evaluate(FIND_TRIGGER_JS, ["data-qa-login-btn", LOGIN_TRIGGER_RE, None])
        if not trig:   # [v2] '로그인·비회원 인증'처럼 다른 글자가 붙은 로그인 버튼
            trig = self.page.evaluate(FIND_TRIGGER_JS, ["data-qa-login-btn", LOGIN_TRIGGER_LOOSE_RE, None])
        if not trig:
            return
        try:
            self.page.locator("[data-qa-login-btn]").first.click(timeout=2000)
            self.page.wait_for_timeout(CLICK_WAIT_MS)
            self.wait_settled()
        except PWError:
            pass

    @staticmethod
    def _duplicate_message(new_text, dialogs):
        """'이미 가입된 아이디입니다' 같은 중복 가입 문구"""
        for t in list(dialogs) + list(new_text):
            low = t.lower()
            if any(w in low for w in DUPLICATE_WORDS):
                return t[:60]
        return ""

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
                plan += [(self.page.url, i) for i in self.page.evaluate(VISIBLE_FORMS_JS, False)]
                self.guest_form_names |= self._form_names()   # [v2] 비로그인 상태에서 보이는 폼 이름
            except PWError:
                pass
        extra = self.revealed_forms[:REVEALED_FORM_MAX] if REVEALED_FORM_TEST else []
        self.bar.reset(total=max(len(plan) + len(extra), 1))
        done_names = set()
        for url, idx in plan:
            self.bar.set_postfix_str(f"폼 #{idx}")
            try:
                self._test_form(url, idx, done_names)
            except PWError as e:
                self.add("오류", f"{self.route_name(url)} 폼#{idx}", f"제출 실패: {str(e).split(chr(10))[0][:80]}",
                         f"{self.open_step(url)} → {idx + 1}번째 폼에 값 입력 → 제출")
            self.bar.update(1)
        for rv in extra:   # [v2] 버튼을 눌러야 나타나는 로그인 창(모달·소셜 로그인 등)
            self.bar.set_postfix_str(f"폼(클릭 후): {rv['name'][:12]}")
            try:
                self._test_form(rv["url"], None, done_names, opener=rv)
            except PWError as e:
                self.add("수동", f"{self.route_name(rv['url'])} > '{rv['label']}' 클릭 후 폼({rv['name']})",
                         f"클릭 후 나타난 로그인 창 검사 중단: {str(e).split(chr(10))[0][:60]}",
                         f"{self.open_step(rv['url'])} → '{rv['label']}' 클릭 → 나타난 창에서 로그인 직접 확인")
            self.bar.update(1)
        self.test_login_chain()

    def _test_form(self, url, idx, done_names, opener=None):
        """폼 하나: 열기 → 값 입력 → 제출 → 판정. opener가 있으면 그 버튼을 눌러 폼(로그인 창)을 먼저 띄움"""
        self.goto(url)
        self.events = []
        loc, open_step = self.route_name(url), self.open_step(url)
        if opener:
            if not self._open_by(opener):
                return
            hit = next((f for f in self._forms_info() if f["name"] == opener["name"]), None)
            if not hit:
                return
            idx = hit["idx"]
            self.events = []
            loc += f" > '{opener['label']}' 클릭 후"
            open_step += f" → '{opener['label']}' 클릭"
        if idx not in self.page.evaluate(VISIBLE_FORMS_JS, False):
            return
        struct = self.page.evaluate(FORM_STRUCT_JS, idx)
        peek = self.page.evaluate(FORM_PEEK_JS, idx)
        if not peek:
            return
        is_auth = AUTH_FORM_TEST and bool(peek.get("auth"))   # [v2] 비밀번호 없이 이름·휴대폰 → 인증번호로 확인하는 폼
        key = peek["name"] + ("\u0001" + peek["btn"] if is_auth else "")   # 같은 폼이라도 탭(로그인·가입·비회원)별로 따로 검사
        if key in done_names:
            return
        done_names.add(key)
        authlike = bool(peek["pw"]) or is_auth
        disp = peek["name"] + (f"·{peek['btn']}" if is_auth and peek["btn"] else "")
        if peek["pw"]:
            kind = "회원가입 폼" if peek["signup"] else "로그인 폼"
        elif is_auth:
            kind = "가입 인증 폼" if peek["signup"] else "인증 폼"
        else:
            kind = "폼"
        where = f"{loc} > {kind}({disp})"
        fstep = (f"{open_step} → {kind}({disp})에 값 입력"
                 f"(예: {account_text(('name', 'phone')) if is_auth else account_text()}) → 제출")
        soft = bool(opener) and not REVEALED_FORM_STRICT   # 클릭해야 나타나는 창: '통과'만 남기고 문제는 '수동'으로
        lv = (lambda level: "수동" if level in PROBLEM_LEVELS else level) if soft else (lambda level: level)
        self.has_form = True
        if authlike:
            self.has_pw_form = True
            self.pw_forms.append({"url": url, "idx": idx, "name": key, "disp": disp, "signup": peek["signup"],
                                  "where": where, "kind": kind, "auth": is_auth, "opener": opener,
                                  "guest": is_auth and bool(re.search(GUEST_TAB_RE, peek["btn"], re.I))})
            self.add("수동", where, "로그인/회원가입 실제 사용 흐름(정상·실패·로그아웃)은 직접 확인",
                     f"{open_step} → 회원가입 완료 → 같은 계정으로 로그인 → 로그인 상태 표시·로그아웃 확인"
                     f" → 틀린 비밀번호·빈 값으로 로그인 시 오류 문구 확인")
        else:
            self.add("수동", where, "폼 입력값 검증(빈 값·잘못된 형식)은 자동 미검사",
                     f"{open_step} → {kind}({disp})를 빈 값으로 제출 → 안내 문구 확인 → 정상 값으로 제출 → 결과 확인")
        # [v4] '전송 대상 불명'은 제출해 본 뒤에 판정(버튼 클릭으로 실제 동작하는 폼은 제외) → _judge_no_target
        no_target = bool(struct and struct["noTarget"])
        fresh_text = None
        if no_target:
            try:
                fresh_text = set(self.page.evaluate(TEXT_LINES_JS))   # 값 입력 전 화면 글자(Enter 새로고침 판정용)
            except PWError:
                pass
        is_login = authlike and not peek["signup"]
        before_state = self._login_state(key) if authlike else None
        try:
            info, changed, new_text, _ = self._submit_form(idx, precheck=peek["signup"], demo=is_login and bool(peek["pw"]),
                                                           where=where, flow=fstep, post_auth=authlike,
                                                           fill_opt={"smart": True} if is_auth else None, steps=is_login)
        except PWError:
            if no_target:
                self.add(lv("주의"), where, NO_TARGET_MSG, f"{fstep} → 제출 후 무슨 일이 일어나야 하는지 기획과 비교")
            raise
        demo = self.last_demo if is_login else None
        if self.page.url.startswith("chrome-error"):
            self.add("오류", where, "제출 후 페이지 이동 실패", f"{fstep} → 이동한 화면이 열리는지 확인")
        rest = self.flush_errors(where, fstep)
        self.check_downloads(rest, where, fstep)
        dialogs = [v for k, v in rest if k == "dialog"]
        changed = changed or bool(rest)
        if not changed:
            invalid = self.page.evaluate("(i) => !document.querySelectorAll('form')[i]?.checkValidity()", idx)
            if invalid:
                self.add(lv("경고"), where, "테스트 값을 넣어도 입력 검증을 통과하지 못함(필수값/형식 확인 필요)",
                         f"{fstep} → 어떤 칸에서 막히는지(빨간 안내) 확인 → required·pattern·minlength 조건 확인")
            elif peek["pw"]:
                self.add(lv("오류"), where,
                         ("체험 계정 입력 후 " if demo else "") + "제출해도 반응 없음(로그인/가입 처리 안 됨) · 값을 자동 입력해 제출했으나 "
                         "주소·화면 구조·겉모습·알림 모두 변화 없음(입력 규칙 검증은 통과)",
                         f"{fstep} → 완료 문구·화면 전환이 있는지 확인" + self._submit_detail())
            else:
                self.add(lv("경고"), where,
                         "제출해도 반응 없음 · 값을 자동 입력해 제출했으나 주소·화면 구조·겉모습·알림 모두 변화 없음",
                         f"{fstep} → 결과 화면·메시지가 있는지 확인" + self._submit_detail())
        elif authlike:
            fail = self._login_fail(new_text, dialogs, key, before_state)
            if demo:
                self._demo_result(where, fstep, demo, fail, key)   # 체험 계정은 되어야 하므로 실패면 바로 기록
            elif fail and not peek["signup"]:
                # 가입 전 로그인 실패는 정상일 수 있음 → '가입 → 로그인' 결과를 보고 test_login_chain에서 결정
                self.login_fail_pending[where] = (fail, fstep)
                if soft:
                    self.soft_where.add(where)
            elif fail and not self._duplicate_message(new_text, dialogs):
                self.add(lv("경고"), where, f"테스트 값으로 제출 시 실패 문구 표시: '{fail}'",
                         f"{fstep} → '{fail}' 문구가 왜 나오는지 확인(입력 규칙·저장 코드 확인)")
            elif not fail and (is_auth or opener or self.last_auth == "ok" or self.last_steps):
                # [v2] 인증 폼·클릭 후 나타난 로그인 창·인증창을 거친 제출: 로그인 상태 표시까지 나타났는지 확인
                self._login_result(where, fstep, key, before_state,
                                   "가입" if peek["signup"] else ("인증" if is_auth else "로그인"))
        if no_target:
            self._judge_no_target(idx, peek["name"], where, fstep, info, changed, fresh_text, lv)
        if authlike:   # [v2] 다음 폼 검사가 로그인 상태에 영향받지 않도록 원래(비로그인) 상태로
            try:
                self._logout_if_available()
            except PWError:
                pass

    def _login_state(self, login_name):
        conf = LOGIN_STATE_SELECTORS.get(self.file.name, {})
        try:
            return self.page.evaluate(LOGIN_STATE_JS, [list(GUEST_WORDS), list(MEMBER_WORDS),
                                                       conf.get("guest", []), conf.get("member", []), login_name,
                                                       [TEST_ACCOUNT["id"], TEST_ACCOUNT["email"], TEST_ACCOUNT["name"], "테스트"]])
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
            for idx in self.page.evaluate(VISIBLE_FORMS_JS, True)[:GUEST_FORM_MAX]:
                try:
                    # [v2] 로그인(인증) 폼 자체는 기록용 폼으로 쓰지 않음
                    if idx == self.page.evaluate(LOGIN_FORM_INDEX_JS, l["name"]) or idx not in self.page.evaluate(VISIBLE_FORMS_JS, True):
                        continue
                    self._fill_form(idx)
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
        after = self._login_state(l["name"])
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
            label = self._find_logout()   # [v5] 마이페이지에만 있는 로그아웃 버튼도 찾음
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
            out = self._login_state(l["name"])
            if out is None:
                return
            left = [w for w in out["member"] if w not in before["member"]]
            if left:
                self.add("경고", where, "로그아웃 후에도 로그인 상태 표시가 남아 있음: " + ", ".join(f"'{w}'" for w in left),
                         ostep + " → 로그인 상태 표시가 모두 사라지는지 확인")
            missing = [g for g in before["guest"] if g not in out["guest"]]
            if missing:   # [v2] 로그아웃 뒤 홈 등 다른 화면으로 옮겨졌을 수 있음 → 로그인 화면으로 돌아가 같은 화면끼리 다시 비교
                try:
                    self._back_to(l["url"])
                    again = self._login_state(l["name"])
                    if again:
                        missing = [g for g in missing if g not in again["guest"]]
                except PWError:
                    pass
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
        [TEST_ACCOUNT로 가입 → 같은 계정으로 로그인]을 이어서 해 보고 실패 여부를 판정.
        끝나면 로그인 폼 단독 제출 때 보류해 둔 실패 문구를 정리(검증된 폼은 버리고, 못 한 폼은 이유와 함께 기록).
        """
        reason = "가입 → 로그인 연속 검사 꺼짐(LOGIN_CHAIN_TEST=False)"
        verified = set()
        try:
            if LOGIN_CHAIN_TEST:
                reason = self._login_chain(verified)
        finally:
            self._flush_login_pending(verified, reason)
        self._after_chain()   # [v2] 비회원 인증 탭 · 회원 전용 화면의 인증창

    def _flush_login_pending(self, verified, reason):
        for where, (fail, fstep) in self.login_fail_pending.items():
            if where in verified or where in self.demo_ok or where in self.login_ok:
                continue   # 가입 후 로그인 또는 체험 계정 로그인으로 이미 판정함(통과면 문제 아님, 실패면 따로 기록됨)
            why = reason or "가입 → 로그인 연속 검사는 다른 로그인 폼으로 진행함"
            self.add("수동" if where in self.soft_where else "주의", where,
                     f"테스트 값으로 제출 시 실패 문구 표시: '{fail}' (가입 후 로그인 자동 확인 못함: {why})",
                     f"{fstep} → 회원가입을 먼저 한 뒤 같은 계정({account_text()})으로 로그인해 확인")
        self.login_fail_pending = {}

    INVALID_FIELDS_JS = r"""
    (i) => { const f = i >= 0 ? document.querySelectorAll('form')[i] : document.querySelector('[data-qa-root]');
      return [...(f ? (f.elements || f.querySelectorAll('input, select, textarea')) : [])]
      .filter(e => e.willValidate && !e.checkValidity())
      .map(e => `${e.getAttribute('name') || e.getAttribute('id') || e.type}: ${e.validationMessage}`.slice(0, 50))
      .slice(0, 3); }
    """

    def _login_chain(self, verified):
        """연속 검사 본체. 로그인 단계까지 갔으면 None, 못 갔으면 그 이유를 돌려줌"""
        # [v2] 버튼을 눌러야 나타나는 로그인 창·'비회원' 인증 탭은 연속 검사에 쓰지 않음(각각 따로 검사)
        signups = [f for f in self.pw_forms if f["signup"] and not f.get("opener")]
        logins = [f for f in self.pw_forms if not f["signup"] and not f.get("opener") and not f.get("guest")]
        if not logins:
            return "로그인 폼 없음"
        l = logins[0]
        self._chain_login = l
        base = l["name"].split("\u0001")[0]
        # 비밀번호 없는 인증 폼이면 같은 폼의 '가입' 탭과 짝을 맞춤
        signups = [f for f in signups if bool(f.get("auth")) == bool(l.get("auth"))
                   and (not l.get("auth") or f["name"].split("\u0001")[0] == base)]
        s = signups[0] if signups else None
        acct = account_text(("name", "phone") if l.get("auth") else ("id", "email", "password", "name"))
        smart = {"smart": True} if l.get("auth") else None
        try:
            if s:
                self.goto(s["url"])
                if not self.page.locator("form").nth(s["idx"]).is_visible():
                    self._logout_if_available()
                    self._back_to(s["url"])
                    if not self.page.locator("form").nth(s["idx"]).is_visible():
                        return "제출할 회원가입 폼이 보이지 않음"
                open_flow = f"{self.open_step(s['url'])} → {s['kind']}({s.get('disp', s['name'])})"
            else:   # 가입 폼이 처음부터 안 보임 → 로그인 화면의 '회원가입' 버튼을 눌러 연다
                s, why = self._find_signup_by_button(l)
                if not s:
                    return why
                open_flow = f"{self.open_step(l['url'])} → '{s['trigger']}' 클릭 → {s['kind']}({s.get('disp', s['name'])})"
            flow = (f"{open_flow}에 {acct}로 가입"
                    f" → {('같은 화면' if s['url'] == l['url'] else '주소 끝에 ' + repr(self.route_name(l['url'])) + ' 붙여 이동')}"
                    f" → {l['kind']}({l.get('disp', l['name'])})에 같은 계정으로 로그인")
            where = f"{s['where']} → {l['where']}"
            self.events = []
            info, changed, new_text, _ = self._submit_form(s["idx"], precheck=True, where=where, flow=flow,
                                                           post_auth=True, fill_opt=smart)
            if self.last_auth not in (None, "ok"):   # [v2] 가입 중 뜬 인증창을 넘지 못함(인증창 결과는 따로 기록됨)
                self.flush_errors(where, flow)
                return "가입 중 인증창을 통과하지 못함"
            rest = self.flush_errors(where, flow)
            dialogs = [v for k, v in rest if k == "dialog"]
            dup = self._duplicate_message(new_text, dialogs)   # 앞 단계에서 이미 가입됨 → 로그인으로 진행
            fail = "" if dup else self._fail_message(new_text, dialogs)
            silent = ""   # 가입에 반응이 없었을 때의 설명. 이미 가입돼 조용히 무시했을 수도 있어 로그인은 해 봄
            if not (changed or rest):
                bad = self.page.evaluate(self.INVALID_FIELDS_JS, s["idx"])
                via = f"'{info['via']}' 버튼 클릭" if info and info.get("via") else "제출 버튼을 못 찾아 폼 제출 이벤트로 제출"
                pre = f", 먼저 누른 버튼: {', '.join(info['precheck'])}" if info and info.get("precheck") else ""
                silent = (f"자동 회원가입 제출에 반응 없음({via}{pre})"
                          + (f"(입력 규칙에 막힌 칸: {', '.join(bad)})" if bad else ""))
            if fail:
                return f"자동 회원가입 실패 문구 '{fail}'"
            if self.page.evaluate(LOGIN_FORM_INDEX_JS, l["name"]) < 0:
                self._logout_if_available()
            if self.page.evaluate(LOGIN_FORM_INDEX_JS, l["name"]) < 0:
                self._open_login_ui(l)   # 같은 화면의 '로그인' 탭·버튼(새로고침 없이)
            reloaded = False
            if self.page.evaluate(LOGIN_FORM_INDEX_JS, l["name"]) < 0:
                now, target = urlparse(self.page.url), urlparse(l["url"])
                reloaded = (now.path, now.query) != (target.path, target.query)
                self._back_to(l["url"])
            self.events = []
            if self.page.evaluate(LOGIN_FORM_INDEX_JS, l["name"]) < 0:
                return "회원가입 후 로그인 폼이 보이지 않음"
            guest_rec = self._make_guest_records(l) if GUEST_RECORD_TEST else None   # 비회원 기록 남기기
            guest_state = self._login_state(l["name"])   # 로그인 직전(비로그인) 화면 상태

            # 로그인: 칸이 아이디인지 이메일인지 모호하면 LOGIN_KEY_ORDER 순서로 한 번씩 시도
            tried, fail, changed, rest = [], "", False, []
            for n, mode in enumerate(LOGIN_KEY_ORDER):
                login_idx = self.page.evaluate(LOGIN_FORM_INDEX_JS, l["name"])
                if login_idx < 0:
                    return "제출할 로그인 폼이 보이지 않음"
                prev_fail = fail
                info, changed, new_text, _ = self._submit_form(login_idx, mode, where=where, flow=flow, post_auth=True,
                                                               fill_opt=smart, steps=True)
                rest = self.flush_errors(where, flow)
                fail = self._login_fail(new_text, [v for k, v in rest if k == "dialog"], l["name"], guest_state)
                if not fail and prev_fail:
                    # 같은 실패 문구가 그대로 떠 있으면 '새 문구'로 안 잡히므로 화면에 남아 있는지 직접 확인
                    lines = self.page.evaluate(TEXT_LINES_JS)
                    if any(prev_fail in x for x in lines):
                        fail = prev_fail
                tried.append(TEST_ACCOUNT[mode] if info and info.get("ambiguous") else "")
                if not fail and (changed or rest):
                    break
                if not (info and info.get("ambiguous")):
                    break   # 칸 구분이 명확하면 다른 값으로 다시 해 볼 필요 없음
            if self.last_auth not in (None, "ok"):   # [v2] 로그인 중 뜬 인증창을 넘지 못함(인증창 결과는 따로 기록됨)
                return "로그인 중 인증창을 통과하지 못함"
            if silent:
                if fail or not (changed or rest):
                    return silent   # 가입도 로그인도 안 됨 → 자동으로는 판단 불가, 보류한 '주의'에 이유로 붙임
                silent = ""         # 가입은 조용했지만 로그인은 됨(앞 단계에서 이미 가입된 계정) → 통과
            verified.add(l["where"])
            tried_note = f" (로그인 칸에 넣어 본 값: {', '.join(t for t in tried if t)})" if any(tried) else ""
            # 화면 이동에 새로고침이 끼면 메모리에만 저장한 계정은 사라짐 → 실제 사용 흐름과 다를 수 있어 '경고'
            level = "경고" if reloaded else "오류"
            note = " (검사 중 새로고침이 있었음 — 실제 화면 흐름으로 다시 확인)" if reloaded else ""
            if fail:
                self.add(level, where, f"회원가입한 계정으로 로그인 실패: '{fail}'{note}{tried_note}",
                         flow + f" → '{fail}' 대신 로그인 완료가 되는지 확인(가입 정보 저장·비교 코드 확인)")
            elif not (changed or rest):
                self.add(level, where,
                         f"회원가입 후 같은 계정으로 로그인해도 반응 없음 · 로그인 제출 후 주소·화면 구조·겉모습·알림 모두 변화 없음{note}",
                         flow + " → 로그인 완료 화면·문구가 나오는지 확인" + self._submit_detail())
            else:
                self.page.wait_for_timeout(400)   # 로그인 창이 닫히는 애니메이션이 끝나길 기다림
                after = self._login_state(l["name"])
                has_member_marker = (
                    after and guest_state
                    and (set(after["member"]) - set(guest_state["member"]) or after["memberSel"])
                )
                login_still_visible = after and after["loginFormVisible"]
                self.chain_passed = not login_still_visible or bool(has_member_marker)
                if self.chain_passed:
                    self.add("통과", where, "회원가입 → 같은 계정 로그인 정상 동작", flow)
                if not self.chain_passed:
                    self.add(level, where, f"가입한 계정의 로그인 상태를 확인할 수 없음{note}",
                             flow + " → 로그인 폼이 닫히거나 회원 메뉴가 나타나는지 확인")
                if LOGIN_STATE_TEST and guest_state is not None:
                    self.check_login_state(l, guest_state, where, flow, guest_rec)
            return None
        except PWError as e:
            return f"검사 중단({str(e).split(chr(10))[0][:60]})"

    # ── [v2] 연속 검사 뒤: 비회원 인증 탭 · 회원 전용 화면의 인증창 ──
    def _after_chain(self):
        logins = [f for f in self.pw_forms if not f["signup"] and not f.get("opener") and not f.get("guest")]
        l = self._chain_login or (logins[0] if logins else None)
        if not l:
            return
        if AUTH_FORM_TEST and l.get("auth"):
            try:
                self._guest_variant(l)
            except PWError as e:
                self.add("수동", l["where"], f"비회원 인증 탭 검사 중단: {str(e).split(chr(10))[0][:60]}",
                         f"{self.open_step(l['url'])} → '비회원' 탭에서 인증 직접 확인")
        if MEMBER_TEST and (self.chain_passed or l["where"] in self.demo_ok or l["where"] in self.login_ok):
            self.test_member_area(l)

    def _guest_variant(self, l):
        """비밀번호 없는 인증 화면에 '비회원' 탭이 있으면 그 인증(이름·휴대폰 → 인증번호)도 확인"""
        if any(f.get("guest") for f in self.pw_forms):
            return   # 화면 탐색에서 이미 찾아 폼 검사 때 확인함
        self.goto(l["url"])
        if self.page.evaluate(LOGIN_FORM_INDEX_JS, l["name"]) < 0:
            self._logout_if_available()
            self.goto(l["url"])
        trig = self.page.evaluate(FIND_TRIGGER_JS, ["data-qa-guest-btn", GUEST_TAB_RE, l["name"]])
        if not trig:
            return
        self.events = []
        self.page.locator("[data-qa-guest-btn]").first.click(timeout=2000)
        self.page.wait_for_timeout(CLICK_WAIT_MS)
        self.wait_settled()
        for idx in self.page.evaluate(VISIBLE_FORMS_JS, False):
            peek = self.page.evaluate(FORM_PEEK_JS, idx)
            if not (peek and peek.get("auth") and not peek["signup"] and re.search(GUEST_TAB_RE, peek["btn"], re.I)):
                continue
            key = peek["name"] + "\u0001" + peek["btn"]
            disp = f"{peek['name']}·{peek['btn']}"
            where = f"{self.route_name(l['url'])} > '{trig}' 클릭 후 인증 폼({disp})"
            flow = (f"{self.open_step(l['url'])} → '{trig}' 클릭 → 인증 폼({disp})에 값 입력"
                    f"(예: {account_text(('name', 'phone'))}) → 제출")
            before = self._login_state(key)
            info, changed, new_text, _ = self._submit_form(idx, where=where, flow=flow, post_auth=True, fill_opt={"smart": True})
            rest = self.flush_errors(where, flow)
            fail = self._login_fail(new_text, [v for k, v in rest if k == "dialog"], key, before)
            if fail:
                self.add("수동", where, f"비회원 인증: 테스트 값으로 제출 시 실패 문구 표시: '{fail}'", flow + " → 직접 확인")
            elif changed or rest:
                self._login_result(where, flow, key, before, "인증")
            self._logout_if_available()
            return

    def _member_login(self, l):
        """회원 전용 화면 검사를 위해 로그인 상태를 만듦(체험 계정이 확인됐으면 체험 계정, 아니면 가입해 둔 테스트 계정)"""
        self.goto(l["url"])
        if self.page.evaluate(LOGIN_FORM_INDEX_JS, l["name"]) < 0:
            self._logout_if_available()
            self._open_login_ui(l)
        if self.page.evaluate(LOGIN_FORM_INDEX_JS, l["name"]) < 0:
            self.goto(l["url"])
        before = self._login_state(l["name"])
        smart = {"smart": True} if l.get("auth") else None
        use_demo = l["where"] in self.demo_ok
        self._mute = True   # 준비 단계: 같은 로그인 흐름은 앞에서 이미 판정했으므로 여기서는 기록하지 않음
        try:
            for mode in LOGIN_KEY_ORDER:
                idx = self.page.evaluate(LOGIN_FORM_INDEX_JS, l["name"])
                if idx < 0:
                    break
                self._submit_form(idx, mode, demo=use_demo, where="회원 전용 화면 > 로그인", flow="로그인",
                                  post_auth=True, fill_opt=smart, steps=True)
                self.flush_errors("회원 전용 화면 > 로그인", "")
                if self.page.evaluate(LOGIN_FORM_INDEX_JS, l["name"]) < 0:
                    break
        finally:
            self._mute = False
        self.page.wait_for_timeout(400)
        after = self._login_state(l["name"])
        return bool(before and after and not after["loginFormVisible"]
                    and (set(after["member"]) - set(before["member"]) or after["memberSel"]))

    def test_member_area(self, l):
        """
        로그인 상태로 화면을 다시 훑어, 비로그인 때는 없던 폼(주문서·예매 등)을 제출해 보고
        제출 뒤 뜨는 인증창(결제 인증 등)이 실제로 되는지 확인.
        인증창 결과와 JS·콘솔 오류만 기록하고, 그 밖의 폼 판정(반응 없음 등)은 하지 않음.
        """
        where0 = "회원 전용 화면"
        hint = (f"{self.open_step(l['url'])} → 로그인 → 주문·결제 등 회원 전용 화면에서 인증창이 뜨는지,"
                f" 인증번호 입력 후 완료되는지 직접 확인")
        tested, visited = [], 0
        try:
            if not self._member_login(l):
                self.add("수동", where0, "로그인 상태를 만들지 못해 회원 전용 화면의 인증창 검사 생략", hint)
                return
            found, names = [], set()
            seen, queue = set(self.guest_routes), list(self.guest_routes)
            pat, extra, preps = Counter(), 0, 0
            while queue and len(found) < MEMBER_MAX_FORMS:
                url = queue.pop(0)
                try:
                    self.goto(url)
                except PWError:
                    continue
                visited += 1
                self.flush_errors(f"회원 전용 {self.route_name(url)} 로드", f"{self.open_step(url)} (로그인 상태)")
                shown = self.page.url
                for f in self._forms_info():   # 비로그인 때는 없던 폼만(비밀번호 변경 등 비밀번호 폼은 제외)
                    if f["pw"] or f["name"] in self.guest_form_names or f["name"] in names:
                        continue
                    names.add(f["name"])
                    found.append((shown, f["name"]))
                try:
                    hrefs = self.page.eval_on_selector_all("a[href]", "els => els.map(e => [e.getAttribute('href'), e.href])")
                except PWError:
                    hrefs = []
                for raw, absu in hrefs:   # 로그인해야 보이는 새 화면
                    if extra >= MEMBER_MAX_ROUTES:
                        break
                    if not raw or raw.startswith(("javascript:", "mailto:", "tel:", "http", "#main")) or raw in ("#", "#content", "#top"):
                        continue
                    if absu in seen or not self.same_file(absu):
                        continue
                    p = urlparse(absu)
                    if not (p.query or p.fragment):
                        continue
                    seen.add(absu)
                    key = pattern(raw)
                    pat[key] += 1
                    if pat[key] <= SAME_PATTERN_LIMIT:
                        queue.append(absu)
                        extra += 1
                if preps < MEMBER_PREP_MAX:   # '바로 주문' 같은 버튼으로 주문서 등 다음 화면으로 넘어가 봄
                    try:
                        label = self.page.evaluate(PREP_BTN_JS, MEMBER_PREP_RE)
                        if label:
                            preps += 1
                            self.page.locator("[data-qa-prep]").first.click(timeout=2000)
                            self.page.wait_for_timeout(CLICK_WAIT_MS)
                            self.wait_settled()
                            now = self.page.url
                            if self.same_file(now) and now not in seen:
                                seen.add(now)
                                queue.insert(0, now)
                    except PWError:
                        pass
                    self.events = []
            for shown, fname in found:
                try:
                    self.goto(shown)
                    self.events = []
                    hit = next((f for f in self._forms_info() if f["name"] == fname), None)
                    if not hit:
                        continue
                    peek = self.page.evaluate(FORM_PEEK_JS, hit["idx"])
                    if not peek or peek["pw"] or re.search(MEMBER_SKIP_RE, peek["btn"], re.I):
                        continue
                    where = f"회원 전용 {self.route_name(shown)} > 폼({fname})"
                    flow = f"{self.open_step(shown)} (로그인 상태) → 폼({fname})에 값 입력 → 제출"
                    self._submit_form(hit["idx"], where=where, flow=flow, post_auth=True, keep=True,
                                      fill_opt={"smart": True, "natural": True})
                    self.flush_errors(where, flow)
                    tested.append(fname + ("(인증창 확인)" if self.last_auth else ""))
                except PWError:
                    continue
            if tested:
                self.add("수동", where0, f"로그인 상태로 화면 {visited}개를 다시 열어, 비로그인 때 없던 폼 {len(tested)}개를 제출해 인증창 확인: "
                                         + ", ".join(tested), hint)
            else:
                self.add("수동", where0, f"로그인 상태로 화면 {visited}개를 다시 열었으나 새로 나타난 폼이 없음", hint)
        except PWError as e:
            self.add("수동", where0, f"회원 전용 화면 검사 중단: {str(e).split(chr(10))[0][:60]}", hint)
        finally:
            try:
                self.goto(self.base_url)       # 열려 있던 창을 닫고
                self._logout_if_available()    # 원래(비로그인) 상태로
            except PWError:
                pass
            self.events = []

    def _find_logout(self):
        """
        보이는 로그아웃 버튼에 번호표(data-qa-logout)를 붙이고 그 글자를 돌려줌.
        [v5] 지금 화면에 없고 로그인 버튼도 보이지 않으면(=로그인 상태로 보이면) '마이페이지'·'내 정보' 같은 메뉴를 눌러 그 화면에서 찾음.
        """
        label = self.page.evaluate(LOGOUT_TAG_JS)
        if label or not LOGOUT_SEARCH:
            return label
        if (self.page.evaluate(FIND_TRIGGER_JS, ["data-qa-guestmark", LOGIN_TRIGGER_RE, None])
                or self.page.evaluate(FIND_TRIGGER_JS, ["data-qa-guestmark", LOGIN_TRIGGER_LOOSE_RE, None])):
            return None   # 로그인 버튼이 보임 → 비로그인 상태이므로 찾으러 다니지 않음
        tried = []
        for _ in range(LOGOUT_SEARCH_MAX):
            trig = self.page.evaluate(ACCOUNT_LINK_JS, [ACCOUNT_LINK_RE, tried])
            if not trig:
                break
            tried.append(trig)
            try:
                self.page.locator("[data-qa-account]").first.click(timeout=2000)
                self.page.wait_for_timeout(CLICK_WAIT_MS)
                self.wait_settled()
            except PWError:
                continue
            label = self.page.evaluate(LOGOUT_TAG_JS)
            if label:
                return label
        return None

    def _logout_if_available(self):
        if self._find_logout():
            self.page.locator("[data-qa-logout]").first.click(timeout=2000)
            self.wait_settled()

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

    def _stage(self, i):
        """진행 표시: '파일 3/100 이름  [2/5단계 ●◉○○○] 클릭 검사' + 전체 진행 막대 갱신"""
        n = len(STAGES)
        marks = "".join("■" if k <= i else "□" for k in range(n))
        self.bar.set_description(f"  └ {self.label}[{i + 1}/{n}단계 {marks}] {STAGES[i]}")
        self.bar.set_postfix_str("")
        if self.stage_cb:
            self.stage_cb(i)

    def run(self):
        routes = []
        try:
            self.bar.reset(total=1)
            self._stage(0)
            routes = self.discover_routes()
            self.bar.update(1)

            self._stage(1)
            self.test_clicks(routes)

            self._stage(2)
            self.test_hidden()

            self._stage(3)
            self.test_forms(routes)

            self._stage(4)
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
        if self.closed_popups:
            names = ", ".join(f"'{n}'" for n in sorted(self.closed_popups)[:MAX_SAMPLES])
            self.add("수동", "자동 팝업", f"화면을 열 때 뜬 팝업 {names}을(를) 닫고 검사함",
                     f"{self.file.name} 열기 → 팝업이 뜨는지, 닫기·오늘 하루 보지 않기가 동작하는지 직접 확인")        
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
    if level == "통과":   # 로그인·인증창이 실제로 동작함을 확인한 내용
        return "정상", f"{cat}: {msg}"
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
    if "인증창" in t or "인증 폼" in t:
        return "인증"
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
    print(f"검수 대상 {len(files)}개 파일 × {len(STAGES)}단계 = 총 {len(files) * len(STAGES)}단계  "
          f"({' → '.join(f'{i}.{n}' for i, n in enumerate(STAGES, 1))})")

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
            n_stage = len(STAGES)
            total_steps = len(files) * n_stage
            file_bar = tqdm(total=total_steps, desc="전체 진행", unit="단계", position=0, dynamic_ncols=True,
                            bar_format="{desc} {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt}단계 [{elapsed}<{remaining}]")
            inner_bar = tqdm(total=1, desc="  └ 준비", position=1, dynamic_ncols=True, leave=False,
                             bar_format="{desc} {percentage:3.0f}%|{bar:12}| {n_fmt}/{total_fmt} {postfix}")
            for fi, f in enumerate(files):
                def on_stage(i, fi=fi, f=f):   # 전체 진행 막대: 지금까지 끝낸 단계 수로 맞춤
                    file_bar.update(fi * n_stage + i - file_bar.n)
                    file_bar.set_description_str(f"전체 진행 · 파일 {fi + 1}/{len(files)} {f.name[:22]}")
                t = FileTester(browser, f, origin, inner_bar, stage_cb=on_stage,
                               label=f"파일 {fi + 1}/{len(files)} {f.name[:20]} ")
                n_routes = t.run()
                file_bar.update((fi + 1) * n_stage - file_bar.n)
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

    # 맨 마지막 줄: 결과 CSV 행 기준 비정상 건수(괄호 안 구분 순서 = 숫자 순서)
    abn = Counter(r[1] for r in rows)
    abn_files = {r[0] for r in rows if r[1] in ABNORMAL_LABELS}
    print(f"\n비정상({', '.join(ABNORMAL_LABELS)}) " + ", ".join(str(abn[k]) for k in ABNORMAL_LABELS)
          + f"  → 합계 {sum(abn[k] for k in ABNORMAL_LABELS)}건 (해당 파일 {len(abn_files)}개 / 전체 {len(files)}개)")

if __name__ == "__main__":
    main()
