# HeatShield on Mobile — PWA (decided: no APK)

**Decision (2026-09-01):** ship the mobile experience as a **Progressive Web App**, not a native APK.
No Android Studio, no JDK, no 3 GB toolchain, no Play Store wait — and it works on iOS too.

## Why PWA instead of Capacitor/React Native

| Option | Toolchain | iOS | Install | Verdict |
|---|---|---|---|---|
| **PWA** | **none — just `npm run build`** | ✅ | Add to Home Screen / browser install prompt | ✅ **Chosen** |
| Capacitor (APK) | JDK 17 + Android Studio + SDK (~3 GB) | ❌ | sideload APK | ❌ rejected |
| React Native | Node + Android/iOS toolchain | ✅ | store or sideload | ❌ full UI rewrite, loses Framer Motion |

The PWA wraps **the same React build** as the web app — one codebase, zero extra UI work.
The Capacitor config was removed; say the word and it takes ~20 minutes to restore.

## What "installable" actually gives you

- Full-screen app (no browser chrome) via `display: standalone`
- Home-screen icon + splash screen
- **Works offline** — the service worker caches the shell and the last-known risk data
- **Push notifications** for Critical ward alerts (Android + iOS 16.4+)
- Deep links: `#/phone` (and `#/phone?ward=14`) open straight into the citizen brief
- **The phone app stays 2D.** The Operations dashboard's lazy CesiumJS globe is a separate
  chunk that the citizen route never imports, so the phone cold-open budget
  (`npm run budget`, < 120 KiB gzip) is unaffected by it. Keep it that way.

## Files — one source of truth

```
frontend/web/public/
├── manifest.webmanifest   # name, icons, theme, standalone display, shortcuts
├── sw.js                  # offline-first service worker + push handler
├── offline.html           # last-resort page when a navigation has no cache entry
├── icons/                 # 192 / 512 / maskable-512 / badge-72
└── data/                  # kolkata_wards.geojson — cached by sw.js for offline use
```

These live in the Vite **public** directory so they are served from the site root — `sw.js`
served from a subdirectory gets a restricted scope and silently does nothing. That's the #1
PWA bug. The old duplicate `frontend/pwa/` copy (a stale v1 manifest + worker) has been
**deleted**: two copies of `sw.js` meant one of them was always the wrong one to edit.

Registration is in `frontend/web/src/main.jsx` and is **production-only** on purpose
(`import.meta.env.PROD`): in dev, a cache-first worker fights Vite's HMR and you end up
debugging stale modules. Exercise the offline path with `npm run build && npm run preview`.

## Already wired (nothing to copy)

`index.html` links the manifest with **relative** paths (`./manifest.webmanifest`,
`./icons/...`) so a GitHub Pages subdirectory (`/Heatshield/`) keeps working; `main.jsx`
registers `./sw.js` with `scope: './'`. Icons are generated and committed in
`public/icons/`.

### Cache-bump discipline (do not skip)

`sw.js` serves the app shell **cache-first** — that is what makes a cold open on a phone
instant and survives airplane mode. The cost is that an installed app will happily serve
last month's build forever. Therefore:

> **Every release that changes shipped frontend code bumps `VERSION` in
> `frontend/web/public/sw.js`** (`heatshield-phone-v2` → `v3` → …).

The bump renames all three caches (shell/data/tiles), and the `activate` handler deletes
any cache that does not start with the current `VERSION`. That is the entire migration
path. Skip it and users stay on the old build until they clear site data by hand.

## Testing on a real phone

```bash
cd frontend/web
npm run build && npm run preview -- --host 0.0.0.0 --port 5173
```

- **Android (Chrome):** phone and laptop on the same Wi-Fi → open `http://<LAN-IP>:5173`
  → ⋮ menu → *Install app*. `localhost` will not work from the phone.
- **iOS (Safari):** Share → *Add to Home Screen*.
- **Lighthouse audit:** DevTools → Lighthouse → check *Progressive Web App*.
  Installable requires HTTPS or `localhost` — for LAN testing on Android, Chrome is
  lenient; for a real deploy use Render/Netlify/Vercel (free HTTPS).
- **Offline test:** install, then enable airplane mode and reopen — the last risk snapshot
  still renders.

## Honest limitations

| Limit | Impact | Workaround |
|---|---|---|
| Push notifications need HTTPS | LAN testing won't get push | Deploy to Render/Netlify (free) for the demo |
| iOS push only from a Home-Screen-installed app | Safari tab can't receive push | Prompt users to install |
| No Play Store listing | Judges must install via URL | One-tap install from the landing page |
| Background sync limited on iOS | Alerts may be slightly delayed | Local notifications when the app is open |
