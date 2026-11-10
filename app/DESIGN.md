# 审片 app: visual direction

Last updated: 2026-11-10

Status: **option B is the working default** (the creator chose it on 11/10). A, C and D stay on the table, and he will compare them later in `app/options.html`. The full component spec follows once the final pick is made. This file holds B's ready-to-apply tokens plus the token block for every option.

Files in `app/`:
- `options.html`: the four screenshots side by side, with a one-line Chinese description each.
- `mock_A.html` … `mock_D.html`: static mocks of the same screen (shell, 成片 tab, video, shot list and comments). Each is a single file with its full CSS inline: the `:root` tokens, then the shared base, then that option's flavor rules.
- `mock_A.png` … `mock_D.png`: headless screenshots at 1600×1000.

## Principles

1. The picture is the brightest thing on screen. Chrome recedes; colour is reserved for state (status, the current shot, the active comment, the one primary action).
2. Use space and tone shifts instead of boxes. Avoid grids of bordered white frames: a panel is a sheet, and the rows inside it are not cards.
3. One accent and four status colours. Nothing else is coloured.
4. Use only the system fonts, with tabular numerals everywhere a number changes (timecodes, durations, counts).
5. Calm motion: 120 ms for hover and press, 200 ms for panels, `cubic-bezier(.2,.8,.2,1)`. No bounces and no entrance animations.

## Swapping styles

Every option defines **the same variable names**. Those names are a superset of what `src/editor/theme.py` already uses (`--bg`, `--surface*`, `--line*`, `--text*`, `--accent*`, `--ok*`, `--q*`, `--danger*`, `--stage*`, `--used/--unused`, `--r-*`, `--sh-*`, `--hdr`, `--font`, `--mono`). To switch, replace the `:root{…}` block in `theme.CSS` and the `DARK` string. No page markup changes.

Tokens carry most of each look. The rest comes from a short "flavor" rule set per option (radius style, separators, fonts in headings), which lives at the end of each `mock_X.html`. If a flavor rule is ever ported, keep it in one `FLAVOR` string in theme.py so a swap stays a two-string change.

New names that pages can start using (all optional):
- `--bg-side`, `--bg-bar`, `--bg-rail`: the shell and pane backgrounds.
- `--on-accent`, `--btn-pri-bg/-ink`, `--btn-sec-bg/-ink/-line`: buttons.
- `--sel-bg/-ink`: the selected sidebar row.
- `--st-review/-open/-pass/-up` plus `-bg`: the status chips for 待审片, 有问题没答, 已通过 and 已上传.
- `--box`: the comment box drawn on the video.
- `--playhead`.
- `--seg/-seg-2/-seg-past`: the timeline shot segments.
- `--sh-stage`, `--r-stage`, `--font-display`, `--font-num`, `--fs-*`.
- `--side-w`, `--rail-w`, `--track-h`, `--dur-1/-2`, `--ease`.

## Option B「明亮 · 照片图库」(working default)

