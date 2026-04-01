"""
wild_crawling.py
================
Pilot Study 2: Wild Web UI 수집 및 정적 모의 환경(Static Mock Environment) 구축 스크립트

목표:
  - Trip.com 메인 페이지를 크롤링하여 에이전트의 시작점(home.html) 생성
  - Flights 탭 → 출발/도착 입력 → Search 버튼이 flight_list.html로 정적 링크
  - 상위 10개 항공편의 리스트 페이지 + 상세 페이지(팝업) HTML을 수집
  - BeautifulSoup으로 노이즈 제거 (Context Diet) 후 로컬 file:/// 경로로 연결되는
    정적 HTML 파일 12개(홈 1 + 리스트 1 + 상세 10개)를 mock_env/ 폴더에 저장

에이전트 탐색 흐름:
  home.html  →(Search 클릭)→  flight_list.html  →(Select 클릭)→  flight_detail_N.html
                                                 ←(← 목록으로)←

연구 배경 (project_proposal.md Pilot Study 2):
  'wild'한 웹 데이터 환경에서 DOM과 IMG 모달리티를 분리하여 에이전트의 편향성과
  정보 처리 능력을 테스트하고, UI가 에이전트 성능에 미치는 영향을 분석.

설치:
  pip install playwright beautifulsoup4 lxml
  playwright install chromium
"""

import asyncio
import re
import json
from pathlib import Path
from datetime import datetime, timedelta

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup, Comment

# ──────────────────────────────────────────────────────────────────────────────
# 설정값 (CHANGE: 아래 값들을 필요에 따라 수정)
# ──────────────────────────────────────────────────────────────────────────────

# 출발일: 오늘로부터 7일 후 (YYYYMMDD 형식)
# TODO: may edit
_depart_date = (datetime.now() + timedelta(days=7)).strftime("%Y%m%d")

# Trip.com 메인 홈페이지 URL
TRIP_HOME_URL = "https://www.trip.com/"

# Trip.com 제주(CJU) → 서울(GMP) 편도 검색 URL
TRIP_SEARCH_URL = (
    f"https://www.trip.com/flights/jeju-to-seoul/tickets-cju-gmp/"
    f"?dcity=cju&acity=gmp&ddate={_depart_date}&triptype=ow&class=y&quantity=1"
)

# 출력 폴더
OUTPUT_DIR = Path(__file__).parent / "mock_env"
RAW_DIR    = OUTPUT_DIR / "raw"   # 원본(가공 전) HTML 저장 위치

# 수집할 항공편 수
N_FLIGHTS = 10

# 브라우저 뷰포트 크기
VIEWPORT = {"width": 1440, "height": 900}

# ── 검증된 셀렉터 (2026-03-31 Trip.com 실제 DOM 확인) ──────────────────────

# [홈 페이지 셀렉터]
# 팝업 닫기 버튼 (언어 제안/앱 설치 배너)
SEL_POPUP_CLOSE   = ".close-icon, [class*='close-icon'], button.close, .dismiss-btn"
# Flights 탭
SEL_FLIGHTS_TAB   = "li.mc-srh-box__tab-item"
# One-way 라디오
SEL_ONEWAY        = "label:has-text('One-way')"
# 출발지 입력
SEL_FROM_INPUT    = "input[placeholder='Leaving from']"
# 도착지 입력
SEL_TO_INPUT      = "input[placeholder='Going to']"
# 자동완성 첫 번째 항목
SEL_AUTOCOMPLETE  = "[class*='suggest'] li:first-child, [class*='autoComplete'] li:first-child, [role='option']:first-child"
# Search 버튼
SEL_SEARCH_BTN    = "button:has-text('Search'), .nh_sp-btn2"

# [검색 결과 페이지 셀렉터]
# 항공편 리스트 로딩 완료 판단 기준
SEL_FLIGHT_LOADED = ".result-item.J_FlightItem"

# 개별 항공편 카드
SEL_FLIGHT_CARD   = ".result-item.J_FlightItem"

# 상세보기(Select) 버튼 - 각 카드 내부
SEL_SELECT_BTN    = "button.c-result-operate__btn"

# 상세 모달 컨테이너
SEL_DETAIL_MODAL  = ".flt-page-modal"

# 닫기 버튼 (모달 우상단 × 아이콘)
SEL_CLOSE_BTN     = "i[aria-label='Close']"


# ──────────────────────────────────────────────────────────────────────────────
# Step 0: 홈 페이지 수집 (Playwright)
# ──────────────────────────────────────────────────────────────────────────────

