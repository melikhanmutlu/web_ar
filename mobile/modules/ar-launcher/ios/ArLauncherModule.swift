// Presents Apple's AR Quick Look for a local USDZ file, the same mechanism
// <model-viewer>'s ios-src attribute relies on for the web AR flow (a plain
// USDZ link that iOS/Safari hands to Quick Look) -- here invoked in-process
// via QLPreviewController + ARQuickLookPreviewItem, since a native app has
// no WebView `rel="ar"` anchor to rely on.
//
// NOT verifiable in the container this was written in (no Xcode/macOS/iOS
// device available there) -- this is the first thing to sanity-check after
// an `expo prebuild`/EAS iOS build: does presentQuickLook(uri) for a real
// downloaded .usdz file show the standard Quick Look AR view with the AR
// badge/button on a physical device (the simulator cannot show AR at all).

import ARKit
import ExpoModulesCore
import QuickLook
import UIKit

public class ArLauncherModule: Module {
  public func definition() -> ModuleDefinition {
    Name("ArLauncher")

    AsyncFunction("presentQuickLook") { (fileUri: String, promise: Promise) in
      DispatchQueue.main.async {
        guard let url = URL(string: fileUri) else {
          promise.reject("E_INVALID_URI", "Invalid file URI: \(fileUri)")
          return
        }
        guard let presentingViewController = ArLauncherModule.topViewController() else {
          promise.reject("E_NO_ROOT_VC", "No view controller to present AR Quick Look from")
          return
        }

        let previewItem = ARQuickLookPreviewItem(fileAt: url)
        let controller = QLPreviewController()
        let coordinator = QuickLookCoordinator(previewItem: previewItem)
        controller.dataSource = coordinator
        // QLPreviewController only holds a weak reference to its dataSource,
        // so the coordinator must be kept alive for as long as the
        // controller is -- tie its lifetime to the controller instance.
        objc_setAssociatedObject(controller, &AssociatedKeys.coordinator, coordinator, .OBJC_ASSOCIATION_RETAIN)

        presentingViewController.present(controller, animated: true) {
          promise.resolve(nil)
        }
      }
    }
  }

  private static func topViewController() -> UIViewController? {
    guard
      let root = UIApplication.shared.connectedScenes
        .compactMap({ ($0 as? UIWindowScene)?.keyWindow })
        .first?.rootViewController
    else {
      return nil
    }
    var top = root
    while let presented = top.presentedViewController {
      top = presented
    }
    return top
  }
}

private enum AssociatedKeys {
  static var coordinator = "coordinator"
}

private class QuickLookCoordinator: NSObject, QLPreviewControllerDataSource {
  private let previewItem: ARQuickLookPreviewItem

  init(previewItem: ARQuickLookPreviewItem) {
    self.previewItem = previewItem
  }

  func numberOfPreviewItems(in controller: QLPreviewController) -> Int {
    1
  }

  func previewController(_ controller: QLPreviewController, previewItemAt index: Int) -> QLPreviewItem {
    previewItem
  }
}