**Theme rationale:** light-first because he works in macOS light mode and the existing pages are light. The video always sits on a pure-black stage, so it reads as the hero. The light surroundings are greys (#f5f5f7 and white), not pure white walls, so long sessions stay soft on the eyes. The dark variant follows macOS appearance and also replaces `theme.DARK`, which the fullscreen rail uses.

### tokens.css (paste into `theme.CSS`, replacing its `:root` block; the dark `{…}` body replaces `theme.DARK`)

```css
/* tokens.css — option B「明亮 · 照片图库」(working default). Same variable names in A/C/D. */
:root{
  /* type, radius, layout, motion: shared by every option unless an option overrides them */
  --font:-apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC","Helvetica Neue",sans-serif;
  --font-display:-apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC","Helvetica Neue",sans-serif;
  --font-num:-apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC","Helvetica Neue",sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,monospace;
  --fs-xs:11px;
  --fs-sm:12px;
  --fs:13px;
  --fs-md:14px;
  --fs-lg:16px;
  --fs-title:20px;
  --r-xs:4px;
  --r-sm:7px;
  --r:10px;
  --r-lg:14px;
  --r-stage:12px;
  --hdr:52px;
  --side-w:236px;
  --rail-w:376px;
  --track-h:16px;
  --dur-1:120ms;
  --dur-2:200ms;
  --ease:cubic-bezier(.2,.8,.2,1);
  /* colour + depth */
  color-scheme:light;
  --bg:#f5f5f7;
  --bg-side:#ebebee;
  --bg-bar:#f5f5f7;
  --bg-rail:#ffffff;
  --surface:#ffffff;
  --surface-2:#f7f7f9;
  --surface-3:#ececf0;
  --line:#e5e5ea;
  --line-2:#d2d2d7;
  --text:#1d1d1f;
  --text-2:#48484d;
  --text-3:#86868b;
  --faint:#aeaeb2;
  --accent:#0071e3;
  --accent-hover:#0077ed;
  --accent-soft:#e9f2fd;
  --accent-line:#a9cdf5;
  --accent-ring:rgba(0,113,227,.16);
  --on-accent:#ffffff;
  --btn-pri-bg:#0071e3;
  --btn-pri-ink:#ffffff;
  --btn-sec-bg:#ffffff;
  --btn-sec-ink:#1d1d1f;
  --btn-sec-line:#d2d2d7;
  --sel-bg:#dcdce1;
  --sel-ink:#1d1d1f;
  --ok:#1a7f45;
  --ok-soft:#e6f4ea;
  --q:#f5a524;
  --q-ink:#9a5b00;
  --q-soft:#fff8eb;
  --q-line:#f7dca6;
  --danger:#d70015;
  --danger-soft:#fdecee;
  --st-review:#0062c4;
  --st-review-bg:#e3eefc;
  --st-open:#9a5b00;
  --st-open-bg:#fdf0d5;
  --st-pass:#1a7f45;
  --st-pass-bg:#e2f3e7;
  --st-up:#6e6e73;
  --st-up-bg:transparent;
  --stage:#000000;
  --stage-ink:rgba(255,255,255,.92);
  --stage-mute:rgba(255,255,255,.6);
  --box:#ffd60a;
  --playhead:#1d1d1f;
  --used:#34c759;
  --unused:#d2d2d7;
  --seg:#e2e2e7;
  --seg-2:#dadadf;
  --seg-past:#bdbdc4;
  --sh-1:0 1px 2px rgba(0,0,0,.08),0 0 0 .5px rgba(0,0,0,.06);
  --sh-2:0 8px 28px rgba(0,0,0,.10),0 0 0 .5px rgba(0,0,0,.06);
  --sh-stage:0 10px 30px rgba(0,0,0,.14),0 2px 6px rgba(0,0,0,.08);
}
/* dark: follows macOS unless the page pins a theme; the same block also replaces theme.DARK (fullscreen rail) */
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme:dark;
    --bg:#1c1c1e;
    --bg-side:#232325;
    --bg-bar:#1c1c1e;
    --bg-rail:#232325;
    --surface:#2c2c2e;
    --surface-2:#262628;
    --surface-3:#3a3a3c;
    --line:#333336;
    --line-2:#48484a;
    --text:#f5f5f7;
    --text-2:#c7c7cc;
    --text-3:#8e8e93;
    --faint:#636366;
    --accent:#0a84ff;
    --accent-hover:#3395ff;
    --accent-soft:rgba(10,132,255,.16);
    --accent-line:rgba(10,132,255,.5);
    --accent-ring:rgba(10,132,255,.28);
    --on-accent:#ffffff;
    --btn-pri-bg:#0a84ff;
    --btn-pri-ink:#ffffff;
    --btn-sec-bg:#3a3a3c;
    --btn-sec-ink:#f5f5f7;
    --btn-sec-line:#48484a;
    --sel-bg:#3a3a3c;
    --sel-ink:#ffffff;
    --ok:#30d158;
    --ok-soft:rgba(48,209,88,.14);
    --q:#ffb340;
    --q-ink:#ffc566;
    --q-soft:rgba(255,179,64,.10);
    --q-line:rgba(255,179,64,.32);
    --danger:#ff453a;
    --danger-soft:rgba(255,69,58,.14);
    --st-review:#4ca2ff;
    --st-review-bg:rgba(10,132,255,.16);
    --st-open:#ffc566;
    --st-open-bg:rgba(255,179,64,.14);
    --st-pass:#30d158;
    --st-pass-bg:rgba(48,209,88,.14);
    --st-up:#8e8e93;
    --st-up-bg:transparent;
    --stage:#000000;
    --stage-ink:rgba(255,255,255,.92);
    --stage-mute:rgba(255,255,255,.6);
    --box:#ffd60a;
    --playhead:#f5f5f7;
    --used:#30d158;
    --unused:#48484a;
    --seg:#3a3a3c;
    --seg-2:#333336;
    --seg-past:#636366;
    --sh-1:0 1px 2px rgba(0,0,0,.4),0 0 0 .5px rgba(255,255,255,.06);
    --sh-2:0 10px 32px rgba(0,0,0,.5),0 0 0 .5px rgba(255,255,255,.08);
    --sh-stage:0 10px 30px rgba(0,0,0,.4);
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --bg:#1c1c1e;
  --bg-side:#232325;
  --bg-bar:#1c1c1e;
  --bg-rail:#232325;
  --surface:#2c2c2e;
  --surface-2:#262628;
  --surface-3:#3a3a3c;
  --line:#333336;
  --line-2:#48484a;
  --text:#f5f5f7;
  --text-2:#c7c7cc;
  --text-3:#8e8e93;
  --faint:#636366;
  --accent:#0a84ff;
  --accent-hover:#3395ff;
  --accent-soft:rgba(10,132,255,.16);
  --accent-line:rgba(10,132,255,.5);
  --accent-ring:rgba(10,132,255,.28);
  --on-accent:#ffffff;
  --btn-pri-bg:#0a84ff;
  --btn-pri-ink:#ffffff;
  --btn-sec-bg:#3a3a3c;
  --btn-sec-ink:#f5f5f7;
  --btn-sec-line:#48484a;
  --sel-bg:#3a3a3c;
  --sel-ink:#ffffff;
  --ok:#30d158;
  --ok-soft:rgba(48,209,88,.14);
  --q:#ffb340;
  --q-ink:#ffc566;
  --q-soft:rgba(255,179,64,.10);
  --q-line:rgba(255,179,64,.32);
  --danger:#ff453a;
  --danger-soft:rgba(255,69,58,.14);
  --st-review:#4ca2ff;
  --st-review-bg:rgba(10,132,255,.16);
  --st-open:#ffc566;
  --st-open-bg:rgba(255,179,64,.14);
  --st-pass:#30d158;
  --st-pass-bg:rgba(48,209,88,.14);
  --st-up:#8e8e93;
  --st-up-bg:transparent;
  --stage:#000000;
  --stage-ink:rgba(255,255,255,.92);
  --stage-mute:rgba(255,255,255,.6);
  --box:#ffd60a;
  --playhead:#f5f5f7;
  --used:#30d158;
  --unused:#48484a;
  --seg:#3a3a3c;
  --seg-2:#333336;
  --seg-past:#636366;
  --sh-1:0 1px 2px rgba(0,0,0,.4),0 0 0 .5px rgba(255,255,255,.06);
  --sh-2:0 10px 32px rgba(0,0,0,.5),0 0 0 .5px rgba(255,255,255,.08);
  --sh-stage:0 10px 30px rgba(0,0,0,.4);
}
```

### What makes B look like B (do these with the token swap; CSS only)

- **Toolbar:**
  - No bottom border.
  - Episode number and name on the left, as `125` in `--text-3` plus `外滩日出` at 16/600.
  - The tab row 封面/素材/成片/Shorts/标题 is a centred segmented control: a `#e3e3e8` track with a white selected pill using `--sh-1`.
  - The render status sits on the right: `预览渲染中`, a 96×4 bar and the percentage in tabular figures.
  - Then 「更新预览」 as a secondary pill and 「审片通过」 as the primary pill (`border-radius:999px`).
- **Page `.hdr`:** inside the app, this duplicates the toolbar. Hide it when embedded, for example `html.in-app .hdr{display:none}`, with the shell adding the class through a user script.
- **Video stage:**
  - `--stage` black, `--r-stage` 12px, `--sh-stage`.
  - No border, sitting directly on the grey canvas.
  - Captions: white text with a soft shadow and no black box (`.cap span` background dropped), so the frame stays clean.
- **Timeline:**
  - 16px shot-segment track with 1px gaps.
  - Played segments use `--seg-past`, the current shot `--accent-line`.
  - Comment markers are 8px accent dots and question markers are `--q` dots, both in a 12px lane above.
  - The playhead is a 2px `--playhead` line with a 10px knob.
- **Shot list:**
  - Rows are 48px with no borders.
  - Each row has a 54×30 thumbnail with a 4px radius, `#14` in tabular `--text-3`, the title, an optional badge (`1 条评论` accent-soft, `已改` ok-soft), then the in-point and duration right-aligned in tabular `--text-3`, then a `···` icon button.
  - The current row is white with `--sh-1`, a "lifted" effect rather than a coloured background.
- **Right rail:**
  - One white sheet (`--bg-rail`) with a left hairline.
  - Cards inside it have no border and a `--surface-2` fill.
  - The active comment is white, with `--accent-line` and a 3px `--accent-ring` halo.
  - Question cards use `--q-soft` / `--q-line`.
  - The 评论 / 问题 tabs are a small segmented control.
- **Comment card:**
  - Header: a 20px avatar, the bold name, a timecode chip (accent text on accent-soft, tabular), the `框 1` tag when a box exists, and a relative time pushed right.
  - Body: 14/1.6.
  - Agent reply: under a hairline, with a green check disc or a spinner.
- **Composer:**
  - Quiet chips (`--surface-3`, pill).
  - A borderless `--surface-2` field showing the timecode chip it will attach.
  - One hint line in 11px `--text-3`.
  - 「评论」 as a ghost button and 「交给 Agent」 as primary.
- **Sidebar rows:**
  - 34px tall with a 7px radius: number in tabular `--text-3`, name, chip on the right.
  - Selection is `--sel-bg` grey, not blue.
  - Chips are soft pills with a 6px dot. 已上传 is plain grey text with no pill, because finished work should be quiet.

### Swift constants (native shell)

```swift
// Theme.swift — option B. Native shell colors only; web pages get theirs from tokens.css.
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
    static let sidebarWidth: CGFloat = 236     // min 200, max 300 when user-resized
    static let toolbarHeight: CGFloat = 52     // unified titlebar+toolbar; traffic lights centred in it
    static let railWidth: CGFloat = 376
    static let rowHeight: CGFloat = 34
    static let radiusSm: CGFloat = 7, radius: CGFloat = 10, radiusLg: CGFloat = 14, radiusStage: CGFloat = 12
    static let durFast: Double = 0.12, durBase: Double = 0.20   // ease: cubic-bezier(.2,.8,.2,1)

    // fonts — system only, nothing to install
    static let ui      = NSFont.systemFont(ofSize: 13)
    static let uiBold  = NSFont.systemFont(ofSize: 13, weight: .semibold)
    static let small   = NSFont.systemFont(ofSize: 11, weight: .medium)            // chips, group labels
    static let numbers = NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .medium) // episode numbers, timecodes
    // sidebar background: NSVisualEffectView(material: .sidebar, blendingMode: .behindWindow) — not a flat color
}
```

**Shell:**
- `NSWindow` with `.fullSizeContentView`, `titlebarAppearsTransparent = true`, and a unified toolbar style.
- Traffic lights sit in the sidebar's 52pt top strip, at x = 20 and vertically centred.
- The sidebar is an `NSVisualEffectView` with `.sidebar` material, 236pt wide.
- Each web tab gets its own `WKWebView`, with `underPageBackgroundColor = Theme.bg` so overscroll matches.
- **App icon:** a white rounded square with a single black play triangle, with a small champagne (#C9A96E) check notch cut into its right edge, meaning "review → approve".

## Option A「暗房 · 专业剪辑台」 (token overrides on top of the shared scale)

Flavor beyond tokens: square corners, dark 1px separators between panes (no gaps), video edge to edge with no margin, a thumbnail filmstrip lane above the shot track, mono timecode in the accent colour, a red playhead, group labels in small letter-spaced caps, and selection shown as a 2px left bar.

```css
:root{
  color-scheme:dark;
  --bg:#1e1e20;
  --bg-side:#252527;
  --bg-bar:#2a2a2d;
  --bg-rail:#252527;
  --surface:#2f2f33;
  --surface-2:#2a2a2d;
  --surface-3:#38383c;
  --line:#0f0f10;
  --line-2:#46464b;
  --text:#e6e6e6;
  --text-2:#b0b0b4;
  --text-3:#7c7c82;
  --faint:#56565b;
  --accent:#f7c844;
  --accent-hover:#ffd45c;
  --accent-soft:rgba(247,200,68,.14);
  --accent-line:rgba(247,200,68,.55);
  --accent-ring:rgba(247,200,68,.22);
  --on-accent:#1a1a1a;
  --btn-pri-bg:#f7c844;
  --btn-pri-ink:#1a1a1a;
  --btn-sec-bg:#3a3a3f;
  --btn-sec-ink:#e6e6e6;
  --btn-sec-line:#4a4a50;
  --sel-bg:#3d3d42;
  --sel-ink:#ffffff;
  --ok:#4cd964;
  --ok-soft:rgba(76,217,100,.14);
  --q:#ff8a3d;
  --q-ink:#ffa366;
  --q-soft:rgba(255,138,61,.10);
  --q-line:rgba(255,138,61,.35);
  --danger:#ff453a;
  --danger-soft:rgba(255,69,58,.14);
  --st-review:#f7c844;
  --st-review-bg:transparent;
  --st-open:#ff8a3d;
  --st-open-bg:transparent;
  --st-pass:#4cd964;
  --st-pass-bg:transparent;
  --st-up:#7c7c82;
  --st-up-bg:transparent;
  --stage:#000000;
  --stage-ink:rgba(255,255,255,.92);
  --stage-mute:rgba(255,255,255,.6);
  --box:#f7c844;
  --playhead:#ff453a;
  --used:#4cd964;
  --unused:#3a3a3f;
  --seg:#3b4a6b;
  --seg-2:#34425f;
  --seg-past:#52669a;
  --sh-1:0 1px 0 rgba(255,255,255,.04) inset,0 1px 2px rgba(0,0,0,.4);
  --sh-2:0 12px 32px rgba(0,0,0,.55);
  --sh-stage:none;
  --fs-xs:10.5px;
  --fs-sm:11.5px;
  --fs:12.5px;
  --fs-md:13px;
  --fs-title:15px;
  --r-xs:2px;
  --r-sm:4px;
  --r:5px;
  --r-lg:6px;
  --r-stage:0px;
  --font-num:"SF Mono",ui-monospace,Menlo,monospace;
  --side-w:224px;
  --rail-w:360px;
  --track-h:22px;
}
```

## Option C「纸感 · 杂志编辑部」

Flavor beyond tokens: hairline rules instead of boxes; tabs as Songti text with a champagne underline; Bodoni 72 lining numerals for the episode number, sidebar numbers and the big timecode, but SF for small timecodes; the video in a thin passe-partout outline; comments as ruled entries in Songti 15/1.75; the primary button in ink black and champagne only for highlights. No old-style figures, which read badly at small sizes.

```css
:root{
  color-scheme:light;
  --bg:#f6f2ea;
  --bg-side:#efe9dd;
  --bg-bar:#f6f2ea;
  --bg-rail:#fbf8f2;
  --surface:#fffdf9;
  --surface-2:#f9f5ee;
  --surface-3:#ebe4d6;
  --line:#e3dbcb;
  --line-2:#cfc4ae;
  --text:#26221d;
  --text-2:#5a5147;
  --text-3:#8c8173;
  --faint:#b7ab97;
  --accent:#9c7740;
  --accent-hover:#8a6834;
  --accent-soft:#f3eadb;
  --accent-line:#d9c39c;
  --accent-ring:rgba(184,149,94,.22);
  --on-accent:#ffffff;
  --btn-pri-bg:#26221d;
  --btn-pri-ink:#f6efe2;
  --btn-sec-bg:transparent;
  --btn-sec-ink:#26221d;
  --btn-sec-line:#cfc4ae;
  --sel-bg:#e4dccb;
  --sel-ink:#26221d;
  --ok:#4f7a4a;
  --ok-soft:#e8eedf;
  --q:#c7782e;
  --q-ink:#9a5518;
  --q-soft:#fbf0e1;
  --q-line:#ecd2ae;
  --danger:#a8322a;
  --danger-soft:#f6e3df;
  --st-review:#8a6834;
  --st-review-bg:transparent;
  --st-open:#b35f1e;
  --st-open-bg:transparent;
  --st-pass:#4f7a4a;
  --st-pass-bg:transparent;
  --st-up:#9a8f80;
  --st-up-bg:transparent;
  --stage:#14110e;
  --stage-ink:rgba(255,250,240,.92);
  --stage-mute:rgba(255,250,240,.6);
  --box:#e2c48d;
  --playhead:#26221d;
  --used:#6f8f5f;
  --unused:#ddd3c1;
  --seg:#e4dccb;
  --seg-2:#dcd2bf;
  --seg-past:#c9b48f;
  --sh-1:0 1px 2px rgba(60,40,10,.08);
  --sh-2:0 10px 30px rgba(60,40,10,.10);
  --sh-stage:0 1px 0 rgba(0,0,0,.04),0 14px 34px rgba(60,40,10,.16);
  --font-display:"Bodoni 72","Songti SC","STSong",serif;
  --font-num:"Bodoni 72 Oldstyle","Bodoni 72",Didot,serif;
  --fs-title:26px;
  --r-sm:6px;
  --r:8px;
  --r-lg:10px;
  --r-stage:3px;
  --track-h:10px;
}
```

## Option D「静夜 · Linear 风」

Flavor beyond tokens: the main area is an inset rounded panel on a darker sidebar canvas, with almost no borders; a faint violet radial glow at the top of the content; violet only for the live element (current shot, active comment, primary button, timeline markers); thin 8px segments in the track.

```css
:root{
  color-scheme:dark;
  --bg:#0f1012;
  --bg-side:#0b0c0e;
  --bg-bar:#0f1012;
  --bg-rail:#121316;
  --surface:#17181c;
  --surface-2:#1b1c20;
  --surface-3:#222328;
  --line:#1f2025;
  --line-2:#2c2e34;
  --text:#ececee;
  --text-2:#a9abb2;
  --text-3:#6c6f78;
  --faint:#4a4c53;
  --accent:#8b7dff;
  --accent-hover:#9d91ff;
  --accent-soft:rgba(139,125,255,.13);
  --accent-line:rgba(139,125,255,.45);
  --accent-ring:rgba(139,125,255,.16);
  --on-accent:#ffffff;
  --btn-pri-bg:#7c6cff;
  --btn-pri-ink:#ffffff;
  --btn-sec-bg:#1c1d22;
  --btn-sec-ink:#ececee;
  --btn-sec-line:#2c2e34;
  --sel-bg:#1d1e23;
  --sel-ink:#ffffff;
  --ok:#4cc38a;
  --ok-soft:rgba(76,195,138,.12);
  --q:#f0b64a;
  --q-ink:#f3c56e;
  --q-soft:rgba(240,182,74,.07);
  --q-line:rgba(240,182,74,.22);
  --danger:#eb5757;
  --danger-soft:rgba(235,87,87,.12);
  --st-review:#a79dff;
  --st-review-bg:rgba(139,125,255,.12);
  --st-open:#f0b64a;
  --st-open-bg:rgba(240,182,74,.10);
  --st-pass:#4cc38a;
  --st-pass-bg:rgba(76,195,138,.10);
  --st-up:#6c6f78;
  --st-up-bg:transparent;
  --stage:#000000;
  --stage-ink:rgba(255,255,255,.92);
  --stage-mute:rgba(255,255,255,.6);
  --box:#8b7dff;
  --playhead:#ececee;
  --used:#4cc38a;
  --unused:#26272c;
  --seg:#1f2025;
  --seg-2:#25262b;
  --seg-past:#3d3e47;
  --sh-1:0 0 0 1px rgba(255,255,255,.06),0 1px 2px rgba(0,0,0,.5);
  --sh-2:0 0 0 1px rgba(255,255,255,.06),0 16px 40px rgba(0,0,0,.6);
  --sh-stage:0 0 0 1px rgba(255,255,255,.06),0 20px 60px rgba(0,0,0,.5);
  --r-sm:6px;
  --r:9px;
  --r-stage:10px;
  --track-h:8px;
}
```

## Keep it lean: do NOT add

- Dashboard furniture: stat tiles, charts, progress rings or a "today" summary in the shell.
- Card grids of bordered white boxes, or borders on both a panel and the rows inside it.
- Gradients or glass anywhere except the sidebar's native vibrancy (and D's single faint glow, if D is picked).
- Web fonts or font downloads. Songti / Bodoni appear only in option C.
- More colours: no per-episode colours, no rainbow tags, and no second accent.
- Animations beyond hover, press and panel transitions: no skeleton shimmer and no confetti on 「审片通过」. A 200 ms check and toast is enough.
- Extra toolbar buttons. Each tab keeps one primary action at most.
