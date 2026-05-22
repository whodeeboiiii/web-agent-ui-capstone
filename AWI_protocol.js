const { chromium } = require('playwright');

(async () => {
    const browser = await chromium.launch({ headless: false, slowMo: 500 });
    const context = await browser.newContext();
    const page = await context.newPage();

    await page.goto('https://playwright.dev/');
    console.log("웹페이지 로드 완료...");

    // =================================================================
    // [AWI 마스터 파이프라인] Pagination (팀원) + Augmentation (재후님)
    // =================================================================
    await page.evaluate(() => {
        const isElementInViewport = (el) => {
            const rect = el.getBoundingClientRect();
            return (
                rect.top >= 0 && rect.left >= 0 &&
                rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
                rect.right <= (window.innerWidth || document.documentElement.clientWidth)
            );
        };

        // 1. [팀원 로직] 화면 밖 요소 제거 (Pruning)
        const allElements = document.querySelectorAll('button, a, input, textarea, select, div, span, [role="button"]');
        allElements.forEach(el => {
            if (!isElementInViewport(el)) {
                el.setAttribute('aria-hidden', 'true'); // 스냅숏에서 완전 삭제
            }
        });

        // 2. [재후님 로직] 살아남은 뷰포트 내 요소들에 대한 '심층 메타데이터 보강'
        const visibleInteractiveElements = document.querySelectorAll('a:not([aria-hidden]), button:not([aria-hidden]), input:not([aria-hidden]), [onclick]:not([aria-hidden])');

        visibleInteractiveElements.forEach(el => {
            const tagName = el.tagName.toLowerCase();
            let tags = `[AWI: tag=${tagName}]`;

            if (tagName === 'a' || tagName === 'button' || tagName === 'input' || el.hasAttribute('onclick')) {
                tags += ` [AWI: clickable=True]`;
            }
            if (tagName === 'input' && el.type) {
                tags += ` [AWI: input_type=${el.type}]`;
            }

            // 야매 링크 구출
            if (el.hasAttribute('onclick') && tagName !== 'button' && tagName !== 'a') {
                el.setAttribute('role', 'button');
            }

            // 💡 FIX: aria-description 대신 aria-label에 주입하여 스냅숏에 강제 노출
            let baseName = el.getAttribute('aria-label') || el.innerText || el.value || '';
            baseName = baseName.replace(/\n/g, ' ').trim();
            el.setAttribute('aria-label', `${baseName} ${tags}`.trim());
        });

        // 3. [팀원 로직] 가상 페이지네이션 버튼 주입 (Virtual Action)
        const virtualNextBtn = document.createElement('button');
        virtualNextBtn.innerText = 'Next Page [AWI: action_id=999]';
        virtualNextBtn.setAttribute('aria-label', 'Next Page [AWI: scroll_down]'); // 스냅숏 노출용

        virtualNextBtn.style.position = 'fixed';
        virtualNextBtn.style.bottom = '10px';
        virtualNextBtn.style.right = '10px';
        virtualNextBtn.style.zIndex = '9999';

        document.body.appendChild(virtualNextBtn);
    });

    console.log("AWI 마스터 프로토콜 렌더링 완료...");

    // =================================================================
    // [최종 관측치 추출]
    // =================================================================
    const awiSnapshot = await page.ariaSnapshot();

    console.log("\n--- [최종 AWI 스냅숏 ($Observation_t)] ---");
    console.log(awiSnapshot);
    // 출력 결과: 화면에 보이는 상단 요소들만 보강되어 출력되며, 
    // 트리 맨 마지막 줄에 `- button "Next Page [AWI: scroll_down]"`이 위치하게 됩니다.

    await browser.close();
})();