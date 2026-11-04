"""HTML 폴더 검사. Python 표준 라이브러리로 실행; --browser는 Playwright 필요."""
import argparse
import html
import json
import os
import re
import hashlib
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


def progress(items, description, label):
    """tqdm 설치 시 진행 막대, 미설치 시 파일별 진행 로그."""
    try:
        from tqdm import tqdm
    except ImportError:
        print('진행 막대 설치: python -m pip install tqdm (현재는 진행 로그 표시)', flush=True)
        for number, item in enumerate(items, 1):
            print(f'[{description}] {number}/{len(items)} 시작: {label(item)}', flush=True)
            yield item
            print(f'[{description}] {number}/{len(items)} 처리 완료', flush=True)
        return
    with tqdm(total=len(items), desc=description, unit='파일', dynamic_ncols=True) as bar:
        for item in items:
            bar.set_postfix_str(str(label(item)), refresh=True)
            yield item
            bar.update(1)


def collect_html(root, out):
    paths = []
    for current, dirs, files in os.walk(root):
        current = Path(current)
        # 제외 폴더에는 진입하지 않는다. Windows 기준 대소문자도 무시한다.
        dirs[:] = sorted(name for name in dirs
                         if name.casefold() != 'history'
                         and not (current / name).resolve().is_relative_to(out))
        for name in files:
            path = current / name
            if path.suffix.lower() in ('.html', '.htm') and not path.resolve().is_relative_to(out):
                paths.append(path)
    return sorted(paths)


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items = []
        self.ids = set()
        self.title = ''
        self.in_title = False
        self.active_controls = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get('id'):
            self.ids.add(a['id'])
        if tag == 'title':
            self.in_title = True
        self.items.append((tag, a))
        if tag in ('a', 'button', 'label'):
            self.active_controls.append((tag, a))

    def handle_endtag(self, tag):
        for index in range(len(self.active_controls) - 1, -1, -1):
            if self.active_controls[index][0] == tag:
                del self.active_controls[index:]
                break
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        for _, attrs in self.active_controls:
            attrs['_text'] = attrs.get('_text', '') + data
        if self.in_title:
            self.title += data


