"""
HTML 파일 난이도(Grade) 평가 + 주요 기능 추출 스크립트

진행 흐름
  1. html 폴더에 있는 파일명을 읽는다.
  2. 파일을 하나씩 열어 주요 기능을 찾는다. (근거 단어도 기록)
     - 일반 HTML 태그뿐 아니라 <script> 안에서 만들어지는 화면,
       <style> 안의 반응형 CSS(@media)까지 확인한다.
  3. 평가 항목(페이지 수, 최대 Depth, 기능 수)을 센다.
     - 기능 수 = 2번에서 찾은 기능 종류 수 (세부 흐름은 점수에 넣지 않는다)
  4. 항목별 점수를 합산해 grade(하/중/상)를 정한다.
  5. [NEW] 찾은 기능 안에서 '세부 흐름'을 구분한다.
     - 예) 로그인 → 일반 / SNS / 공동인증서 / 간편인증 / 생체인증 ...
     - 예) 결제   → 간편결제 / 카드 / 계좌이체 / 상품권 / 포인트 / 쿠폰 ...
     - 흐름마다 'AI가 시뮬레이션을 짤 때 확인할 순서(체크포인트)'를 함께 기록한다.
  6. 결과를 result.csv에 기록한다.
     (no, filename, grade, grade_memo, functions, flow_count,
      function_evidence, simulation_flows)

필요한 라이브러리:  pip install -r requirements.txt
"""

import csv
import os
import re

from bs4 import BeautifulSoup

# ──────────────────────────────────────────────
# 설정값 (필요하면 여기만 바꾸면 됩니다)
# ──────────────────────────────────────────────
HTML_FOLDER = "html_input_files"          # HTML 파일이 들어 있는 폴더
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


