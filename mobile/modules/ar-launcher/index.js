import { requireNativeModule } from 'expo-modules-core';

// iOS only -- Android AR viewing goes through expo-intent-launcher +
// Scene Viewer instead (see ../../src/ar/launchAR.js), so this native
// module only declares an iOS side (see expo-module.config.json).
//
// Resolved lazily (not at import time): this custom module is only present
// in a prebuilt/dev-client or EAS build, never in plain Expo Go. Since
// model/[modelId].js imports launchAR.js unconditionally, an eager
// requireNativeModule() here would throw as soon as that screen's module
// graph loads -- before the user ever taps "View in AR" -- which would
// break the whole Expo Go preview (login/register/browse/upload) for a
// capability Expo Go was never going to support anyway.
function getNativeModule() {
  return requireNativeModule('ArLauncher');
}

// fileUri must be a local file:// URI (e.g. from expo-file-system's
// File.downloadFileAsync) -- QLPreviewController runs in-process and reads
// it directly, unlike Android's Scene Viewer which fetches a URL itself.
export function presentQuickLook(fileUri) {
  return getNativeModule().presentQuickLook(fileUri);
}