def estimate_grade(source, parsed):
    """코드 신호로 구현 복잡도를 잠정 분류한다. 기능 정상 여부와 별개다."""
    js = '\n'.join(re.findall(r'<script\b[^>]*>(.*?)</script\s*>', source, re.I | re.S))
    rules = [
        ('검색', r'(?:function\s+\w*search\w*|\b(?:search|query)\s*[:=]|\.includes\s*\()'),
        ('조건 필터', r'\.filter\s*\('),
        ('정렬', r'\.sort\s*\('),
        ('상세·팝업', r'(?:function\s+\w*(?:detail|modal)\w*|\b(?:openDetail|showModal)\s*\(|[\x22\x27]dialog[\x22\x27])'),
        ('입력·제출', r'(?:FormData\s*\(|addEventListener\s*\(\s*[\x22\x27]submit)'),
        ('다운로드', r'(?:\.download\s*=|createObjectURL\s*\()'),
        ('관심·선택 상태', r'(?:\.add\s*\(|\.delete\s*\(|\b(?:toggleSave|toggleFavorite)\s*\()'),
        ('예약·신청·취소 흐름', r'(?:function\s+\w*(?:reserve|booking|cancel|apply|checkout)\w*|data-action\s*=\s*[\x22\x27](?:cancel|submit))'),
    ]
    features = [name for name, pattern in rules if re.search(pattern, js, re.I)]
    interactive = any(tag in ('button','input','select','form') for tag, _ in parsed.items) or bool(re.search(r'(?:addEventListener|\.onclick\s*=)',js))
    if interactive and not features:
        features = ['버튼·화면 상호작용']
    routes = set()
    for tag, attrs in parsed.items:
        href = attrs.get('href', '')
        if tag == 'a' and href.startswith('#/'):
            routes.add(href.split('?')[0].split('/')[1])
    routes.update(re.findall(r"case\s+['\"]([\w-]+)['\"]\s*:", js))
    multi_view = len(routes) >= 4
    detail = '상세·팝업' in features
    validation = bool(re.search(r'(?:function\s+\w*validat\w*|checkValidity\s*\(|reportValidity\s*\(|setCustomValidity\s*\()',js,re.I))
    required = any('required' in attrs or attrs.get('type') in ('email','number','date') for _,attrs in parsed.items)
    persistence = bool(re.search(r'(?:localStorage|sessionStorage)\s*\.\s*setItem\s*\(|indexedDB\s*\.',js))
    state = bool(re.search(r'\.(?:push|splice|add|delete)\s*\(',js))
    complex_flow = persistence and validation and ('예약·신청·취소 흐름' in features or multi_view)
    # API 흔적만으로 인증·권한 구현을 인정하지 않는다.
    api = bool(re.search(r'(?:\bfetch\s*\(|\bXMLHttpRequest\b|\baxios\s*\.)',js))
    scores = [0 if len(features)<=3 else 1 if len(features)<=7 else 2,
              2 if multi_view else 1 if detail or routes else 0,
              2 if validation else 1 if required or '입력·제출' in features or '검색' in features else 0,
              2 if persistence else 1 if state else 0,
              2 if complex_flow else 1 if len(features)>=2 else 0,
              1 if api else 0]
    total = sum(scores)
    grade = 'Low' if total <= 3 else 'Medium' if total <= 7 else 'High'
    why = ('검색·선택 위주의 단순한 구성' if grade=='Low' else '여러 조건과 상세 화면·상태 변경을 함께 확인해야 하는 구성' if grade=='Medium' else '여러 화면과 입력 검증·저장·후속 처리까지 연결된 구성')
    evidence = features + (['브라우저 저장 코드'] if persistence else []) + (['입력 검증 함수'] if validation else []) + (['여러 화면 분기'] if multi_view else []) + (['API 호출 흔적'] if api else [])
    result = dict(grade=grade, grade_score=total, grade_scores=scores, grade_reason=why,
                grade_evidence=evidence, grade_method='코드 신호 기반 자동 추정 · 잠정',
                source_hash=hashlib.sha256(source.encode('utf-8')).hexdigest())
    # 검토한 버전과 내용이 정확히 같을 때만 직접 검토한 판정을 재사용한다.
    reviewed = {
        'c255b56dcdfd55b5b7b554e646eac79c97be024b1be7aff39486ff8fb7659d7f': (
            [1,1,1,0,1,0], '검색·유형·기간 필터, 빠른 조건, 로그 상세·복사, 조회 결과 다운로드가 연결돼 있어 Medium으로 판단했어요. 로그인 화면이 아니라 로그인 기록을 조회하는 사이트예요.',
            ['검색','조건 필터','상세·팝업','입력·제출','다운로드','기록 ID 복사']),
        '681b600a8dc2eeb1a794951eb4a1b2ee45d04dcad1366a0987646c1ba66df067': (
            [1,1,1,1,1,0], '매물 검색·조건·정렬, 목록과 지도 핀의 상세 연결, 관심 매물 선택과 다운로드가 있어 Medium으로 판단했어요. 지도는 모의 화면이고 관심 목록은 메모리에만 보관해요.',
            ['검색','조건 필터','정렬','상세·팝업','관심·선택 상태','다운로드','지도 핀과 매물 연결']),
        '21b8248b063908d9ef1f0f548294d93761fe1483dbebb00c5221d846e430ded1': (
            [1,2,2,2,2,0], '도서·프로그램·공간을 검색한 뒤 신청→검증→저장→조회→취소까지 이어지고, 날짜·정원 조건과 확인서 다운로드도 있어 High로 판단했어요.',
            ['검색','조건 필터','상세·팝업','입력·제출','입력 검증 함수','예약·신청·취소 흐름','브라우저 저장 코드','여러 화면 분기','다운로드']),
        '6f9f53caf7542c52de2e1704518e8c0c46a514160fb2d8811c6948aa41c3ddcc': (
            [2,1,1,1,1,0], '티켓 등록·검색·필터·정렬, 상세 답변, 담당자·상태 변경, 해결 처리와 다운로드가 연결돼 있어 Medium으로 판단했어요. 변경 내용은 메모리에만 보관해요.',
            ['검색','조건 필터','정렬','상세·팝업','다운로드','티켓 등록·답변·해결']),
    }
    if result['source_hash'] in reviewed:
        scores, reason, evidence = reviewed[result['source_hash']]
        total = sum(scores)
        result.update(grade='Low' if total<=3 else 'Medium' if total<=7 else 'High',
                      grade_score=total, grade_scores=scores, grade_reason=reason,
                      grade_evidence=evidence, grade_method='Codex 직접 코드 검토')
    return result


def inspect_file(path, root, image_review=False):
    p = PageParser()
    source = path.read_text(encoding='utf-8-sig', errors='replace')
    p.feed(source)
    checks = []

    def add(name, status, detail):
        checks.append(dict(item=name, status=status, detail=detail))

    for n, (tag, a) in enumerate(p.items, 1):
        visible = ' '.join(a.get('_text', '').split())
        label = a.get('aria-label') or a.get('title') or visible[:90] or a.get('alt') or a.get('placeholder') or a.get('id') or {'a':'이름 없는 링크', 'button':'이름 없는 버튼', 'form':'입력·제출 화면', 'img':'이미지', 'script':'스크립트 파일', 'link':'스타일·참조 파일'}.get(tag, '선택 항목')
        if tag in ('a', 'img', 'script', 'link'):
            attr = 'href' if tag in ('a', 'link') else 'src'
            url = a.get(attr)
            if url is None:
                if tag == 'a':
                    add(label, '확인 필요', 'href 없음. 스크립트 연결 여부 확인')
                continue
            parsed = urlsplit(url)
            if parsed.scheme or parsed.netloc:
                if tag == 'a':
                    add(label, '확인 필요', f'외부/특수 링크의 목적지와 동작 확인: {url}')
                continue
            if not parsed.path:
                if parsed.fragment:
                    exists = unquote(parsed.fragment) in p.ids
                    add(label, '통과' if exists else '확인 필요',
                        f'동일 문서 대상 ID {"존재" if exists else "없음; 스크립트 처리 확인"}: {url} (정적 검사)')
                elif tag == 'a':
                    add(label, '확인 필요', '빈 링크 또는 # 링크. 클릭 결과 확인')
                continue
            if parsed.path.startswith('/'):
                add(label, '확인 필요', f'서버 루트 기준 경로. 실제 운영 서버에서 확인: {url}')
                continue
            target = path.parent / unquote(parsed.path)
            exists = target.is_file()
            add(label, '통과' if exists else '불일치',
                f'로컬 참조 파일 {"존재" if exists else "없음"}: {url} (정적 검사; 기능 정상 판정 아님)')
            if exists and tag == 'a' and parsed.fragment:
                add(label + ' 연결 화면', '확인 필요', f'연결 문서의 대상 위치·선택값 반영 확인: {url}')
        if tag == 'button' or (tag == 'input' and a.get('type', '').lower() in ('submit', 'button', 'checkbox', 'radio')):
            add(label, '확인 필요', '클릭 → 기대 화면/선택 상태/데이터 반영을 수동 확인')
        if tag == 'form':
            add(label, '확인 필요', '정상값·빈칸·잘못된 값 제출 결과 확인')
        if tag == 'img' and image_review:
            add(label + ' 이미지', '확인 필요', f'인물·모델 여부 및 교체 요청 확인: {a.get("src", "src 없음")} (자동 판별 안 함)')
    counts = Counter(tag for tag, _ in p.items)
    add('메인 페이지 연결 흐름', '확인 필요', '메뉴·배너·상품에서 시작하여 연결 화면, 선택값 반영, 돌아오기까지 확인')
    if not image_review:
        add('이미지 교체 대상', '확인 필요', '쇼핑몰 여부 확인. 해당하면 인물·모델 이미지와 대체 이미지 사용 권한 확인')
    # DOM 개수는 독립 기능 수와 다르므로 Grade 확정에는 사용하지 않는다.
    return dict(file=str(path.relative_to(root)), title=p.title.strip() or path.stem,
                counts=dict(counts), **estimate_grade(source, p), source_uri=path.as_uri(),
                checks=checks)


