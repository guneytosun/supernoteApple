// Supernote Bildirim: shows one notification, then quits.
//
// AppleScript's `display notification` is always attributed to Script Editor
// (and a click opens Script Editor), even from a saved applet. This tiny app
// posts through UNUserNotificationCenter instead, so the notification carries
// this app's own name, and a click opens Reminders.
//
// The watcher writes the text to the file named by the SupernoteMessageFile
// key of this app's Info.plist, then runs `open -g` on the app. Launched with
// no message waiting -- which is what a click on one of its notifications
// does -- it opens Reminders.
//
// Built by `supernote-todo install-app` with `xcrun swiftc`.

import Cocoa
import UserNotifications

final class Notifier: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        let center = UNUserNotificationCenter.current()
        center.delegate = self

        guard let text = takeMessage() else {
            NSLog("Supernote Bildirim: bekleyen mesaj yok, Anımsatıcılar açılıyor")
            // Probably started by a click; the click itself also arrives as
            // didReceive below, which may get there first.
            DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                self.openReminders()
                NSApp.terminate(nil)
            }
            return
        }

        center.requestAuthorization(options: [.alert, .sound]) { granted, error in
            NSLog("Supernote Bildirim: izin=\(granted) hata=\(String(describing: error))")
            guard granted else {
                DispatchQueue.main.async { NSApp.terminate(nil) }
                return
            }
            let content = UNMutableNotificationContent()
            content.title = "Supernote"
            content.body = text
            content.sound = UNNotificationSound.default
            let request = UNNotificationRequest(identifier: UUID().uuidString,
                                                content: content, trigger: nil)
            center.add(request) { error in
                NSLog("Supernote Bildirim: gönderildi, hata=\(String(describing: error))")
                DispatchQueue.main.asyncAfter(deadline: .now() + 1) { NSApp.terminate(nil) }
            }
        }
    }

    /// The pending message, removed so it is shown only once.
    private func takeMessage() -> String? {
        guard let path = Bundle.main.object(forInfoDictionaryKey: "SupernoteMessageFile") as? String,
              let raw = try? String(contentsOfFile: path, encoding: .utf8) else {
            return nil
        }
        try? FileManager.default.removeItem(atPath: path)
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty ? nil : text
    }

    private func openReminders() {
        if let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.reminders") {
            _ = NSWorkspace.shared.open(url)
        }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        openReminders()
        completionHandler()
        NSApp.terminate(nil)
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification,
                                withCompletionHandler completionHandler:
                                    @escaping (UNNotificationPresentationOptions) -> Void) {
        // Show it even though this app is (briefly) the one running.
        if #available(macOS 11.0, *) {
            completionHandler([.banner, .list, .sound])
        } else {
            completionHandler([.alert, .sound])
        }
    }
}

let app = NSApplication.shared
let notifier = Notifier()
app.delegate = notifier
app.setActivationPolicy(.accessory)
app.run()
