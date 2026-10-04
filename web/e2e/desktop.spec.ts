import { test, expect } from "@playwright/test";

test("desktop: login -> library -> search -> camelot filter -> track detail", async ({
  page,
}) => {
  await page.goto("/");
  // redirected to login
  await expect(page).toHaveURL(/\/login/);
  await page.getByPlaceholder("Password").fill("e2epw");
  await page.getByRole("button", { name: "Sign in" }).click();

  // library loads with a total count
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId("total-count")).toContainText("500");

  // search narrows results
  await page.getByTestId("search-input").fill("Track 0001");
  await expect(page.getByTestId("total-count")).not.toContainText("500", {
    timeout: 5000,
  });
  await page.getByTestId("search-input").clear();

  // camelot filter via the wheel (8A)
  await page.getByRole("button", { name: "8A", exact: true }).click();
  await expect(page).toHaveURL(/camelot=8A/);

  // open a track -> detail shows cues
  await page.getByTestId("track-table").getByRole("link").first().click();
  await expect(page).toHaveURL(/\/tracks\//);
  await expect(page.getByTestId("track-detail")).toBeVisible();
  await expect(page.getByTestId("cues-table")).toBeVisible();
});