async def collect_home_raw_html(playwright) -> str:
    """
    Trip.com 메인 홈 페이지를 크롤링한다.
    Flights 탭을 클릭하고, 출발지(Jeju)·도착지(Seoul/Gimpo)를 입력한 상태에서
    HTML을 덤프한다. Search 버튼은 이후 rewrite_home_page()에서 정적 링크로 교체된다.

    Returns:
        원본 HTML 문자열
    """
    print("\n" + "="*60)
    print("  STEP 0: 홈 페이지 수집 (Playwright)")
    print("="*60)

    browser = await playwright.chromium.launch(
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    context = await browser.new_context(
        viewport=VIEWPORT,
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="en-US",          # en-US로 설정 → kr.trip.com 리다이렉트 방지
        timezone_id="America/New_York",  # 타임존도 미국으로 설정
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",  # 한국어 감지 차단
        },
    )
    page = await context.new_page()

    # ── kr.trip.com 리다이렉트 차단: 요청 URL을 www.trip.com으로 강제 교체 ────
    async def block_kr_redirect_home(route, request):
        url = request.url
        if "kr.trip.com" in url or "trip.com/?locale=ko" in url:
            new_url = url.replace("kr.trip.com", "www.trip.com")
            new_url = new_url.replace("locale=ko-kr", "locale=en-US")
            new_url = new_url.replace("locale=ko", "locale=en-US")
            print(f"    🔀 리다이렉트 차단: {url[:80]}")
            await route.continue_(url=new_url)
        else:
            await route.continue_()
    await page.route("**/*", block_kr_redirect_home)

    # ── 0-1. 홈 페이지 접속 ──────────────────────────────────────────────────
    print(f"\n🌐 접속 중: {TRIP_HOME_URL}")
    try:
        await page.goto(TRIP_HOME_URL, timeout=60_000, wait_until="domcontentloaded")
    except PlaywrightTimeoutError:
        print("⚠️  페이지 이동 타임아웃. 현재 상태로 계속 진행합니다.")

    # 리다이렉트 후 실제 URL 확인 → kr.trip.com이면 강제로 www로 재탐색
    current_url = page.url
    if "kr.trip.com" in current_url or "locale=ko" in current_url:
        forced_url = "https://www.trip.com/?locale=en-US"
        print(f"  🔀 kr.trip.com 감지 → 강제 우회: {forced_url}")
        try:
            await page.goto(forced_url, timeout=60_000, wait_until="domcontentloaded")
        except PlaywrightTimeoutError:
            pass

    print(f"  📍 현재 URL: {page.url}")
    await page.wait_for_timeout(3_000)

    # ── 0-2. 팝업 닫기 (언어 제안, 앱 설치 배너 등) ─────────────────────────
    print("  🔕 팝업 닫기 시도...")
    popup_selectors = [
        ".close-icon",
        "[class*='close-icon']",
        "button[aria-label='Close']",
        ".mc-modal-close",
        ".dismiss",
    ]
    for sel in popup_selectors:
        try:
            popup = page.locator(sel).first
            if await popup.count() > 0 and await popup.is_visible():
                await popup.click(timeout=2_000)
                print(f"    ✅ 팝업 닫힘: '{sel}'")
                await page.wait_for_timeout(500)
        except Exception:
            pass

    # ── 0-3. Flights 탭 클릭 ────────────────────────────────────────────────
    print("  ✈️  Flights 탭 클릭 중...")
    flights_tab = page.locator(SEL_FLIGHTS_TAB).filter(has_text="Flights").first
    try:
        await flights_tab.click(timeout=10_000)
        print("    ✅ Flights 탭 선택 완료")
        await page.wait_for_timeout(1_500)
    except Exception as e:
        print(f"    ⚠️  Flights 탭 클릭 실패: {e}")

    # ── 0-4. One-way 선택 ─────────────────────────────────────────────────────
    print("  🔘 One-way 선택 중...")
    try:
        # 'One-way' 텍스트가 포함된 label 또는 라디오 버튼 클릭
        oneway = page.locator("label, div, span").filter(has_text="One-way").first
        await oneway.click(timeout=5_000)
        print("    ✅ One-way 선택 완료")
        await page.wait_for_timeout(800)
    except Exception as e:
        print(f"    ⚠️  One-way 선택 실패: {e}")

    # ── 0-5. 출발지 입력: Jeju (CJU) ─────────────────────────────────────────
    # 드롭다운 셀렉터: Trip.com은 #m-flight-poi-list 안에 자동완성 항목을 렌더링함
    AUTOCOMPLETE_LIST = "#m-flight-poi-list"
    AUTOCOMPLETE_ITEM = "#m-flight-poi-list li"

    print("  🛫 출발지 입력: Jeju...")
    try:
        from_input = page.locator(SEL_FROM_INPUT).first
        await from_input.click(timeout=5_000)
        await page.wait_for_timeout(300)
        await from_input.fill("Jeju", timeout=5_000)

        # 자동완성 드롭다운이 나타날 때까지 대기
        try:
            await page.wait_for_selector(AUTOCOMPLETE_ITEM, timeout=4_000)
        except PlaywrightTimeoutError:
            pass

        # 드롭다운 첫 번째 항목 클릭 (Jeju 관련)
        items = page.locator(AUTOCOMPLETE_ITEM)
        if await items.count() > 0:
            await items.first.click(timeout=5_000)
            print("    ✅ Jeju 자동완성 첫 번째 항목 선택")
        else:
            await from_input.press("Enter")
            print("    ✅ Jeju 입력 후 Enter")

        # 드롭다운이 완전히 닫힐 때까지 대기 (다음 필드 클릭 전)
        try:
            await page.wait_for_selector(AUTOCOMPLETE_LIST, timeout=3_000, state="hidden")
        except PlaywrightTimeoutError:
            # 닫히지 않으면 Escape로 강제 닫기
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)
        print("    ✅ 출발지 드롭다운 닫힘 확인")
    except Exception as e:
        print(f"    ⚠️  출발지 입력 실패: {e}")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)

    # ── 0-6. 도착지 입력: Seoul Gimpo (GMP) ───────────────────────────────────
    print("  🛬 도착지 입력: Seoul Gimpo (GMP)...")
    try:
        # 출발지 드롭다운이 완전히 사라진 것을 확인한 후 클릭
        await page.wait_for_selector(AUTOCOMPLETE_LIST, timeout=2_000, state="hidden")
    except PlaywrightTimeoutError:
        await page.wait_for_timeout(500)

    try:
        to_input = page.locator(SEL_TO_INPUT).first
        # force=True: 위를 덮는 요소가 있어도 강제 클릭
        await to_input.click(timeout=5_000, force=True)
        await page.wait_for_timeout(300)
        await to_input.fill("Gimpo", timeout=5_000)

        # 자동완성 드롭다운이 나타날 때까지 대기
        try:
            await page.wait_for_selector(AUTOCOMPLETE_ITEM, timeout=4_000)
        except PlaywrightTimeoutError:
            pass

        # 드롭다운 항목 중 'Gimpo' 포함 항목 선택
        items = page.locator(AUTOCOMPLETE_ITEM)
        count = await items.count()
        clicked = False
        for idx in range(count):
            item = items.nth(idx)
            text = await item.inner_text()
            if "Gimpo" in text or "GMP" in text:
                await item.click(timeout=5_000)
                print(f"    ✅ '{text.strip()[:40]}' 선택")
                clicked = True
                break
        if not clicked:
            if count > 0:
                await items.first.click(timeout=5_000)
                print("    ✅ 도착지 자동완성 첫 번째 항목 선택")
            else:
                await to_input.press("Enter")
                print("    ✅ Gimpo 입력 후 Enter")

        # 드롭다운 닫힘 대기
        try:
            await page.wait_for_selector(AUTOCOMPLETE_LIST, timeout=3_000, state="hidden")
        except PlaywrightTimeoutError:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)
        print("    ✅ 도착지 드롭다운 닫힘 확인")
    except Exception as e:
        print(f"    ⚠️  도착지 입력 실패: {e}")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)

    # ── 0-7. 날짜 입력은 생략 (현재 폼 상태 그대로 덤프) ──────────────────────
    # 날짜 필드는 에이전트가 직접 선택하는 태스크로 남겨둠
    # (날짜 피커를 닫아서 폼의 나머지 부분이 보이도록 대기)
    await page.wait_for_timeout(1_000)

    # ── 0-8. 현재 페이지 HTML 덤프 ──────────────────────────────────────────
    home_html = await page.content()
    print(f"  📄 홈 페이지 HTML 수집 완료 ({len(home_html):,} bytes)")

    await browser.close()
    return home_html


