import { requireNativeModule } from 'expo-modules-core';

// iOS only -- Android AR viewing goes through expo-intent-launcher +
// Scene Viewer instead (see ../../src/ar/launchAR.js), so this native
// module only declares an iOS side (see expo-module.config.json).
const ArLauncherModule = requireNativeModule('ArLauncher');

// fileUri must be a local file:// URI (e.g. from expo-file-system's
// File.downloadFileAsync) -- QLPreviewController runs in-process and reads
// it directly, unlike Android's Scene Viewer which fetches a URL itself.
export function presentQuickLook(fileUri) {
  return ArLauncherModule.presentQuickLook(fileUri);
}
