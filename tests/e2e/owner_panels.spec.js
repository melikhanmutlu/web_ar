const { test, expect } = require('@playwright/test');
const { registerAndLogin } = require('./helpers/auth');
const { isUnexpectedError, uploadCubeAndGetViewerUrl } = require('./helpers/upload');

// Several tools-panel sections only render for the model's owner (Analytics,
// Embed, undo/redo). viewer_tools.spec.js only ever uploads anonymously, so
// none of that owner-only UI gets exercised there -- this covers it.

test('owner sees and can use the Analytics and Embed panels', async ({ page }) => {
  // Two extra full page loads (register + login) beyond the anonymous-only
  // upload flow other specs use push this past the default 30s budget.
  test.setTimeout(60_000);
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });

  await registerAndLogin(page, 'ownerpanels');
  await uploadCubeAndGetViewerUrl(page);

  await page.locator('#toolsPanelToggle').click();

  await page.locator('#analyticsContainer .tp-section-header').click();
  await expect(page.locator('#analyticsTotals')).not.toContainText('Loading');
  await page.locator('#toolsDetailBackBtn').click();

  await page.locator('#embedContainer .tp-section-header').click();
  await expect(page.locator('#embedSnippetOutput')).toHaveValue(/<iframe/);
  await page.locator('#embedSnippetType').selectOption('woocommerce_shortcode');
  await expect(page.locator('#embedSnippetOutput')).toHaveValue(/arvision_model/);

  const unexpected = errors.filter(isUnexpectedError);
  expect(unexpected, `unexpected console/page errors: ${unexpected.join('\n')}`).toEqual([]);
});

test('non-owner does not see Analytics or Embed panels', async ({ page }) => {
  await uploadCubeAndGetViewerUrl(page); // anonymous upload = no owner
  await page.locator('#toolsPanelToggle').click();
  await expect(page.locator('#analyticsContainer')).toHaveCount(0);
  await expect(page.locator('#embedContainer')).toHaveCount(0);
});