def browser_checks(pages, root):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return 'Playwright 미설치: 브라우저 검사 미실행. 정적 검사 결과만 생성했습니다.'
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for report in progress(pages, '2. 브라우저 검사', lambda item: item['file']):
                context = browser.new_context(viewport={'width': 1366, 'height': 900}, accept_downloads=False)
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' else None)
                page.on('requestfailed', lambda req: errors.append(f'요청 실패: {req.url} / {req.failure}'))
                try:
                    page.goto((root / report['file']).as_uri(), wait_until='load', timeout=15000)
                    page.wait_for_timeout(800)
                    report['checks'].append(dict(item='브라우저 초기 로딩', status='통과', detail='Chromium file:// 로딩 완료. 클릭 동작은 별도 확인'))
                    broken = page.locator('img').evaluate_all('(imgs) => imgs.filter(i => i.currentSrc && i.complete && i.naturalWidth === 0).map(i => i.currentSrc)')
                    for src in broken:
                        report['checks'].append(dict(item='이미지 로딩', status='불일치', detail=src))
                    for error in dict.fromkeys(errors):
                        report['checks'].append(dict(item='브라우저 실행 오류', status='불일치', detail=error))
                except Exception as error:
                    report['checks'].append(dict(item='브라우저 검사', status='확인 필요', detail=str(error)))
                finally:
                    context.close()
            browser.close()
    except Exception as error:
        return f'브라우저 검사 일부 또는 전체 미실행: {error}'
    return '브라우저 초기 로딩 검사 실행. file:// 환경 차이는 실제 서버에서 재확인하세요.'


def review_tasks(page):
    features = page.get('grade_evidence', [])
    tasks = [dict(key='main', title='메인 메뉴와 배너 눌러보기', instruction='메인 화면의 메뉴·배너·카드를 하나씩 누르세요. 이름에 맞는 화면이 열리는지 확인하세요.')]
    options = [
        ('search', ['검색','조건 필터','정렬'], '검색·필터·정렬 확인', '검색어나 조건을 바꿔보세요. 결과가 맞게 바뀌는지, 결과가 없을 때 안내가 나오는지 확인하세요.'),
        ('detail', ['상세·팝업'], '상세 화면 열고 닫기', '목록에서 항목을 누르세요. 누른 항목의 정보가 나오는지, 닫은 뒤 목록으로 돌아오는지 확인하세요.'),
        ('form', ['입력·제출','입력 검증 함수'], '입력하고 제출하기', '정상 입력으로 제출한 뒤 결과를 확인하세요. 빈칸·잘못된 입력으로도 제출해 안내나 차단이 나오는지 확인하세요.'),
        ('state', ['관심·선택 상태'], '선택·취소 결과 확인', '체크·관심 등록·선택을 했다가 취소하세요. 표시와 개수가 맞는지 확인하세요.'),
        ('flow', ['예약·신청·취소 흐름'], '신청부터 조회·취소까지 확인', '테스트 정보로 신청한 뒤 조회 화면에서 같은 내역을 찾으세요. 취소 후 상태·잔여 수량도 확인하세요. 실제 접수되는 서비스는 테스트 환경을 사용하세요.'),
        ('storage', ['브라우저 저장 코드'], '새로고침 후 기록 확인', '저장한 기록이 새로고침 뒤에도 남는지 확인하세요. 저장했다고 안내했는데 사라지면 오류로 기록하세요.'),
        ('download', ['다운로드'], '다운로드 파일 열어보기', '다운로드 버튼을 누른 뒤 받은 파일을 여세요. 화면에서 선택한 내용과 파일 내용이 맞는지 확인하세요.'),
    ]
    for key, signals, title, instruction in options:
        if any(signal in features for signal in signals):
            tasks.append(dict(key=key, title=title, instruction=instruction))
    if '티켓 등록·답변·해결' in features:
        tasks.append(dict(key='ticket', title='티켓 등록·답변·해결 확인', instruction='티켓을 등록하고 목록에서 찾으세요. 상세에서 답변·담당자·상태를 바꾸고, 해결 처리 뒤 목록과 대시보드 숫자가 맞는지 확인하세요. 이 버전은 새로고침 뒤 기록 유지를 지원하지 않아요.'))
    if page.get('source_hash') == '681b600a8dc2eeb1a794951eb4a1b2ee45d04dcad1366a0987646c1ba66df067':
        tasks.append(dict(key='reviewed-download', title='우선 확인: 다운로드·상세·지도 버튼', instruction='코드에서 버튼 연결 중 실행이 중단될 수 있는 부분을 발견했어요. 다운로드, 매물 상세, 지도 확대 버튼을 먼저 눌러보세요. 수정 요청: 다운로드 버튼을 찾는 querySelector 호출을 querySelectorAll로 바꾸고 재검수. 실제 증상은 브라우저에서 확인해야 해요.'))
    tasks.append(dict(key='images', title='인물·모델 이미지 교체 대상 확인', instruction='쇼핑몰이면 인물·모델 사진이 남아 있는지 확인하고 교체 요청을 기록하세요. 해당 이미지가 없거나 쇼핑몰이 아니면 해당 없음을 선택하세요. 사용 권한은 별도로 확인하세요.'))
    return tasks


