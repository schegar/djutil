// Phase 5-7 screenshots against the real-data server on :8899.
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const outDir = "C:\\Users\\patwi\\AppData\\Local\\Temp\\djshots";
mkdirSync(outDir, { recursive: true });
const base = "http://127.0.0.1:8899";

const browser = await chromium.launch();

async function login(page) {
  await page.goto(base + "/login");
  await page.getByPlaceholder("Password").fill("e2epw");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/$/);
}

const dctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const dpage = await dctx.newPage();
await login(dpage);

// live desktop
await dpage.goto(base + "/live");
await dpage.waitForSelector("[data-testid=live-page]");
await dpage.waitForTimeout(1200);
await dpage.screenshot({ path: `${outDir}/live-desktop.png`, fullPage: true });

// set detail with transitions (use the auto-recorded live set, else first set)
await dpage.goto(base + "/sets");
await dpage.waitForSelector("[data-testid=sets-page] a");
await dpage.locator("[data-testid=sets-page] a").first().click();
await dpage.waitForSelector("[data-testid=set-detail]");
await dpage.waitForTimeout(500);
await dpage.screenshot({ path: `${outDir}/set-detail.png`, fullPage: true });

// track detail w/ transitions + compatible: pick a track that has transitions
// (now-playing track has session plays; use a track from set entries)
const setId = new URL(dpage.url()).pathname.split("/").pop();
await dpage.goto(base + `/sets/${setId}`);
const entryLink = dpage.locator("[data-testid^=entry-] a").first();
await entryLink.click();
await dpage.waitForSelector("[data-testid=track-detail]");
await dpage.waitForTimeout(800);
await dpage.screenshot({ path: `${outDir}/track-detail.png`, fullPage: true });

// library filtered to a streaming source row
await dpage.goto(base + "/?source=spotify%2Csoundcloud");
await dpage.waitForSelector("[data-testid=total-count]");
await dpage.waitForTimeout(1200);
await dpage.screenshot({ path: `${outDir}/library-streaming.png` });
await dctx.close();

// mobile live
const mctx = await browser.newContext({
  viewport: { width: 390, height: 844 },
  isMobile: true,
  hasTouch: true,
  userAgent:
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
});
const mpage = await mctx.newPage();
await login(mpage);
await mpage.goto(base + "/live");
await mpage.waitForSelector("[data-testid=live-page]");
await mpage.waitForTimeout(1200);
await mpage.screenshot({ path: `${outDir}/live-mobile.png`, fullPage: true });
await mctx.close();

await browser.close();
console.log("done ->", outDir);
