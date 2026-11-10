// Theme.swift — option B「明亮 · 照片图库」(app/DESIGN.md). Native shell colors only; web pages get theirs from
// the same tokens in src/editor/theme.py. Keep the names when swapping in A/C/D.
import AppKit

enum Theme {
    /// light/dark pair that follows NSApp.effectiveAppearance
    static func dyn(light: UInt32, dark: UInt32) -> NSColor {
        NSColor(name: nil) { ap in
            let v = ap.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? dark : light
            return NSColor(srgbRed: CGFloat((v >> 16) & 0xFF) / 255, green: CGFloat((v >> 8) & 0xFF) / 255,
                           blue: CGFloat(v & 0xFF) / 255, alpha: 1)
        }
    }
    static let bg           = dyn(light: 0xF5F5F7, dark: 0x1C1C1E)
    static let bgSide       = dyn(light: 0xEBEBEE, dark: 0x232325)
    static let surface      = dyn(light: 0xFFFFFF, dark: 0x2C2C2E)
    static let surface3     = dyn(light: 0xECECF0, dark: 0x3A3A3C)
    static let line         = dyn(light: 0xE5E5EA, dark: 0x333336)
    static let line2        = dyn(light: 0xD2D2D7, dark: 0x48484A)
    static let text         = dyn(light: 0x1D1D1F, dark: 0xF5F5F7)
    static let text2        = dyn(light: 0x48484D, dark: 0xC7C7CC)
    static let text3        = dyn(light: 0x86868B, dark: 0x8E8E93)
    static let accent       = dyn(light: 0x0071E3, dark: 0x0A84FF)
    static let accentHover  = dyn(light: 0x0077ED, dark: 0x3395FF)
    static let onAccent     = dyn(light: 0xFFFFFF, dark: 0xFFFFFF)
    static let ok           = dyn(light: 0x1A7F45, dark: 0x30D158)
    static let q            = dyn(light: 0xF5A524, dark: 0xFFB340)
    static let qInk         = dyn(light: 0x9A5B00, dark: 0xFFC566)
    static let danger       = dyn(light: 0xD70015, dark: 0xFF453A)
    static let stReview     = dyn(light: 0x0062C4, dark: 0x4CA2FF)
    static let stOpen       = dyn(light: 0x9A5B00, dark: 0xFFC566)
    static let stPass       = dyn(light: 0x1A7F45, dark: 0x30D158)
    static let stUp         = dyn(light: 0x6E6E73, dark: 0x8E8E93)
    static let stage        = dyn(light: 0x000000, dark: 0x000000)
    static let box          = dyn(light: 0xFFD60A, dark: 0xFFD60A)
    static let playhead     = dyn(light: 0x1D1D1F, dark: 0xF5F5F7)

    // layout (pt) — match --side-w / --hdr / --rail-w
    static let sidebarWidth: CGFloat = 236
    static let toolbarHeight: CGFloat = 52     // unified titlebar+toolbar; traffic lights centred in it
    static let railWidth: CGFloat = 376
    static let rowHeight: CGFloat = 34
    static let radiusSm: CGFloat = 7, radius: CGFloat = 10, radiusLg: CGFloat = 14, radiusStage: CGFloat = 12
    static let durFast: Double = 0.12, durBase: Double = 0.20   // ease: cubic-bezier(.2,.8,.2,1)

    // fonts — system only
    static let ui      = NSFont.systemFont(ofSize: 13)
    static let uiBold  = NSFont.systemFont(ofSize: 13, weight: .semibold)
    static let small   = NSFont.systemFont(ofSize: 11, weight: .medium)
    static let numbers = NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .medium)
    // sidebar background: NSVisualEffectView(material: .sidebar, blendingMode: .behindWindow) — not a flat color
}