# ──────────────────────────────────────────────
# [NEW] 세부 흐름 사전
#   형식: {기능명: {흐름명: ([이 흐름이 있다고 볼 단어들], "시뮬레이션 체크포인트")}}
#   - 기능명은 위 FUNCTION_KEYWORDS의 이름과 똑같아야 합니다.
#   - 상위 기능이 감지된 경우에만 흐름을 찾습니다. (엉뚱한 오탐 방지)
#   - 세부 흐름은 기능 수(점수)에 포함하지 않습니다. → 기존 등급 기준이 그대로 유지됩니다.
#   - 단어 비교 규칙은 FUNCTION_KEYWORDS와 같습니다. (한글=포함, 영어=단어 단위)
#   - 체크포인트는 'A → B → C' 순서로 적습니다. AI가 시나리오를 만들 때 뼈대가 됩니다.
#   - 새 흐름이 필요하면 아래 형식을 복사해서 한 줄 추가하세요.
# ──────────────────────────────────────────────
FUNCTION_FLOWS = {
    "로그인, 로그아웃": {
        "일반 로그인 (아이디/비밀번호)": (
            ["아이디", "비밀번호", "password", "passwd", "user id", "userid",
             "이메일로 로그인", "이메일 로그인", "email login", "체험 계정"],
            "아이디·비밀번호 입력 → 로그인 클릭 → 성공 시 로그아웃 버튼/사용자명 노출, "
            "실패 시 오류 문구 노출",
        ),
        "SNS(소셜) 로그인": (
            ["sns 로그인", "sns로그인", "sns login", "소셜 로그인", "소셜로그인", "social login",
             "카카오 로그인", "카카오톡 로그인", "카카오로 로그인", "카카오로 시작",
             "네이버 로그인", "네이버로 로그인", "네이버로 시작",
             "구글 로그인", "구글로 로그인", "구글로 시작", "애플 로그인", "페이스북 로그인",
             "kakao login", "naver login", "google login", "apple login", "facebook login",
             "sign in with google", "sign in with apple", "continue with google",
             "continue with kakao", "oauth",
             "소셜 계정", "간편 로그인", "로 계속하기"],
            "SNS 버튼 클릭 → 외부 동의/인증 화면(모의) → 동의 → 서비스 복귀 → 로그인 완료 상태 확인",
        ),
        "공동·금융인증서 로그인": (
            ["공동인증서", "공인인증서", "금융인증서", "인증서 로그인", "인증서로 로그인",
             "인증서 선택", "인증서 암호", "체험용 인증서", "인증서", "certificate"],
            "인증서 로그인 클릭 → 인증서 선택 창 → 인증서 암호 입력 → 확인 → 로그인 완료 확인, "
            "암호 오류 시 안내 문구 확인",
        ),
        "간편인증 (PASS·모바일 신분증)": (
            ["간편인증", "간편 인증", "패스 인증", "pass 인증", "모바일 신분증", "모바일신분증",
             "휴대폰 인증", "휴대폰 본인", "본인확인", "본인 확인", "mobile id",
             "인증 방식", "인증 요청", "인증 승인", "인증 실패", "다른 인증", "모의 인증"],
            "간편인증 수단 선택 → 이름·생년월일·휴대폰 입력 → 인증 요청 → 인증 완료 → 로그인 확인",
        ),
        "생체인증 (지문·얼굴·패스키)": (
            ["생체", "지문", "얼굴 인식", "얼굴인식", "패스키", "biometric", "fingerprint",
             "face id", "faceid", "touch id", "touchid", "passkey"],
            "생체인증 버튼 클릭 → 인증 대기 화면 → 성공/실패 각각 확인 → 실패 시 다른 방식으로 전환 가능한지 확인",
        ),
        "2단계 인증 (OTP·인증번호)": (
            ["2단계", "이중 인증", "2차 인증", "보안카드", "로그인 인증번호", "login otp",
             "2fa", "mfa", "two factor", "verification code"],
            "1차 로그인 → 인증번호/OTP 입력 칸 노출 → 올바른 번호 입력 시 통과, "
            "틀린 번호·시간 초과 시 오류 확인",
        ),
        "자동 로그인·로그인 유지": (
            ["자동 로그인", "자동로그인", "로그인 유지", "로그인 상태 유지",
             "remember me", "keep me signed", "stay signed"],
            "체크 후 로그인 → 새로고침/재접속해도 로그인 상태 유지되는지 확인",
        ),
        "아이디·비밀번호 찾기/재설정": (
            ["아이디 찾기", "비밀번호 찾기", "비밀번호 재설정", "비밀번호 변경",
             "forgot password", "find id", "reset password"],
            "찾기 클릭 → 본인 확인(이메일/휴대폰) → 인증 → 새 비밀번호 설정 → 새 비밀번호로 로그인 확인",
        ),
        "비회원(게스트) 이용": (
            ["비회원", "게스트", "guest", "non member", "nonmember"],
            "비회원 이용 클릭 → 로그인 없이 주요 화면 접근 가능한지, 제한 기능은 안내되는지 확인",
        ),
        "SNS 계정 연동·해제": (
            ["계정 연동", "sns 연동", "소셜 연동", "연동 해제", "연동해제", "연결된 계정",
             "계정 연결", "연동하기", "연동 관리", "연동 완료", "연동 확정", "소셜 연결",
             "connected account", "linked account", "account link"],
            "마이페이지 연동 버튼 → SNS 인증(모의) → 연동 완료 표시 → 연동 해제 → 상태 원복 확인, "
            "연동 계정으로 로그인 가능한지 확인",
        ),
    },
    "회원가입": {
        "일반 가입 (아이디/이메일)": (
            ["아이디", "이메일", "email", "비밀번호 확인"],
            "가입 열기 → 입력 → 약관 체크 → 제출 → 완료 문구 확인 → (같은 시나리오 안에서) 로그인까지 이어서 확인",
        ),
        "SNS 간편 가입": (
            ["sns 가입", "소셜 가입", "간편 가입", "간편가입", "카카오로 가입", "네이버로 가입",
             "구글로 가입", "social signup", "sign up with google", "sign up with kakao"],
            "SNS 가입 버튼 → 외부 동의 화면(모의) → 추가 정보 입력 → 가입 완료 확인",
        ),
        "본인인증 (휴대폰·아이핀)": (
            ["본인인증", "본인 인증", "휴대폰 인증", "아이핀", "ipin", "인증번호"],
            "인증 요청 → 인증번호 입력 → 인증 완료 표시 → 인증 전에는 가입 버튼이 막히는지 확인",
        ),
        "약관 동의": (
            ["약관 동의", "약관동의", "개인정보 수집", "이용약관", "terms"],
            "전체 동의 체크 시 하위 항목 모두 체크 → 필수 약관 미체크 시 제출 불가 확인",
        ),
        "이메일 인증": (
            ["이메일 인증", "메일 인증", "인증 메일", "verify email", "email verification"],
            "인증 메일 발송 클릭 → 발송 안내 → 인증 코드 입력 → 인증 완료 확인",
        ),
        "중복 확인": (
            ["중복 확인", "중복확인", "사용 가능", "duplicate check"],
            "이미 있는 값 입력 시 '사용 불가', 새 값 입력 시 '사용 가능' 안내 확인",
        ),
        "사업자·기관 회원": (
            ["사업자", "기업 회원", "기관 회원", "법인", "business member"],
            "회원 유형 선택 → 사업자 번호 등 추가 입력 항목 노출 → 제출 → 완료 확인",
        ),
    },
    "결제, 환불": {
        "간편결제 (카카오페이·네이버페이 등)": (
            ["간편결제", "간편 결제", "카카오페이", "카카오 페이", "네이버페이", "네이버 페이",
             "토스페이", "삼성페이", "애플페이", "페이코",
             "kakaopay", "kakao pay", "naverpay", "naver pay", "tosspay", "toss pay",
             "samsung pay", "apple pay", "payco", "easy pay", "easypay", "simple pay"],
            "간편결제 수단 선택 → 결제하기 → 외부 결제창(모의) → 승인 → 주문 완료 화면 확인, "
            "결제창 닫기/취소 시 주문이 완료되지 않는지 확인",
        ),
        "신용·체크카드 결제": (
            ["신용카드", "체크카드", "카드 결제", "카드결제", "카드번호", "카드 번호", "할부",
             "카드사", "카드 할인", "카드 혜택",
             "credit card", "creditcard", "debit card", "card number", "card payment"],
            "카드 선택 → 카드번호·유효기간·CVC 입력 → (할부 개월 선택) → 결제 → 승인/실패 문구 확인",
        ),
        "계좌이체·무통장입금": (
            ["계좌이체", "계좌 이체", "무통장", "가상계좌", "실시간 계좌", "입금",
             "bank transfer", "banktransfer", "virtual account"],
            "계좌이체 선택 → 은행 선택 → 결제 → 가상계좌/입금 안내 노출 → 입금 대기 상태 확인",
        ),
        "휴대폰(소액) 결제": (
            ["휴대폰 결제", "휴대폰결제", "핸드폰 결제", "소액결제", "소액 결제", "통신사",
             "mobile payment", "phone bill"],
            "휴대폰 결제 선택 → 통신사·번호 입력 → 본인 인증(인증번호 요청·입력) → 결제 완료 확인, "
            "인증번호가 틀리면 결제가 진행되지 않는지 확인",
        ),
        "상품권 결제": (
            ["상품권", "금액권", "문화상품권", "해피머니", "기프트카드", "기프티콘", "모바일 상품권",
             "gift card", "giftcard", "voucher"],
            "상품권 번호/PIN 입력 → 잔액 조회 → 사용 금액 반영 → 부족하면 나머지 결제수단 요구하는지, "
            "잘못된 번호 오류 확인",
        ),
        "포인트·적립금 결제": (
            ["포인트 결제", "포인트 사용", "포인트 전액", "보유 포인트", "사용 포인트",
             "포인트 내역", "포인트 복원", "적립금", "마일리지", "예치금",
             "point", "points", "use point", "use points", "point pay", "point payment",
             "pay with point", "usepoint"],
            "보유 포인트 표시 → 사용 포인트 입력/전액 사용 → 결제 금액 차감 → 보유량 초과 입력 시 제한 확인 → "
            "결제 후 잔여 포인트 감소 확인",
        ),
        "쿠폰·할인코드": (
            ["쿠폰", "할인코드", "할인 코드", "프로모션 코드", "프로모션코드",
             "coupon", "promo code", "promocode", "discount code"],
            "쿠폰 선택/코드 입력 → 할인 금액 반영 → 최종 결제금액 재계산 → 잘못된·만료 코드 오류 확인",
        ),
        "복합(분할) 결제": (
            ["복합 결제", "복합결제", "분할 결제", "분할결제", "혼합 결제", "나머지 결제",
             "잔액 결제", "split payment"],
            "포인트/상품권 먼저 적용 → 남은 금액을 카드·간편결제로 결제 → 합계가 총액과 일치하는지 확인",
        ),
        "영수증·증빙 (현금영수증·세금계산서)": (
            ["현금영수증", "세금계산서", "영수증", "receipt", "invoice"],
            "발급 신청 체크 → 번호 입력 → 결제 완료 후 발급 완료/내역 노출 확인",
        ),
        "배송지 관리 (주소록)": (
            ["배송지", "배송주소록", "배송 주소록", "배송정보", "배송 정보", "주소록", "delivery address"],
            "배송지 추가/수정/삭제 → 저장 → 주문 시 선택한 배송지가 반영되는지, 삭제 후 목록이 갱신되는지 확인",
        ),
        "구매확정·포인트 적립": (
            ["구매확정", "구매 확정", "포인트 적립", "적립 예정"],
            "구매확정 클릭 → 확정 동의 → 상태가 '구매확정'으로 변경 → 포인트 적립 내역 반영 → "
            "확정 후에는 취소가 막히는지 확인",
        ),
        "결제 취소·환불·반품": (
            ["결제 취소", "주문 취소", "취소 요청", "취소 확정", "취소 사유", "환불", "반품",
             "교환 신청", "교환 요청", "반품 신청", "환불 계좌",
             "cancel order", "order cancel", "return request", "refund"],
            "주문 내역에서 취소/환불 요청 → 사유 선택 → 확인 → 상태 '취소/환불 처리'로 변경, "
            "사용한 포인트·상품권·쿠폰이 복구되는지 확인",
        ),
    },
    "댓글, 문의, 답변": {
        "채팅·실시간 상담": (
            ["대화", "채팅", "챗봇", "chat"],
            "메시지 입력 → 보내기 → 응답 표시 → 대화 내역 삭제 시 목록이 비워지는지 확인",
        ),
        "문의 작성·내역": (
            ["문의 작성", "문의하기", "내 문의", "문의 내역", "inquiry"],
            "문의 작성 → 제출 → 내 문의 내역에 방금 글 노출 → (로그아웃 상태에서는) 작성 제한 확인",
        ),
    },
    "신청, 접수, 제출": {
        "서류·파일 첨부": (
            ["첨부", "서류", "attachment", "upload"],
            "파일 선택 → 첨부 목록 표시 → 삭제/교체 → 필수 서류 누락 시 제출 불가 확인",
        ),
        "임시저장": (
            ["임시저장", "임시 저장", "save draft", "draft"],
            "일부 입력 후 임시저장 → 새로고침/재진입 → 입력값 복원 확인",
        ),
        "신청 내역·진행 조회": (
            ["신청 내역", "접수 내역", "접수 번호", "접수번호", "처리 현황", "진행 상황"],
            "제출 완료 → 접수번호 발급 → 내역 화면에서 방금 신청건 노출 및 상태 확인",
        ),
        "신청 수정·취소": (
            ["신청 취소", "접수 취소", "신청 수정", "취소 신청", "withdraw"],
            "신청 내역에서 수정/취소 → 확인 → 상태 변경 및 수정값 반영 확인",
        ),
    },
    "공유": {
        "카카오톡 공유": (
            ["카카오톡 공유", "카카오 공유", "kakao share", "kakaotalk"],
            "공유 클릭 → 카카오톡 공유 창(모의) 열림 → 닫기/완료 후 원래 화면 유지 확인",
        ),
        "링크 복사": (
            ["링크 복사", "주소 복사", "url 복사", "copy link", "copy url"],
            "복사 클릭 → '복사되었습니다' 안내 노출 확인",
        ),
        "이메일·SNS 공유": (
            ["이메일 공유", "메일 공유", "페이스북 공유", "트위터 공유", "facebook share",
             "twitter share", "email share"],
            "공유 수단 선택 → 외부 창/새 탭 열림 관찰 → 원래 화면 유지 확인",
        ),
    },
}

