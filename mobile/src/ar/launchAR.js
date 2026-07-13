import { Platform } from 'react-native';
import * as IntentLauncher from 'expo-intent-launcher';
import { File, Paths } from 'expo-file-system';
import { presentQuickLook } from 'ar-launcher';

// Android: hand the model's existing PUBLIC glb URL to Google's Scene Viewer
// app via an explicit Intent -- the exact mechanism <model-viewer> already
// uses for the web AR flow (see @google/model-viewer's ar.js
// $openSceneViewer, and templates/view.html), already proven in production
// by this same backend. Scene Viewer fetches the URL itself and can't carry
// our Bearer token, which is why the mobile API exposes a separate
// public_glb_url (see blueprints/api_tokens.py's api_v1_model) alongside the
// Bearer-gated glb_url -- this only works while the model stays "unlisted"
// (the default; nothing in this app's UI can mark a model private).
async function launchAndroidSceneViewer(model) {
  const sceneViewerUrl =
    `https://arvr.google.com/scene-viewer/1.2?file=${encodeURIComponent(model.public_glb_url)}&mode=ar_preferred`;
  await IntentLauncher.startActivityAsync('android.intent.action.VIEW', {
    data: sceneViewerUrl,
    packageName: 'com.google.android.googlequicksearchbox',
  });
}

// iOS: AR Quick Look has to run in-process via QLPreviewController (see
// modules/ar-launcher) -- there's no Scene-Viewer-style "hand a URL to a
// system AR app" intent for a native (non-WebView) app on iOS. So the USDZ
// is downloaded first, authenticated with our Bearer token like any other
// mobile API call, then handed to the native module as a local file.
async function launchIOSQuickLook(model, token) {
  if (!model.usdz_url) {
    throw new Error('The AR version of this model is not ready yet.');
  }
  const destination = new File(Paths.cache, `${model.id}.usdz`);
  const downloaded = await File.downloadFileAsync(model.usdz_url, destination, {
    headers: { Authorization: `Bearer ${token}` },
    idempotent: true,
  });
  await presentQuickLook(downloaded.uri);
}

export async function launchModelInAR({ model, token }) {
  if (Platform.OS === 'android') {
    return launchAndroidSceneViewer(model);
  }
  if (Platform.OS === 'ios') {
    return launchIOSQuickLook(model, token);
  }
  throw new Error('AR viewing is only available on iOS and Android.');
}
