"""Native macOS overlay hosting the JARVIS HUD — NO browser window.

A borderless, transparent, click-through, always-on-top window with a WKWebView that
loads the local HUD page. It floats over the desktop and every app, never intercepts
mouse/keyboard (ignoresMouseEvents), and the HUD fades in only while JARVIS is speaking
(the page drives its own presence over SSE). So "말하면 화면에 나온다".

Runs as its OWN process (AppKit needs the main runloop) — the orchestrator spawns it:
    <main-venv python> -m jarvis.hud.overlay_mac http://127.0.0.1:8787/

Requires pyobjc (`pip install -e '.[hud]'`). Degrades with a clear message if absent.
"""
from __future__ import annotations

import sys


def _window_level():
    # Above the menu bar / fullscreen apps. Prefer the screensaver level; fall back.
    try:
        from AppKit import NSScreenSaverWindowLevel
        return NSScreenSaverWindowLevel
    except Exception:
        try:
            from AppKit import NSStatusWindowLevel
            return NSStatusWindowLevel + 1
        except Exception:
            return 1000


def main(url: str) -> int:
    try:
        from AppKit import (
            NSApplication,
            NSApplicationActivationPolicyAccessory,
            NSBackingStoreBuffered,
            NSColor,
            NSScreen,
            NSWindow,
            NSWindowCollectionBehaviorCanJoinAllSpaces,
            NSWindowCollectionBehaviorFullScreenAuxiliary,
            NSWindowCollectionBehaviorStationary,
            NSWindowStyleMaskBorderless,
        )
        from Foundation import NSURL, NSURLRequest
        from WebKit import WKWebView, WKWebViewConfiguration
    except Exception as exc:  # pyobjc not installed
        print(f"[overlay] pyobjc unavailable ({exc}). Install: pip install -e '.[hud]'")
        return 1

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)  # no dock icon

    frame = NSScreen.mainScreen().frame()
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        frame, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
    win.setOpaque_(False)
    win.setBackgroundColor_(NSColor.clearColor())
    win.setHasShadow_(False)
    win.setLevel_(_window_level())
    win.setIgnoresMouseEvents_(True)  # click-through: never blocks the user
    win.setCollectionBehavior_(
        NSWindowCollectionBehaviorCanJoinAllSpaces
        | NSWindowCollectionBehaviorFullScreenAuxiliary
        | NSWindowCollectionBehaviorStationary)

    cfg = WKWebViewConfiguration.alloc().init()
    web = WKWebView.alloc().initWithFrame_configuration_(
        ((0, 0), (frame.size.width, frame.size.height)), cfg)
    web.setValue_forKey_(False, "drawsBackground")  # transparent webview
    win.setContentView_(web)
    web.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(url)))
    win.orderFrontRegardless()
    app.run()
    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787/"
    raise SystemExit(main(target))