# '분류 안 된 버튼' 목록에서 제외할 단순 조작 버튼
IGNORE_LABELS = {
    "확인", "취소", "닫기", "이전", "다음", "더보기", "더 보기", "홈", "메뉴", "목록", "top", "맨위로",
    "ok", "cancel", "close", "prev", "previous", "next", "more", "home", "menu", "back",
}

# [NEW] 오탐 방지 ①: 이 문구는 비교 전에 다른 말로 바꿔서 읽는다.
#   예) 'voucher register'(상품권 등록)의 'register'가 회원가입으로 잡히는 것을 막는다.
PHRASE_REWRITE = {
    "voucher register": "voucher",
    "register voucher": "voucher",
    "상품권 등록": "상품권",
}

# [NEW] 오탐 방지 ②: 상위 기능의 근거가 '약한 단어'뿐이면 세부 흐름은 만들지 않는다.
#   (기능 수·등급 계산은 그대로. 흐름만 걸러서 AI가 없는 기능의 시뮬레이션을 짜지 않게 한다.)
#   예) 결제 화면의 '본인 인증'만으로 회원가입 흐름(가입 폼, 사업자 회원 등)을 만들지 않는다.
WEAK_PARENT_KEYWORDS = {
    "회원가입": {"본인인증", "본인 인증", "약관 동의", "약관동의", "register"},
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
    text = normalize(expand_template(" ".join(clues)))
    for old, new in PHRASE_REWRITE.items():
        text = text.replace(old, new)
    return text


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


def detect_flows(clue_texts, found):
    """
    [NEW] 찾은 기능 안에서 세부 흐름을 구분한다.
      - 상위 기능(found)에 있는 것만 본다.
      - 돌려주는 값: {기능명: {흐름명: [근거 단어, ...]}}
    """
    flows = {}
    for parent, flow_defs in FUNCTION_FLOWS.items():
        if parent not in found:
            continue
        weak = WEAK_PARENT_KEYWORDS.get(parent, set())
        if not any(hit not in weak for hit in found[parent]):
            continue                      # 근거가 약한 단어뿐이면 흐름은 만들지 않음
        for flow_name, (keywords, _check) in flow_defs.items():
            hits = []
            for text in clue_texts:
                for kw in keywords:
                    if has_keyword(text, kw) and kw not in hits:
                        hits.append(kw)
            if hits:
                flows.setdefault(parent, {})[flow_name] = hits
    return flows


def detect_functions(soup, script_soup, css_text):
    """
    주요 기능과 세부 흐름을 찾는다.
    돌려주는 값
      found        : {기능명: [근거1, 근거2, ...]}  (기능 사전 순서대로)
      flows        : {기능명: {흐름명: [근거, ...]}}  (흐름 사전 순서대로)
      unclassified : [사전에 안 걸린 버튼 글자, ...]
    """
    soups = [soup, script_soup]
    clue_texts = [collect_clue_text(s) for s in soups]   # 단서 글자는 한 번만 계산해서 재사용
    found = {}
    for text in clue_texts:
        for name, hits in match_functions(text).items():
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

    # [NEW] 세부 흐름 (기능 수·점수에는 영향 없음)
    flows = detect_flows(clue_texts, found)
    return found, flows, find_unclassified_buttons(soups)


def count_flows(flows):
    """찾은 세부 흐름의 총 개수"""
    return sum(len(v) for v in flows.values())


def format_functions(found, flows):
    """
    functions 열: 기능명 목록 + (있으면) 그 아래에 세부 흐름
      - 로그인, 로그아웃
          · SNS(소셜) 로그인
          · 공동·금융인증서 로그인
    """
    if not found:
        return "(감지된 기능 없음)"
    lines = []
    for name in found:
        lines.append(f"- {name}")
        for flow_name in flows.get(name, {}):
            lines.append(f"    · {flow_name}")
    return "\n".join(lines)


def format_evidence(found, flows, unclassified):
    """function_evidence 열: 기능별 근거 + 흐름별 근거 + 사전에 없는 버튼(참고)"""
    lines = []
    for name, hits in found.items():
        lines.append(f"- {name}: {', '.join(hits)}")
        for flow_name, flow_hits in flows.get(name, {}).items():
            lines.append(f"    · {flow_name}: {', '.join(flow_hits)}")
    if unclassified:
        lines.append("- (참고) 분류 안 된 버튼: " + ", ".join(unclassified))
    return "\n".join(lines) if lines else "(근거 없음)"


def format_simulation_flows(flows):
    """
    [NEW] simulation_flows 열: AI가 시뮬레이션을 짤 때 쓰는 흐름별 체크포인트
      - 로그인, 로그아웃 > SNS(소셜) 로그인: SNS 버튼 클릭 → ... → 로그인 완료 상태 확인
    """
    lines = []
    for parent, flow_map in flows.items():
        for flow_name in flow_map:
            _keywords, check = FUNCTION_FLOWS[parent][flow_name]
            lines.append(f"- {parent} > {flow_name}: {check}")
    return "\n".join(lines) if lines else "(세부 흐름 없음)"


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

    found, flows, unclassified = detect_functions(soup, script_soup, css_text)
    features = len(found)          # 점수는 '기능 종류 수'로만 계산 (세부 흐름 제외)
    flow_total = count_flows(flows)

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
        f" / (참고) 세부 흐름 {flow_total}개, 점수 미반영"
    )
    return {
        "grade": grade,
        "grade_memo": grade_memo,
        "functions": format_functions(found, flows),
        "flow_count": flow_total,
        "function_evidence": format_evidence(found, flows, unclassified),
        "simulation_flows": format_simulation_flows(flows),
    }


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

    # 2~5. 파일을 하나씩 평가해서 결과 모으기
    FIELDS = ["no", "filename", "grade", "grade_memo", "functions", "flow_count",
              "function_evidence", "simulation_flows"]
    rows = []
    for no, filename in enumerate(html_files, start=1):
        filepath = os.path.join(HTML_FOLDER, filename)
        try:
            result = evaluate_file(filepath)
        except Exception as e:          # 파일 하나가 깨져도 나머지는 계속 진행
            result = {
                "grade": "오류", "grade_memo": f"파일 처리 실패: {e}", "functions": "",
                "flow_count": 0, "function_evidence": "", "simulation_flows": "",
            }

        rows.append({"no": no, "filename": filename, **result})
        print(f"[{no}] {filename} → {result['grade']}  ({result['grade_memo']})")
        print("    " + result["functions"].replace("\n", "\n    "))

    # 6. CSV 저장 (utf-8-sig: 엑셀에서 열어도 한글이 깨지지 않음)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n완료! 결과가 '{OUTPUT_CSV}'에 저장되었습니다.")