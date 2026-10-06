// Helpers for the in-page dialogs (window.arConfirm / window.arPrompt) that
// replaced the native alert/confirm/prompt calls.
const { expect } = require('@playwright/test');

/** Waits for the arPrompt dialog, types `value` and confirms it. */
async function answerPrompt(page, value) {
  const dlg = page.locator('.ar-dialog');
  await expect(dlg).toBeVisible();
  await dlg.locator('input').fill(value);
  await dlg.locator('[data-ar-dialog-confirm]').click();
  await expect(dlg).toHaveCount(0);
}

/** Waits for an arConfirm dialog and accepts (default) or cancels it. */
async function answerConfirm(page, accept = true) {
  const dlg = page.locator('.ar-dialog');
  await expect(dlg).toBeVisible();
  await dlg.locator(accept ? '[data-ar-dialog-confirm]' : '[data-ar-dialog-cancel]').click();
  await expect(dlg).toHaveCount(0);
}

module.exports = { answerPrompt, answerConfirm };