# ──────────────────────────────────────────────────────────────────────────────
# Step 1: 검색 결과 + 상세 데이터 수집 (Playwright)
# ──────────────────────────────────────────────────────────────────────────────

async def collect_raw_html(playwright) -> dict:
    """
    Playwright로 Trip.com 검색 결과에서 원본 HTML을 수집한다.

    Returns:
        {
          "list_html"    : str,          # 검색 결과 리스트 전체 HTML
          "detail_htmls" : [str, ...]    # 각 항공편 상세 모달 HTML (최대 N_FLIGHTS개)
        }
    """
    print("\n" + "="*60)
    print("  STEP 1: 데이터 수집 (Playwright)")
    print("="*60)

    browser = await playwright.chromium.launch(
        headless=False,   # True로 변경하면 화면 없이 실행
        args=[
            "--disable-blink-features=AutomationControlled",  # 봇 탐지 우회
            "--no-sandbox",
        ],
    )
    context = await browser.new_context(
        viewport=VIEWPORT,
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="en-US",          # en-US로 설정 → kr.trip.com 리다이렉트 방지
        timezone_id="America/New_York",
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    page = await context.new_page()

    # ── kr.trip.com 리다이렉트 차단: 요청 URL을 www.trip.com으로 강제 교체 ────
    async def block_kr_redirect_search(route, request):
        url = request.url
        if "kr.trip.com" in url or "trip.com/?locale=ko" in url:
            new_url = url.replace("kr.trip.com", "www.trip.com")
            new_url = new_url.replace("locale=ko-kr", "locale=en-US")
            new_url = new_url.replace("locale=ko", "locale=en-US")
            print(f"    🔀 리다이렉트 차단: {url[:60]}")
            await route.continue_(url=new_url)
        else:
            await route.continue_()
    await page.route("**/*", block_kr_redirect_search)

    # ── 1-1. 검색 결과 페이지 접속 ──────────────────────────────────────────
    print(f"\n🌐 접속 중: {TRIP_SEARCH_URL}")
    try:
        await page.goto(TRIP_SEARCH_URL, timeout=60_000, wait_until="domcontentloaded")
    except PlaywrightTimeoutError:
        print("⚠️  페이지 이동 타임아웃. 현재 상태로 계속 진행합니다.")

    # 리다이렉트 후 실제 URL 확인 → kr.trip.com이면 강제로 www로 재탐색
    current_url = page.url
    if "kr.trip.com" in current_url or "locale=ko" in current_url:
        forced_url = TRIP_SEARCH_URL + "&locale=en-US"
        print(f"  🔀 kr.trip.com 감지 → 강제 우회: {forced_url[:80]}")
        try:
            await page.goto(forced_url, timeout=60_000, wait_until="domcontentloaded")
        except PlaywrightTimeoutError:
            pass

    print(f"  📍 현재 URL: {page.url[:80]}")

    # ── 1-2. 항공편 리스트 로딩 대기 ─────────────────────────────────────────
    print(f"⏳ 항공편 카드 로딩 대기 중 (셀렉터: '{SEL_FLIGHT_LOADED}')...")
    try:
        await page.wait_for_selector(SEL_FLIGHT_LOADED, timeout=30_000)
        print("  ✅ 항공편 카드 로딩 확인")
    except PlaywrightTimeoutError:
        print("  ⚠️  카드 셀렉터 타임아웃. 5초 추가 대기 후 계속합니다.")
        await page.wait_for_timeout(5_000)

    # 동적 렌더링 완료 대기
    # (Trip.com은 로딩 바가 사라진 후에도 순차적으로 카드가 채워지는 경우가 있음)
    print("  ⏳ 동적 렌더링 완료 대기 (5초)...")
    await page.wait_for_timeout(5_000)

    # ── 1-3. 리스트 HTML 덤프 ────────────────────────────────────────────────
    list_html = await page.content()
    card_count = await page.locator(SEL_FLIGHT_CARD).count()
    print(f"  📄 리스트 HTML 수집 완료 ({len(list_html):,} bytes, 카드 {card_count}개 감지)")

    if card_count == 0:
        print("  ❌ 항공편 카드를 찾지 못했습니다. 스크립트를 종료합니다.")
        await browser.close()
        return {"list_html": list_html, "detail_htmls": []}

    # ── 1-4. 상위 N_FLIGHTS개 항공편 상세 모달 HTML 수집 ─────────────────────
    detail_htmls = []
    n_to_collect = min(N_FLIGHTS, card_count)

    for i in range(n_to_collect):
        print(f"\n  🔍 항공편 #{i+1}/{n_to_collect} 상세 모달 수집 중...")

        # 카드 재참조 (이전 클릭으로 DOM이 갱신될 수 있으므로 매번 새로 조회)
        cards = page.locator(SEL_FLIGHT_CARD)

        # 현재 카드가 뷰포트에 오도록 스크롤
        card = cards.nth(i)
        await card.scroll_into_view_if_needed()
        await page.wait_for_timeout(500)

        # Select 버튼 찾기 (카드 내부)
        select_btn = card.locator(SEL_SELECT_BTN).first
        if await select_btn.count() == 0:
            print(f"    ⚠️  Select 버튼을 찾지 못했습니다. 카드 자체를 클릭합니다.")
            select_btn = card

        # Select 버튼 클릭
        try:
            await select_btn.click(timeout=10_000)
            print(f"    ✅ Select 버튼 클릭 완료")
        except Exception as e:
            print(f"    ❌ 클릭 실패: {e}")
            detail_htmls.append("")
            continue

        # ── 상세 모달 로딩 대기 ──────────────────────────────────────────────
        try:
            await page.wait_for_selector(SEL_DETAIL_MODAL, timeout=15_000, state="visible")
            print(f"    ✅ 상세 모달 등장 확인: '{SEL_DETAIL_MODAL}'")
        except PlaywrightTimeoutError:
            print(f"    ⚠️  모달 셀렉터 타임아웃. 2초 대기 후 HTML 덤프합니다.")

        # 모달 내 콘텐츠 렌더링 완료 대기
        await page.wait_for_timeout(2_000)

        # 전체 페이지 HTML 덤프 (모달이 DOM에 overlay 형태로 존재)
        detail_html = await page.content()
        detail_htmls.append(detail_html)
        print(f"    📄 상세 HTML 수집 완료 ({len(detail_html):,} bytes)")

        # ── 모달 닫기 ────────────────────────────────────────────────────────
        try:
            close_btn = page.locator(SEL_CLOSE_BTN).first
            await close_btn.wait_for(timeout=5_000, state="visible")
            await close_btn.click(timeout=5_000)
            # 모달이 완전히 닫힐 때까지 대기
            await page.wait_for_selector(SEL_DETAIL_MODAL, timeout=5_000, state="hidden")
            print(f"    🔒 모달 닫힘 확인")
        except PlaywrightTimeoutError:
            # 닫기 실패 시 Escape 키로 대체
            await page.keyboard.press("Escape")
            print(f"    🔒 모달 닫기: Escape 키 사용")
            await page.wait_for_timeout(1_000)
        except Exception as e:
            print(f"    ⚠️  닫기 오류: {e}. Escape 시도.")
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(1_000)

        # 다음 카드 클릭 전 안정화 대기
        await page.wait_for_timeout(1_500)

    await browser.close()
    print(f"\n✅ 수집 완료: 리스트 1개 + 상세 {len(detail_htmls)}개")
    return {"list_html": list_html, "detail_htmls": detail_htmls}


# ──────────────────────────────────────────────────────────────────────────────
# Step 2: 데이터 가공 (Context Diet via BeautifulSoup)
# ──────────────────────────────────────────────────────────────────────────────

# 삭제할 HTML 태그 (에이전트에게 불필요한 노이즈 요소)
# ※ 'style'과 'link'는 CSS를 위해 유지 (screenshot 모달리티 지원)
REMOVE_TAGS = [
    "script", "iframe", "noscript", "svg",
    "canvas", "video", "audio", "source", "track",
    "meta",    # 대부분 에이전트 태스크에 무관
]

# 삭제할 class/id 키워드를 포함한 섹션 (광고, 푸터, 쿠키 배너 등)
REMOVE_SECTION_KEYWORDS = [
    "advertisement", "ad-banner", "ad-slot", "ads-",
    "footer", "site-footer", "page-footer",
    "cookie-banner", "cookie-notice", "gdpr",
    "newsletter", "subscribe-popup",
    "chat-widget", "live-chat",
    "social-share", "share-bar",
    "promotion", "promo-banner",
    "app-download", "app-banner",
]

# CSS를 유지하되 제거할 <link> rel 값 (stylesheet 외의 비CSS 링크)
REMOVE_LINK_RELS = {
    "preload", "prefetch", "preconnect", "dns-prefetch",
    "manifest", "canonical", "alternate", "amphtml",
    "shortcut icon", "apple-touch-icon",
}

TRIP_BASE_URL = "https://www.trip.com"


def _should_remove_section(tag) -> bool:
    """class나 id에 제거 키워드가 포함된 태그인지 확인한다."""
    if not hasattr(tag, 'attrs') or tag.attrs is None:
        return False
    for attr in ("class", "id"):
        val = tag.attrs.get(attr, "")
        if isinstance(val, list):
            val = " ".join(val)
        if val and any(kw in val.lower() for kw in REMOVE_SECTION_KEYWORDS):
            return True
    return False


def fix_css_urls(soup: BeautifulSoup) -> None:
    """
    로컬 파일로 서빙 시 CSS가 깨지지 않도록 URL을 절대경로로 변환한다.

    처리 내용:
      1. <link rel="stylesheet">의 href 중 '//'로 시작하는 것 → 'https://'
      2. <link rel="stylesheet">의 href 중 '/'로 시작하는 것 → TRIP_BASE_URL 앞에 붙이기
      3. 비CSS <link> 태그 (preload, prefetch 등) 제거 (노이즈 감소)
      4. <style> 태그 내부의 url() 참조도 절대경로로 변환
    """
    # ── link 태그 처리 ─────────────────────────────────────────────────────────
    for link_tag in soup.find_all("link"):
        rel = link_tag.get("rel", [])
        if isinstance(rel, list):
            rel = " ".join(rel).lower()
        else:
            rel = str(rel).lower()

        # stylesheet가 아닌 link 태그 제거 (preload, prefetch, icon 등)
        if "stylesheet" not in rel:
            # favicon은 남겨도 무방하나 노이즈 감소를 위해 제거
            link_tag.decompose()
            continue

        # stylesheet href URL 절대경로 변환
        href = link_tag.get("href", "")
        if href.startswith("//"):
            link_tag["href"] = "https:" + href
        elif href.startswith("/") and not href.startswith("//"):
            link_tag["href"] = TRIP_BASE_URL + href

    # ── <style> 내부 url() 참조 변환 ──────────────────────────────────────────
    for style_tag in soup.find_all("style"):
        if style_tag.string:
            css_text = style_tag.string
            # url(//...) → url(https://...)
            css_text = re.sub(r'url\((["\']?)//([^"\')]+)(["\']?)\)',
                              r'url(\1https://\2\3)', css_text)
            # url(/...) → url(https://www.trip.com/...)
            css_text = re.sub(r'url\((["\']?)/([^/"\')][^"\')]*?)(["\']?)\)',
                              rf'url(\1{TRIP_BASE_URL}/\2\3)', css_text)
            style_tag.string.replace_with(css_text)


def context_diet(raw_html: str, label: str = "") -> BeautifulSoup:
    """
    BeautifulSoup으로 HTML을 파싱하고 에이전트에게 불필요한 요소를 제거한다.

    Args:
        raw_html : 원본 HTML 문자열
        label    : 로깅용 레이블 (예: "list", "detail_1")

    Returns:
        가공된 BeautifulSoup 객체
    """
    soup = BeautifulSoup(raw_html, "lxml")

    for captcha_text in soup.find_all(string=re.compile(r"Too many attempts|verification|puzzle", re.I)):
        # 해당 문구를 포함한 가장 가까운 팝업/레이어(div)를 찾아 삭제
        target = captcha_text.find_parent("div", class_=re.compile(r"modal|mask|container|wrapper", re.I))
        if target:
            target.decompose()
            print(f"    ✨ [{label}] 가공 중 캡차 레이어 제거 완료")

    # 2. 화면을 가리는 오버레이(배경 어둡게 만드는 막) 제거
    for mask in soup.select('.modal-mask, .mask, [class*="captcha_"]'):
        mask.decompose()

    # 3. body에 걸린 스크롤 방지 해제 (팝업 때문에 스크롤이 안 될 수 있음)
    if soup.body and soup.body.has_attr("style"):
        soup.body["style"] = soup.body["style"].replace("overflow: hidden", "overflow: auto")
    # ── 2-1. 불필요 태그 전체 삭제 ────────────────────────────────────────────
    tag_count = {}
    for tag_name in REMOVE_TAGS:
        tags = soup.find_all(tag_name)
        tag_count[tag_name] = len(tags)
        for t in tags:
            t.decompose()

    # ── 2-2. 광고/푸터 등 섹션 삭제 ──────────────────────────────────────────
    section_removed = 0
    for tag in list(soup.find_all(True)):
        try:
            if _should_remove_section(tag):
                tag.decompose()
                section_removed += 1
        except Exception:
            continue

    # ── 2-3. HTML 주석 삭제 ───────────────────────────────────────────────────
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # ── 2-4. CSS URL 절대경로 변환 (screenshot 모달리티를 위해 CSS 유지) ───────
    #  protocol-relative(//...) 및 relative(/...) URL → https://www.trip.com/...
    fix_css_urls(soup)
    img_count = 0  # 이미지는 유지 (screenshot 모달리티 지원)

    # ── 2-5. 인라인 이벤트 핸들러 및 거대 data-* 속성 정리 ───────────────────
    inline_events = [
        "onclick", "onmouseover", "onmouseout", "onload",
        "onchange", "onsubmit", "onfocus", "onblur",
        "onkeydown", "onkeyup", "onkeypress",
    ]
    attr_removed = 0
    for tag in soup.find_all(True):
        for evt in inline_events:
            if tag.has_attr(evt):
                del tag[evt]
                attr_removed += 1
        # 200자 초과하는 data-* 속성 제거 (JSON 임베드 등)
        large_data = [a for a in list(tag.attrs)
                      if a.startswith("data-") and len(str(tag.get(a, ""))) > 200]
        for da in large_data:
            del tag[da]
            attr_removed += 1

    if label:
        removed_summary = {k: v for k, v in tag_count.items() if v > 0}
        css_link_count = len(soup.find_all("link", rel=re.compile("stylesheet", re.I)))
        print(f"  🧹 [{label}] Context Diet:")
        print(f"       태그 제거: {removed_summary}")
        print(f"       섹션 제거: {section_removed}개 | CSS 유지: {css_link_count}개 | 속성 제거: {attr_removed}개")

    return soup


# ──────────────────────────────────────────────────────────────────────────────
# Step 2-6: 정적 경로 치환 (Static Path Rewriting)
# ──────────────────────────────────────────────────────────────────────────────

def rewrite_list_page(soup: BeautifulSoup) -> str:
    """
    항공편 리스트 페이지에서 각 항공편 카드의 Select 버튼을
    로컬 파일 경로 ./flight_detail_{n}.html 로 연결되는 <a> 태그로 교체한다.

    Trip.com은 React SPA이므로 버튼에 href가 없다.
    → 버튼 요소를 <a href="..."> 로 래핑(wrap)하거나 교체한다.
    """
    print("\n  🔗 리스트 페이지 정적 링크 치환 중...")

    # 항공편 카드 탐색: class에 'J_FlightItem'을 포함하는 요소
    cards = soup.find_all(class_=re.compile(r"J_FlightItem"))[:N_FLIGHTS]

    if not cards:
        # Fallback: 'result-item' 클래스를 포함하는 모든 요소
        cards = soup.find_all(class_=re.compile(r"result-item"))[:N_FLIGHTS]

    if not cards:
        print("    ⚠️  카드를 찾지 못했습니다. 링크 치환 없이 저장합니다.")
        return str(soup)

    print(f"    발견된 카드: {len(cards)}개")

    for idx, card in enumerate(cards, start=1):
        detail_path = f"./flight_detail_{idx}.html"

        # Select 버튼 탐색: class에 'c-result-operate__btn'을 포함하는 <button>
        btn = card.find("button", class_=re.compile(r"c-result-operate__btn"))

        if btn:
            # 버튼을 <a href="..."> 로 교체 (내용은 유지)
            new_a = soup.new_tag("a", href=detail_path,
                                 style="display:inline-block;cursor:pointer;")
            new_a.string = btn.get_text(strip=True)
            btn.replace_with(new_a)
            print(f"    ✅ 항공편 #{idx}: Select 버튼 → <a href='{detail_path}'>")
        else:
            # 버튼을 찾지 못한 경우: 카드 끝에 링크 추가
            fallback = soup.new_tag("a", href=detail_path,
                                    style="display:block;margin-top:8px;font-weight:bold;")
            fallback.string = f"항공편 {idx} 상세보기"
            card.append(fallback)
            print(f"    ⚠️  항공편 #{idx}: 버튼 없음 → Fallback 링크 추가")

    return str(soup)


def rewrite_detail_page(soup: BeautifulSoup, flight_idx: int) -> str:
    """
    항공편 상세 모달 페이지에서 닫기 버튼(×)을 ./flight_list.html 로 연결하는
    <a> 태그로 교체하고, 리스트 복귀 링크를 상단에 추가한다.
    """
    list_path = "./flight_list.html"

    # 닫기 버튼 탐색: aria-label="Close" 인 <i> 태그
    close_btn = soup.find("i", attrs={"aria-label": "Close"})
    if close_btn:
        new_a = soup.new_tag("a", href=list_path,
                             style="display:inline-block;cursor:pointer;font-size:20px;")
        new_a.string = "✕ 닫기"
        close_btn.replace_with(new_a)
        print(f"    🔗 상세 #{flight_idx}: 닫기(×) 버튼 → <a href='{list_path}'>")
    else:
        print(f"    ⚠️  상세 #{flight_idx}: 닫기 버튼 없음, 상단 링크 추가")

    # body 최상단에 "목록으로 돌아가기" 링크 항상 삽입
    body = soup.find("body")
    if body:
        back_bar = soup.new_tag(
            "div",
            style="position:sticky;top:0;background:#fff;padding:8px 16px;"
                  "border-bottom:1px solid #eee;z-index:9999;",
        )
        back_link = soup.new_tag("a", href=list_path,
                                 style="font-weight:bold;text-decoration:none;color:#0066cc;")
        back_link.string = "← 항공편 목록으로 돌아가기"
        back_bar.append(back_link)
        body.insert(0, back_bar)

    return str(soup)


# ──────────────────────────────────────────────────────────────────────────────
# Step 3: 파일 저장
# ──────────────────────────────────────────────────────────────────────────────

def rewrite_home_page(soup: BeautifulSoup) -> str:
    """
    홈 페이지에서 Search 버튼의 클릭 동작을 ./flight_list.html로 이동하는
    정적 링크(<a href>)로 교체한다.

    Trip.com의 Search 버튼은 React 이벤트로만 작동하므로,
    버튼 요소 자체를 <a href="./flight_list.html"> 로 교체한다.
    """
    print("\n  🔗 홈 페이지 Search 버튼 정적 링크 치환 중...")

    list_path = "./flight_list.html"
    replaced = False

    # 후보 1: class에 'search' 관련 키워드를 포함하는 button 또는 div
    for tag_name in ["button", "div", "a", "span"]:
        candidates = soup.find_all(
            tag_name,
            class_=re.compile(r"search|sp-btn|srh-btn", re.I)
        )
        for el in candidates:
            text = el.get_text(strip=True).lower()
            if "search" in text:
                new_a = soup.new_tag(
                    "a", href=list_path,
                    style=(
                        "display:inline-flex;align-items:center;justify-content:center;"
                        "background:#0066cc;color:#fff;padding:12px 32px;"
                        "border-radius:4px;font-size:16px;font-weight:bold;"
                        "text-decoration:none;cursor:pointer;"
                    )
                )
                new_a.string = "🔍 Search"
                el.replace_with(new_a)
                replaced = True
                print(f"    ✅ Search 버튼(<{tag_name}> class='{el.get('class', '')}') → <a href='{list_path}'>")
                break
        if replaced:
            break

    # 후보 2: 텍스트가 정확히 'Search'인 모든 클릭 가능 요소
    if not replaced:
        for el in soup.find_all(["button", "div", "span", "a"]):
            if el.get_text(strip=True) == "Search":
                new_a = soup.new_tag("a", href=list_path,
                                     style="display:inline-block;background:#0066cc;color:#fff;"
                                            "padding:12px 24px;border-radius:4px;font-weight:bold;"
                                            "text-decoration:none;")
                new_a.string = "🔍 Search"
                el.replace_with(new_a)
                replaced = True
                print(f"    ✅ 텍스트 'Search' 요소 → <a href='{list_path}'>")
                break

    if not replaced:
        # Fallback: body 상단에 Search 링크 강제 삽입
        body = soup.find("body")
        if body:
            notice = soup.new_tag(
                "div",
                style="position:fixed;bottom:20px;right:20px;z-index:99999;"
                       "background:#0066cc;border-radius:8px;padding:4px;"
            )
            fallback_a = soup.new_tag(
                "a", href=list_path,
                style="display:block;color:#fff;padding:12px 24px;"
                       "font-size:16px;font-weight:bold;text-decoration:none;"
            )
            fallback_a.string = "🔍 Search Flights (Jeju → Gimpo)"
            notice.append(fallback_a)
            body.append(notice)
            print(f"    ⚠️  Search 버튼 없음 → Fallback 고정 링크 삽입")

    return str(soup)


def save_html(html_str: str, filepath: Path) -> None:
    """HTML 문자열을 지정 경로에 저장하고 파일 크기를 출력한다."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(html_str, encoding="utf-8")
    size_kb = filepath.stat().st_size / 1024
    print(f"  💾 저장: {filepath.name}  ({size_kb:.1f} KB)")


def save_metadata(metadata: dict, filepath: Path) -> None:
    """수집 메타데이터(URL, 수집 시각, 파일 목록, 태스크 설명)를 JSON으로 저장한다."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  📋 메타데이터: {filepath.name}")


