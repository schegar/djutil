// Screenshot run against a locally running server with real data.
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const outDir = join(fileURLToPath(new URL(".", import.meta.url)), "screenshots");
mkdirSync(outDir, { recursive: true });
const base = "http://127.0.0.1:8877";

const browser = await chromium.launch();

async function login(page) {
  await page.goto(base + "/login");
  await page.getByPlaceholder("Password").fill("testpass123");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/$/);
}

// Desktop
const dctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const dpage = await dctx.newPage();
await login(dpage);
await dpage.waitForSelector("[data-testid=total-count]");
await dpage.waitForTimeout(1500);
await dpage.screenshot({ path: join(outDir, "library-desktop.png") });

// first track detail
await dpage.locator("[data-testid=track-table] a").first().click();
await dpage.waitForSelector("[data-testid=track-detail]");
await dpage.screenshot({ path: join(outDir, "track-detail.png"), fullPage: true });
await dpage.goBack();

// history session
await dpage.goto(base + "/history");
await dpage.waitForSelector("[data-testid=history-list]");
await dpage.screenshot({ path: join(outDir, "history-list.png") });
await dpage.locator("[data-testid=history-list] a").first().click();
await dpage.waitForSelector("[data-testid=history-detail]");
await dpage.screenshot({ path: join(outDir, "history-session.png"), fullPage: true });
await dctx.close();

// Mobile
const mctx = await browser.newContext({
  viewport: { width: 390, height: 844 },
  isMobile: true,
  hasTouch: true,
  userAgent:
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
});
const mpage = await mctx.newPage();
await login(mpage);
await mpage.waitForSelector("[data-testid=track-list-mobile]");
await mpage.waitForTimeout(1500);
await mpage.screenshot({ path: join(outDir, "library-mobile.png") });
await mctx.close();

await browser.close();
console.log("screenshots saved to", outDir);