def render(data):
    """검색 가능한 목록과 쉬운 용어로 구성한 검수 화면."""
    e = lambda value: html.escape(str(value), quote=True)
    nav, panels, overview = [], [], []
    for i, page in enumerate(data['sites']):
        tasks = review_tasks(page)
        issues = [x for x in page['checks'] if x['status'] == '불일치']
        grade = page.get('grade', '미산정')
        filename = page['file']
        site_id = re.match(r'\d+', Path(filename).name)
        display_id = site_id.group() if site_id else str(i+1)
        nav.append(f'<button class="site-link" data-index="{i}" onclick="showSite({i})"><span class="site-top"><b>#{e(display_id)}</b><span class="grade {e(grade)}">{e(grade)}</span></span><span class="site-title">{e(page["title"])}</span><small>{e(filename)}</small><span class="site-bottom" id="nav-state{i}"></span></button>')
        overview.append(f'<tr class="summary-row" data-index="{i}"><td><button class="text-button" onclick="showSite({i})">#{e(display_id)} · {e(page["title"])}</button><small>{e(filename)}</small></td><td><span class="grade {e(grade)}">{e(grade)}</span></td><td>{len(issues)}개</td><td id="summary-state{i}"></td></tr>')
        issue_cards = []
        for j, issue in enumerate(issues):
            kind = issue['item']
            detail = issue['detail']
            if '로컬 참조 파일 없음' in detail:
                friendly = '연결할 파일을 찾지 못했어요'
                action = '아래 경로의 파일이 실제로 있는지 확인하세요. 파일이 없으면 추가하거나 홈페이지의 연결 경로를 수정해야 합니다.'
            elif '이미지' in kind:
                friendly = '이미지가 불러와지지 않았어요'
                action = '해당 이미지를 화면에서 확인하세요. 인터넷 연결이나 이미지 주소를 확인하고, 필요하면 대체 이미지로 교체하세요.'
            else:
                friendly = '화면 실행 중 오류가 기록됐어요'
                action = '원본 사이트를 열어 메뉴·버튼을 확인하세요. 재현되면 아래 오류 기록과 함께 수정을 요청하세요.'
            issue_cards.append(f'<article class="issue-card"><strong>{e(kind)} · {friendly}</strong><p>{action}</p><details><summary>오류 기록 보기</summary><pre>{e(detail)}</pre></details></article>')
        task_cards = []
        for task in tasks:
            key = f'{filename}:task:{task["key"]}'
            task_cards.append(f'<article class="task-card"><div><h3>{e(task["title"])}</h3><p>{e(task["instruction"])}</p></div><label class="result-label">내 확인 결과<select data-review="{i}" data-save="{e(key)}:status"><option>미검수</option><option>정상</option><option>오류</option><option>해당 없음</option><option>수정 확인 완료</option></select></label><textarea data-save="{e(key)}:note" aria-label="{e(task["title"])} 메모" placeholder="문제가 있으면: 누른 곳 → 생긴 문제 → 수정 요청"></textarea></article>')
        raw = ''.join(f'<tr><td>{e(x["item"])}</td><td>{e(x["status"])}</td><td>{e(x["detail"])}</td><td><select data-save="{e(filename)}:{j}:status"><option>미검수</option><option>정상</option><option>오류</option><option>해당 없음</option><option>수정 확인 완료</option></select><textarea data-save="{e(filename)}:{j}:note" placeholder="기존 상세 기록"></textarea></td></tr>' for j,x in enumerate(page['checks']))
        evidence = ' · '.join(page.get('grade_evidence', [])) or '상호작용 코드 신호가 적음'
        source_link = f'<a class="button primary" href="{e(page["source_uri"])}" target="_blank" rel="noopener">원본 사이트 열기 ↗</a>' if page.get('source_uri') else ''
        changed_notice = '<div class="issue-card">원본이 이전 검사 이후 바뀌었어요. 아래 자동 검사 기록은 예전 결과이므로 일반 검사 명령으로 다시 검사해 주세요.</div>' if page.get('source_changed') else ''
        panels.append(f'''<section class="view site-panel" id="site{i}" hidden>
<div class="page-heading"><div><small>사이트 #{e(display_id)}</small><h1>{e(page["title"])}</h1><p class="filename">{e(filename)}</p></div>{source_link}</div>
{changed_notice}
<div class="site-controls"><label>이 사이트 검수 상태 <select data-site-status="{i}" data-save="{e(filename)}:site-status"><option>미검수</option><option>검수 중</option><option>수정 필요</option><option>검수 완료</option></select></label><span id="task-progress{i}"></span></div>
<div class="grade-card"><span class="grade {e(grade)}">{e(grade)}</span><div><b>기능 난이도 · {e(page.get('grade_method','미산정'))}</b><p>{e(page.get('grade_reason','다시 검사하면 코드 기반 난이도가 표시됩니다.'))}</p><small>근거: {e(evidence)}. 오류 개수와 별개이며, 실제 동작을 보증하는 등급은 아니에요.</small></div></div>
<h2>1. 프로그램이 발견한 문제 <span class="count">{len(issues)}개</span></h2>
{''.join(issue_cards) or '<div class="empty-ok">자동 검사에서 발견한 문제는 없어요. 아래 기능은 직접 눌러서 확인해 주세요.</div>'}
<h2>2. 직접 눌러볼 항목 <span class="count">{len(tasks)}개</span></h2><p class="muted">원본 사이트에서 확인한 다음 결과를 선택하세요. 선택과 메모는 자동 저장돼요.</p>
{''.join(task_cards)}<label class="overall-note">이 사이트 수정 요청 요약<textarea data-save="{e(filename)}:overall-note" placeholder="예: 상단 검색이 안 됨 / 상품 상세에서 장바구니 이동 확인 필요"></textarea></label>
<details class="technical"><summary>3. 자동 검사 상세·이전 검수 기록 보기</summary><p>여기의 통과는 파일이나 연결 위치가 있다는 뜻이에요. 버튼을 눌러 기능이 정상 동작하는지까지 검사한 것은 아니에요.</p><div class="table-scroll"><table><tr><th>화면 항목</th><th>자동 기록</th><th>검사 상세</th><th>기존 수동 기록</th></tr>{raw}</table></div></details></section>''')
    payload = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c')
    template = '''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>홈페이지 검수</title>
<style>
:root{font:15px/1.6 "Segoe UI",system-ui,sans-serif;color:#253247;background:#f5f7fb}*{box-sizing:border-box}body{margin:0}button,input,select,textarea{font:inherit}button,a,select{touch-action:manipulation}button{cursor:pointer}button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:3px solid #a6c5ff;outline-offset:2px}button,.button{border:1px solid #d9e0eb;border-radius:8px;padding:9px 13px;background:white;color:#253247;text-decoration:none}h1{font-size:25px;line-height:1.35;margin:6px 0}h2{font-size:19px;margin:30px 0 12px}h3{font-size:16px;margin:0 0 7px}p{margin:6px 0 12px}small,.muted,.filename{color:#64748b}small{display:block}.layout{display:grid;grid-template-columns:310px minmax(0,1fr);min-height:100vh}aside{height:100vh;position:sticky;top:0;background:white;border-right:1px solid #dde4ee;display:flex;flex-direction:column}.sidebar-head{padding:21px 17px 12px;border-bottom:1px solid #e7edf4}.sidebar-head h2{margin:0 0 12px}.search{width:100%;border:1px solid #cbd5e1;padding:11px;border-radius:8px}.filters{display:flex;gap:6px;margin:9px 0}.filters select{width:50%;min-width:0;font-size:13px}.site-list{overflow:auto;padding:8px 10px;flex:1}.site-link{width:100%;display:block;text-align:left;border:1px solid transparent;margin:4px 0;padding:12px;background:white}.site-link.active{background:#edf4ff;border-color:#abc9ff;box-shadow:inset 3px 0 #3563e9}.site-top,.site-bottom{display:flex;align-items:center;justify-content:space-between;gap:8px}.site-title{display:block;font-weight:650;line-height:1.4;margin:6px 0}.site-link small{font-size:11px;overflow-wrap:anywhere}.site-bottom{margin-top:8px;font-size:12px;color:#596b80}.grade{display:inline-block;border-radius:6px;padding:3px 9px;font-size:12px;font-weight:750;white-space:nowrap}.Low{background:#e7f5ee;color:#20704a}.Medium{background:#fff1cf;color:#855905}.High{background:#eee8ff;color:#6943a8}.pill{display:inline-block;border-radius:5px;padding:2px 7px;background:#eef2f7}.red{color:#b83b37;background:#fff0ee}.green{color:#20704a;background:#e7f5ee}main{padding:22px 30px;min-width:0}.toolbar{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:24px}.save-state{color:#28724c;font-size:13px}.save-state.error{color:#bb3535}.toolbar-buttons{display:flex;gap:7px}.view[hidden],[hidden]{display:none!important}.page-heading{display:flex;align-items:center;justify-content:space-between;gap:18px}.filename{font-size:12px;overflow-wrap:anywhere}.primary{background:#3563e9;color:white;border-color:#3563e9;white-space:nowrap}.site-controls{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;margin:18px 0}select{background:white;border:1px solid #cbd5e1;padding:8px;border-radius:7px}.grade-card{background:white;border:1px solid #e0e6ef;border-radius:12px;padding:18px;display:flex;gap:15px;align-items:flex-start}.grade-card .grade{font-size:16px}.grade-card p{margin:4px 0}.grade-card small{font-size:12px}.count{font-size:13px;color:#6b7a90;font-weight:500}.issue-card{background:#fff5f2;border:1px solid #f2c7bd;border-radius:10px;padding:17px;margin:12px 0}.issue-card strong{color:#a2392a}.issue-card p{font-size:14px}.empty-ok{background:#edf6f0;border:1px solid #cde4d5;padding:17px;border-radius:10px;color:#2a6440}.task-card{background:white;border:1px solid #dfe6f0;border-radius:12px;padding:20px;margin:12px 0;display:grid;grid-template-columns:minmax(0,1fr) 145px;gap:14px}.task-card p{color:#5c6d83;font-size:14px;margin:0}.result-label{font-size:12px;color:#66768b}.result-label select{display:block;width:100%;margin-top:5px}.task-card textarea{grid-column:1/-1;min-height:58px}textarea{width:100%;border:1px solid #d8e0ea;border-radius:8px;padding:11px;resize:vertical;min-height:85px}.overall-note{display:block;margin:24px 0;font-weight:650}.overall-note textarea{margin-top:8px;font-weight:400}.technical{margin:28px 0;color:#66778e}.technical summary{cursor:pointer}.table-scroll{overflow:auto}table{width:100%;border-collapse:collapse;background:white}th,td{text-align:left;vertical-align:top;padding:13px;border-bottom:1px solid #e5ebf3}th{font-size:13px;color:#68788e;background:#f1f4f8}td{font-size:14px}td small{font-size:11px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}.text-button{border:0;background:none;text-align:left;padding:0;color:#285bbb;font-weight:650}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:20px 0}.stat{background:white;border:1px solid #dfe6f0;border-radius:10px;padding:16px}.stat b{display:block;font-size:26px}.stat span{font-size:13px;color:#64748b}.help{background:#eaf1ff;padding:16px;border-radius:10px;color:#3f5c87}.help p{margin:0}.footnote{font-size:12px;color:#718196;margin-top:24px}.nav-overview{width:100%;margin-bottom:10px;font-weight:650}.empty-list{padding:16px;color:#64748b;font-size:13px}@media(min-width:1500px){main{padding:28px 45px}.site-panel{max-width:1200px;margin:auto}}@media(max-width:850px){.layout{grid-template-columns:250px minmax(0,1fr)}main{padding:18px}.task-card{grid-template-columns:1fr}.task-card textarea{grid-column:auto}.page-heading{align-items:flex-start;flex-direction:column}.stats{grid-template-columns:repeat(2,1fr)}}@media(max-width:600px){.layout{display:block}aside{height:320px;position:relative}.sidebar-head{padding:10px}.site-list{min-height:90px}.toolbar{margin-top:12px}h1{font-size:21px}.stats{gap:6px}}@media print{aside,.toolbar,.button{display:none}.layout{display:block}main{padding:0}.view[hidden]{display:block!important}.site-panel{break-before:page}.technical{display:none}}
</style></head><body><div class="layout"><aside><div class="sidebar-head"><h2>홈페이지 검수</h2><button class="nav-overview" onclick="showSite('overview')">전체 결과 보기</button><input id="search" class="search" type="search" placeholder="번호·사이트 이름으로 검색" aria-label="사이트 검색"><div class="filters"><select id="status-filter" aria-label="검수 상태 필터"><option value="all">모든 상태</option><option value="issue">문제 있음</option><option value="pending">미검수·진행 중</option><option value="done">검수 완료</option></select><select id="grade-filter" aria-label="난이도 필터"><option value="all">모든 Grade</option><option>Low</option><option>Medium</option><option>High</option></select></div><small id="list-count"></small></div><nav class="site-list" aria-label="사이트 목록">__NAV__<div id="empty-list" class="empty-list" hidden>조건에 맞는 사이트가 없어요.</div></nav></aside><main><div class="toolbar"><span id="save-state" class="save-state" role="status" aria-live="polite">저장 상태 확인 중</span><div class="toolbar-buttons"><button onclick="exportReview()">기록 백업</button><button onclick="document.getElementById('import').click()">기록 불러오기</button><input id="import" type="file" accept="application/json" hidden></div></div>
<section class="view" id="overview"><h1>어떤 사이트를 확인하면 될까요?</h1><p class="muted">번호나 이름을 검색하고, 왼쪽에서 사이트를 선택하세요.</p><div class="stats"><div class="stat"><b id="stat-total"></b><span>전체 사이트</span></div><div class="stat"><b id="stat-issues"></b><span>문제가 있는 사이트</span></div><div class="stat"><b id="stat-pending"></b><span>아직 검수 중</span></div><div class="stat"><b id="stat-done"></b><span>검수 완료</span></div></div><div class="help"><p><b>① 사이트 선택 → ② 발견한 문제 확인 → ③ 원본 사이트에서 직접 클릭 → ④ 결과 선택</b><br>선택한 결과와 메모는 이 브라우저에 자동 저장돼요. 다른 PC로 옮길 때는 ‘기록 백업’을 눌러주세요.</p></div><h2>사이트별 결과</h2><div class="table-scroll"><table><thead><tr><th>사이트</th><th>기능 난이도</th><th>자동 발견 문제</th><th>수동 검수</th></tr></thead><tbody>__ROWS__</tbody></table></div><details class="technical"><summary>검사 범위와 실행 정보</summary><p>__NOTE__</p><p>파일을 읽지 못한 사이트: __FAILURES__개. inspection.json에 상세 기록이 있습니다.</p><p>자동 검사는 파일 연결과 초기 로딩을 확인합니다. 클릭 후 결과와 이미지 권리 상태는 사람이 확인해야 해요. Grade는 구현 복잡도이며 완성도 점수가 아니에요.</p></details></section>
__PANELS__<p class="footnote">원본 홈페이지는 수정하지 않아요. 브라우저 저장 기록은 파일 이동·브라우저 데이터 삭제 시 사라질 수 있으니 작업 후 기록을 백업하세요.</p></main></div><script>
const original=__DATA__;
const prefix='html-inspector:'+original.root+':';
const byId=id=>document.getElementById(id);
let active='overview';
function savedValue(key){const el=[...document.querySelectorAll('[data-save]')].find(x=>x.dataset.save===key);return el?el.value:'';}
function siteState(i){const p=original.sites[i],panel=byId('site'+i),tasks=[...panel.querySelectorAll('[data-review]')];const done=tasks.filter(x=>x.value!=='미검수').length;const issue=p.checks.some(x=>x.status==='불일치')||[...panel.querySelectorAll('select[data-save]')].some(x=>x.value==='오류');const state=panel.querySelector('[data-site-status]').value;return{done,total:tasks.length,issue,state};}
function updateSummary(){let issues=0,done=0;original.sites.forEach((p,i)=>{const s=siteState(i);if(s.issue||s.state==='수정 필요')issues++;if(s.state==='검수 완료')done++;byId('nav-state'+i).replaceChildren();const status=document.createElement('span');status.className='pill '+(s.state==='검수 완료'?'green':s.issue?'red':'');status.textContent=s.state;const info=document.createElement('span');info.textContent=(s.issue?'문제 있음 · ':'')+s.done+'/'+s.total+' 확인';byId('nav-state'+i).append(status,info);byId('summary-state'+i).textContent=s.state+' · '+s.done+'/'+s.total;byId('task-progress'+i).textContent='직접 확인 '+s.done+' / '+s.total+'개';});byId('stat-total').textContent=original.sites.length;byId('stat-issues').textContent=issues;byId('stat-done').textContent=done;byId('stat-pending').textContent=original.sites.length-done;filterSites();}
function filterSites(){const q=byId('search').value.trim().toLocaleLowerCase(),status=byId('status-filter').value,grade=byId('grade-filter').value;let visible=0;original.sites.forEach((p,i)=>{const s=siteState(i),match=(!q||(p.file+' '+p.title).toLocaleLowerCase().includes(q))&&(grade==='all'||p.grade===grade)&&(status==='all'||status==='issue'&&(s.issue||s.state==='수정 필요')||status==='done'&&s.state==='검수 완료'||status==='pending'&&s.state!=='검수 완료');document.querySelector('.site-link[data-index="'+i+'"]').hidden=!match;document.querySelector('.summary-row[data-index="'+i+'"]').hidden=!match;if(match)visible++;});byId('list-count').textContent=visible+' / '+original.sites.length+'개 사이트';byId('empty-list').hidden=visible!==0;}
function showSite(index){let id=index==='overview'?'overview':'site'+index;if(!byId(id))id='overview';active=id;document.querySelectorAll('.view').forEach(el=>el.hidden=el.id!==id);document.querySelectorAll('.site-link').forEach(el=>{const selected='site'+el.dataset.index===id;el.classList.toggle('active',selected);if(selected)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});try{localStorage.setItem(prefix+'active-view',id);}catch{}history.replaceState(null,'','#'+id);window.scrollTo({top:0});}
function persist(el){let siteStatus=null;if(el.dataset.review!==undefined){const panel=byId('site'+el.dataset.review);siteStatus=panel.querySelector('[data-site-status]');siteStatus.value=[...panel.querySelectorAll('[data-review]')].some(x=>x.value==='오류')?'수정 필요':'검수 중';}try{localStorage.setItem(prefix+el.dataset.save,el.value);if(siteStatus)localStorage.setItem(prefix+siteStatus.dataset.save,siteStatus.value);byId('save-state').classList.remove('error');byId('save-state').textContent='자동 저장됨 · '+new Date().toLocaleTimeString();}catch{byId('save-state').classList.add('error');byId('save-state').textContent='자동 저장 실패 · 기록 백업을 눌러주세요';}updateSummary();}
try{localStorage.setItem(prefix+'storage-test','ok');localStorage.removeItem(prefix+'storage-test');byId('save-state').textContent='이 브라우저에 자동 저장돼요';}catch{byId('save-state').classList.add('error');byId('save-state').textContent='자동 저장 사용 불가 · 기록 백업으로 저장하세요';}
document.querySelectorAll('[data-save]').forEach(el=>{try{const value=localStorage.getItem(prefix+el.dataset.save);if(value!==null){if(el.tagName!=='SELECT'||[...el.options].some(o=>o.value===value))el.value=value;}}catch{}el.addEventListener('input',()=>persist(el));el.addEventListener('change',()=>persist(el));});
['search','status-filter','grade-filter'].forEach(id=>byId(id).addEventListener('input',filterSites));
function exportReview(){const manual={};document.querySelectorAll('[data-save]').forEach(el=>manual[el.dataset.save]=el.value);const blob=new Blob([JSON.stringify({inspection:original,manual},null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='review-record.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
byId('import').onchange=async event=>{try{const file=event.target.files[0];if(!file)return;const saved=JSON.parse(await file.text());if(!saved.manual||typeof saved.manual!=='object')throw Error();if(saved.inspection?.root!==original.root&&!confirm('다른 폴더에서 만든 기록입니다. 불러올까요?'))return;document.querySelectorAll('[data-save]').forEach(el=>{if(Object.hasOwn(saved.manual,el.dataset.save)){const value=saved.manual[el.dataset.save];if(typeof value==='string'&&(el.tagName!=='SELECT'||[...el.options].some(o=>o.value===value))){el.value=value;try{localStorage.setItem(prefix+el.dataset.save,value);}catch{}}}});updateSummary();byId('save-state').textContent='기록을 불러왔어요. 자동 저장이 안 되는 환경에서는 다시 백업하세요.';}catch{alert('검수 기록 파일을 읽을 수 없어요. 기록 백업으로 받은 JSON을 선택하세요.');}};
updateSummary();let start=location.hash.slice(1);try{start=start||localStorage.getItem(prefix+'active-view');}catch{}showSite(start&&/^site[0-9]+$/.test(start)?Number(start.slice(4)):'overview');
</script></body></html>'''
    return (template.replace('__NAV__', ''.join(nav)).replace('__ROWS__', ''.join(overview))
            .replace('__NOTE__', e(data['browser_note'])).replace('__FAILURES__', str(len(data['read_failures'])))
            .replace('__PANELS__', ''.join(panels)).replace('__DATA__', payload))