def _make_empty_detail_page(idx: int) -> str:
    """수집 실패한 항공편에 대해 대체 HTML 페이지를 생성한다."""
    return (
        "<!DOCTYPE html><html lang='ko'><head><meta charset='UTF-8'>"
        f"<title>항공편 {idx} 상세</title></head><body>"
        "<div style='position:sticky;top:0;background:#fff;padding:8px 16px;"
        "border-bottom:1px solid #eee;z-index:9999;'>"
        f"<a href='./flight_list.html' style='font-weight:bold;color:#0066cc;'>"
        "← 항공편 목록으로 돌아가기</a></div>"
        f"<h2 style='padding:16px;'>항공편 {idx} 상세 정보</h2>"
        "<p style='padding:0 16px;'>⚠️ 상세 정보 수집에 실패했습니다.</p>"
        "</body></html>"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 메인 파이프라인
# ──────────────────────────────────────────────────────────────────────────────

async def main():
    print("\n" + "="*60)
    print("  Wild Web Crawling Pipeline")
    print("  Pilot Study 2: Trip.com Mock Env 구축")
    print("="*60)
    print(f"  대상 URL   : {TRIP_SEARCH_URL}")
    print(f"  출력 폴더  : {OUTPUT_DIR.resolve()}")
    print(f"  수집 항공편: {N_FLIGHTS}개")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 0: 홈 페이지 원본 HTML 수집
    # ──────────────────────────────────────────────────────────────────────────
    async with async_playwright() as pw:
        home_html_raw = await collect_home_raw_html(pw)

    # 원본 저장
    save_html(home_html_raw, RAW_DIR / "home_raw.html")

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 1: 검색 결과 + 상세 페이지 원본 HTML 수집
    # ──────────────────────────────────────────────────────────────────────────
    async with async_playwright() as pw:
        result = await collect_raw_html(pw)

    list_html_raw    = result["list_html"]
    detail_htmls_raw = result["detail_htmls"]

    # 원본 HTML 저장 (디버깅 / 비교 분석용)
    print("\n" + "="*60)
    print("  원본 HTML 저장 (raw/)")
    print("="*60)
    save_html(list_html_raw, RAW_DIR / "flight_list_raw.html")
    for i, dhtml in enumerate(detail_htmls_raw, start=1):
        if dhtml:
            save_html(dhtml, RAW_DIR / f"flight_detail_raw_{i}.html")

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 2: Context Diet (노이즈 제거 + 정적 경로 치환)
    # ──────────────────────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("  STEP 2: Context Diet (BeautifulSoup 가공)")
    print("="*60)

    # 홈 페이지 가공
    print("\n📄 홈 페이지 가공 중...")
    home_soup = context_diet(home_html_raw, label="home")
    home_html_final = rewrite_home_page(home_soup)

    # 리스트 페이지 가공
    print("\n📄 리스트 페이지 가공 중...")
    list_soup = context_diet(list_html_raw, label="list")
    list_html_final = rewrite_list_page(list_soup)

    # 상세 페이지 가공
    detail_htmls_final = []
    for i, dhtml in enumerate(detail_htmls_raw, start=1):
        if not dhtml:
            print(f"\n  ⚠️  항공편 #{i}: 수집된 HTML 없음. 빈 페이지로 대체.")
            detail_htmls_final.append(_make_empty_detail_page(i))
            continue
        print(f"\n📄 상세 #{i} 페이지 가공 중...")
        detail_soup = context_diet(dhtml, label=f"detail_{i}")
        detail_html_final = rewrite_detail_page(detail_soup, i)
        detail_htmls_final.append(detail_html_final)

    # N_FLIGHTS에 못 미치면 빈 페이지로 채움
    while len(detail_htmls_final) < N_FLIGHTS:
        idx = len(detail_htmls_final) + 1
        detail_htmls_final.append(_make_empty_detail_page(idx))

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 3: 최종 파일 저장
    # ──────────────────────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("  STEP 3: 최종 파일 저장 (mock_env/)")
    print("="*60)

    save_html(home_html_final,  OUTPUT_DIR / "home.html")          # 시작점
    save_html(list_html_final,  OUTPUT_DIR / "flight_list.html")   # 검색 결과
    for i, dhtml in enumerate(detail_htmls_final, start=1):
        save_html(dhtml, OUTPUT_DIR / f"flight_detail_{i}.html")   # 상세 페이지

    # 메타데이터 저장 (에이전트 실험 시 태스크 설명 참조용)
    metadata = {
        "source_urls"  : {"home": TRIP_HOME_URL, "search": TRIP_SEARCH_URL},
        "crawled_at"   : datetime.now().isoformat(),
        "n_flights"    : N_FLIGHTS,
        "agent_flow"   : "home.html → (Search) → flight_list.html → (Select) → flight_detail_N.html",
        "selectors_used": {
            "home": {
                "flights_tab"  : SEL_FLIGHTS_TAB,
                "oneway"       : SEL_ONEWAY,
                "from_input"   : SEL_FROM_INPUT,
                "to_input"     : SEL_TO_INPUT,
                "search_button": SEL_SEARCH_BTN,
            },
            "list": {
                "flight_card"  : SEL_FLIGHT_CARD,
                "select_button": SEL_SELECT_BTN,
            },
            "detail": {
                "modal"        : SEL_DETAIL_MODAL,
                "close_button" : SEL_CLOSE_BTN,
            },
        },
        "files": {
            "home"   : "home.html",
            "list"   : "flight_list.html",
            "details": [f"flight_detail_{i}.html" for i in range(1, N_FLIGHTS + 1)],
            "raw"    : {
                "home"   : "raw/home_raw.html",
                "list"   : "raw/flight_list_raw.html",
                "details": [f"raw/flight_detail_raw_{i}.html" for i in range(1, N_FLIGHTS + 1)],
            },
        },
        "task": {
            "description": (
                "Trip.com 제주(CJU) → 서울(GMP) 편도 항공편 검색 결과 페이지에서 "
                "조건에 맞는 항공편을 선택하여 상세 정보(수하물 규정, 취소 정책)를 확인하라."
            ),
            "goal": (
                "항공편 목록에서 가장 저렴한 항공편을 찾아 상세 페이지로 이동하고, "
                "수하물 규정과 취소 수수료를 확인한 후 해당 정보를 보고하라."
            ),
            "modality_conditions": {
                "DOM_only"       : "use_screenshot=False, use_html=True",
                "Screenshot_only": "use_screenshot=True,  use_html=False",
                "Both"           : "use_screenshot=True,  use_html=True",
            },
        },
    }
    save_metadata(metadata, OUTPUT_DIR / "metadata.json")

    # 최종 결과 출력
    print("\n" + "="*60)
    print("  ✅ 파이프라인 완료!")
    print(f"  📁 결과 폴더: {OUTPUT_DIR.resolve()}")
    print()
    for f in sorted(OUTPUT_DIR.glob("*.html")):
        size_kb = f.stat().st_size / 1024
        print(f"    {f.name:<30} {size_kb:>8.1f} KB")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
