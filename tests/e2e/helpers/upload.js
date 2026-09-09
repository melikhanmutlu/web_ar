const path = require('path');

// Some CI/sandboxed environments restrict outbound access to third-party
// CDNs (Tailwind, Lucide icons, unpkg's model-viewer bundle); errors caused
// purely by a blocked CDN request are not app bugs, so they're filtered out
// of failure assertions rather than asserting zero console errors.
const KNOWN_BLOCKED_CDN_ERRORS = [
  /tailwind is not defined/i,
  /lucide is not defined/i,
  /net::ERR_/i,
  /Failed to load resource.*(tailwindcss|unpkg|cdnjs|googleapis)/i,
  // Browser-console noise unrelated to app JS correctness: an unrecognized
  // (but harmless) CSP directive, and the favicon 404 present in every run.
  /Unrecognized Content-Security-Policy directive/i,
  /Failed to load resource: the server responded with a status of 404/i,
];

function isUnexpectedError(message) {
  return !KNOWN_BLOCKED_CDN_ERRORS.some((pattern) => pattern.test(message));
}

async function uploadCubeAndGetViewerUrl(page) {
  await page.goto('/studio');
  const fileInput = page.locator('#file-upload');
  await fileInput.setInputFiles(path.join(__dirname, '..', 'fixtures', 'cube.glb'));
  await page.getByRole('button', { name: /upload and convert/i }).click();

  // The upload goes through the async job flow (job_id + status polling, or
  // real-time SSE); wait for the client-side redirect to the viewer once it
  // completes.
  await page.waitForURL(/\/view\//, { timeout: 30_000 });
  await page.waitForFunction(() => document.querySelector('model-viewer')?.loaded);
  const onboardingDismiss = page.locator('#onboardingDismiss');
  if (await onboardingDismiss.isVisible()) await onboardingDismiss.click();
  return page.url();
}

module.exports = { KNOWN_BLOCKED_CDN_ERRORS, isUnexpectedError, uploadCubeAndGetViewerUrl };