def main():
    ap = argparse.ArgumentParser(description='HTML 폴더 검사 및 수동 검수표 생성')
    ap.add_argument('folder', nargs='?')
    ap.add_argument('--out', default='inspection-result', help='결과 저장 폴더')
    ap.add_argument('--browser', action='store_true', help='선택: Chromium 초기 로딩 검사')
    ap.add_argument('--image-review', action='store_true', help='모든 img에 인물·모델 교체 확인 항목 추가')
    ap.add_argument('--refresh-report', metavar='JSON', help='기존 inspection.json으로 화면만 새로 생성 (브라우저 재검사 없음)')
    args = ap.parse_args()
    if args.refresh_report:
        existing = Path(args.refresh_report).resolve()
        data = json.loads(existing.read_text(encoding='utf-8'))
        for site in progress(data['sites'], 'Grade 분석·화면 갱신', lambda item: item['file']):
            original_path = Path(data['root']) / site['file']
            try:
                source = original_path.read_text(encoding='utf-8-sig', errors='replace')
                parsed = PageParser()
                parsed.feed(source)
                grade_data = estimate_grade(source, parsed)
                site['source_changed'] = site.get('source_changed', False) or bool(site.get('source_hash') and site['source_hash'] != grade_data['source_hash'])
                site.update(grade_data, source_uri=original_path.as_uri())
                # 기존 검사의 통과·불일치와 브라우저 오류 기록은 유지한다.
                current = inspect_file(original_path, Path(data['root']), args.image_review)
                # 동일 항목의 순서·결과가 일치할 때만 사람이 읽는 이름을 바꾼다.
                for old, new in zip(site['checks'], current['checks']):
                    if old['detail'] == new['detail'] and old['status'] == new['status']:
                        old['item'] = new['item']
            except (OSError, ValueError) as error:
                site['grade_method'] = '원본을 읽지 못해 기존 판정 유지'
                print(f'원본 읽기 실패: {site["file"]}: {error}', flush=True)
        (existing.parent / 'report.html').write_text(render(data), encoding='utf-8')
        existing.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'화면 갱신 완료: {existing.parent / "report.html"}', flush=True)
        return
    if not args.folder:
        import tkinter as tk
        from tkinter import filedialog
        app = tk.Tk()
        app.withdraw()
        args.folder = filedialog.askdirectory(title='검사할 HTML 폴더 선택')
        app.destroy()
        if not args.folder:
            return
    root = Path(args.folder).resolve()
    if not root.is_dir():
        ap.error('검사 폴더가 없습니다.')
    out = Path(args.out).resolve()
    print(f'HTML 파일 목록 수집 중: {root}', flush=True)
    paths = collect_html(root, out)
    print('제외: history 폴더(하위 전체, 대소문자 무시), 결과 저장 폴더', flush=True)
    print(f'검사 대상: {len(paths)}개', flush=True)
    pages, failures = [], []
    for path in progress(paths, '1. HTML 검사', lambda item: str(item.relative_to(root))):
        try:
            pages.append(inspect_file(path, root, args.image_review))
        except Exception as error:
            failures.append(dict(file=str(path), error=str(error)))
    note = browser_checks(pages, root) if args.browser else '브라우저 검사 미실행。--browser 옵션으로 초기 로딩 검사를 추가할 수 있습니다.'
    print(note, flush=True)
    data = dict(root=str(root), browser_note=note, sites=pages, read_failures=failures)
    print('검수표 HTML/JSON 저장 중...', flush=True)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'inspection.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'report.html').write_text(render(data), encoding='utf-8')
    print(f'검사 {len(pages)}개 / 읽기 실패 {len(failures)}개')
    print(out / 'report.html')
    if failures:
        print('읽기 실패 파일은 inspection.json의 read_failures를 확인하세요.')


if __name__ == '__main__':
    main()
