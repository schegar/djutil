import { test, expect } from "@playwright/test";

const TOKEN = "e2e-token";

function play(i: number, contentId: string, minutes: number) {
  const played = new Date(Date.UTC(2026, 0, 1, 20, minutes)).toISOString();
  return {
    history_entry_id: `e2e-he-${i}`,
    history_id: "e2e-live",
    content_id: contentId,
    played_at: played,
    detected_at: played,
  };
}

async function login(page: import("@playwright/test").Page) {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await page.getByPlaceholder("Password").fill("e2epw");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/$/);
}

test("live: events -> now playing -> set -> annotate transition", async ({
  page,
  request,
}) => {
  // ingest two plays over the REST fallback with the agent token
  const r = await request.post("/api/agent/events", {
    headers: { authorization: `Bearer ${TOKEN}` },
    data: [play(1, "demo-00001", 0), play(2, "demo-00002", 3)],
  });
  expect(r.ok()).toBeTruthy();

  await login(page);
  await page.goto("/live");
  await expect(page.getByTestId("live-page")).toBeVisible();
  // now playing = the second track
  await expect(page.getByTestId("live-page")).toContainText("Track 0002", {
    timeout: 10000,
  });
  // session shows both tracks
  await expect(page.getByTestId("live-page")).toContainText("Track 0001");

  // a set was auto-recorded; open it
  await page.goto("/sets");
  await page.getByRole("link").filter({ hasText: /Set / }).first().click();
  await expect(page).toHaveURL(/\/sets\/\d+/);
  await expect(page.getByTestId("set-detail")).toContainText("Track 0001");

  // annotate the transition: favourite + comment, reload, still there
  const tr = page.locator('[data-testid^="transition-"]').first();
  await tr.getByLabel("favourite").click();
  await tr.getByPlaceholder("transition note…").fill("smooth blend");
  await page.waitForTimeout(900); // comment PATCH is debounced 500 ms
  await page.reload();
  const tr2 = page.locator('[data-testid^="transition-"]').first();
  await expect(tr2.getByPlaceholder("transition note…")).toHaveValue(
    "smooth blend",
  );
  await expect(tr2.locator("svg").first()).toHaveClass(/fill-amber-400/);
});

test("history: import session as set", async ({ page }) => {
  await login(page);
  await page.goto("/history");
  await page.locator('a[href^="/history/"]').first().click();
  await expect(page).toHaveURL(/\/history\//);
  const btn = page.getByRole("button", { name: /Import as set|Open set/ });
  const openLink = page.getByRole("link", { name: "Open set" });
  if (await openLink.isVisible()) {
    await openLink.click();
  } else {
    await btn.click();
  }
  await expect(page).toHaveURL(/\/sets\/\d+/, { timeout: 10000 });
  await expect(page.getByTestId("set-detail")).toBeVisible();
});
