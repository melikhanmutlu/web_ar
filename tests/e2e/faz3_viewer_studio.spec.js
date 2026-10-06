const { test, expect } = require('@playwright/test');
const { registerAndLogin } = require('./helpers/auth');
const { uploadCubeAndGetViewerUrl } = require('./helpers/upload');

// Faz 3 viewer & studio fixes (UIA-06, 07, 13, 15).

test('Escape cancels an inline title edit and nothing is saved', async ({ page, isMobile }) => {
  // On phones the title sits in the collapsed info sheet; the inline editor is desktop UI.
  test.skip(isMobile, 'title editor is in the collapsed info sheet on mobile');
  test.setTimeout(60_000);
  await registerAndLogin(page, 'titleesc');
  await uploadCubeAndGetViewerUrl(page);

  const title = page.locator('#modelTitle');
  const before = (await title.textContent()).trim();
  let patched = false;
  await page.route('**/api/models/*/metadata', (route) => { patched = true; route.continue(); });

  await title.click();
  const input = title.locator('input');
  await expect(input).toHaveAttribute('maxlength', '255');
  await input.fill('ESCAPED TITLE');
  await page.keyboard.press('Escape');

  await expect(title).toHaveText(before);
  await page.waitForTimeout(300);
  expect(patched).toBe(false);
});

test('a failed title save restores the old value and shows an error toast', async ({ page, isMobile }) => {
  // On phones the title sits in the collapsed info sheet; the inline editor is desktop UI.
  test.skip(isMobile, 'title editor is in the collapsed info sheet on mobile');
  test.setTimeout(60_000);
  await registerAndLogin(page, 'titlefail');
  await uploadCubeAndGetViewerUrl(page);
  await page.route('**/api/models/*/metadata', (route) => route.fulfill({ status: 500, body: '{}' }));

  const title = page.locator('#modelTitle');
  const before = (await title.textContent()).trim();
  await title.click();
  await title.locator('input').fill('Will fail');
  await page.keyboard.press('Enter');

  await expect(page.locator('.ar-toast--error')).toContainText('Could not save');
  await expect(title).toHaveText(before);
});

test('a material preset is a single undo step', async ({ page }) => {
  test.setTimeout(60_000);
  await registerAndLogin(page, 'presetundo');
  await uploadCubeAndGetViewerUrl(page);
  await page.waitForTimeout(1500); // let viewer:material-ready settle

  await page.locator('#toolsPanelToggle').click();
  await page.locator('#materialContainer .tp-section-header').click();
  const metal = page.locator('#metalnessSlider');
  const initial = await metal.inputValue();

  await page.locator('.material-preset-btn[data-preset="gold"]').click();
  await expect(metal).toHaveValue('1');

  await page.locator('#undoButton').click();
  await expect(metal).toHaveValue(initial);
  // One click, one step: nothing left to undo.
  await expect(page.locator('#undoButton')).toBeDisabled();
});

test('desktop AR click shows the QR fallback without counting an AR launch', async ({ page, isMobile }) => {
  test.skip(isMobile, 'Android UA launches Scene Viewer instead of the fallback modal');
  await uploadCubeAndGetViewerUrl(page);
  const events = [];
  page.on('request', (req) => {
    if (req.method() === 'POST' && /\/api\/models\/[^/]+\/events$/.test(req.url())) {
      events.push(req.postDataJSON().event_type);
    }
  });

  await page.locator('#arButton').click();
  await expect(page.locator('#arModal')).toHaveClass(/show/);
  await expect.poll(() => events).toContain('qr_shown');
  await page.waitForTimeout(2000);
  expect(events).not.toContain('ar_launch');
});

test('studio keeps submit disabled and the specific error after an invalid file', async ({ page }) => {
  await page.goto('/studio');
  await page.locator('#file-upload').setInputFiles({
    name: 'notes.txt', mimeType: 'text/plain', buffer: Buffer.from('hello'),
  });
  await expect(page.locator('.av-alert--error')).toContainText('Invalid file type');
  await expect(page.locator('#submitBtn')).toBeDisabled();
  expect(await page.locator('#file-upload').inputValue()).toBe('');
});
