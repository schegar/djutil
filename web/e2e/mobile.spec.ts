import { test, expect } from "@playwright/test";

test("mobile: login -> list -> filter sheet", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await page.getByPlaceholder("Password").fill("e2epw");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByTestId("total-count")).toContainText("500");
  // mobile list renders (not the desktop table)
  await expect(page.getByTestId("track-list-mobile")).toBeVisible();

  // filter sheet opens and applies a camelot filter
  await page.getByTestId("open-filters").click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByTestId("filters-panel")).toBeVisible();
  await dialog.getByRole("button", { name: "8A", exact: true }).click();
  await page.keyboard.press("Escape");
  await expect(page).toHaveURL(/camelot=8A/);
});
