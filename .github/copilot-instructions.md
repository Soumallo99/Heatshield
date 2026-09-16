# GitHub Copilot

This repository's full context — architecture, physics formulas, invariants, hard constraints,
known gaps and the PR checklist — lives in **[../AGENTS.md](../AGENTS.md)**.

**Read `AGENTS.md` before suggesting or making any change.** It is the single source of truth;
this file is only a pointer, so don't duplicate its content here.

Project in one line: HeatShield turns an open weather forecast into **ward-level heat-health
warnings** for 141 Kolkata wards (forecast → WBGT/Heat Index physics → UHI adjustment →
vulnerability-weighted risk → SMS alert copy with 2–5 day lead).

Non-negotiables when suggesting code:

- Never fabricate data. Population 60+ and slum share are **deliberately absent**.
- PWA only — no Capacitor, no APK, no Android/Gradle tooling.
- WBGT drives the model; Heat Index is for public-facing copy. Both stay.
- Keep the UI motion quality high (spring physics, staggered entrances,
  `prefers-reduced-motion`, transform/opacity only).
- `python -m pytest tests -q` must stay at **52 passed**.
