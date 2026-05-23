/**
 * Standalone AWI protocol demo.
 * Injects awi_inject.js into a page and prints an accessibility snapshot.
 *
 * Usage:
 *   node AWI_protocol.js
 *   AWI_URL=https://parandol.tistory.com/41 node AWI_protocol.js
 */
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const AWI_INJECT = fs.readFileSync(path.join(__dirname, 'awi_inject.js'), 'utf8');
const START_URL = process.env.AWI_URL || 'https://playwright.dev/';

(async () => {
    const browser = await chromium.launch({ headless: false, slowMo: 500 });
    const context = await browser.newContext();
    const page = await context.newPage();

    await page.goto(START_URL);
    console.log('웹페이지 로드 완료:', START_URL);
    await page.waitForLoadState('networkidle');

    await page.evaluate(AWI_INJECT);
    console.log('AWI 마스터 프로토콜 렌더링 완료...');

    const awiSnapshot = await page.locator('body').ariaSnapshot();
    console.log('\n--- [최종 AWI 스냅숏 ($Observation_t)] ---');
    console.log(awiSnapshot);

    // await browser.close();
})();
