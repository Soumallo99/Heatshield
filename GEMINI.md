# Gemini / Antigravity

This project's full context — architecture, physics formulas, invariants, hard constraints,
known gaps and the PR checklist — lives in **[AGENTS.md](AGENTS.md)**.

**Read `AGENTS.md` before making any change.** It is the single source of truth; this file is
only a pointer, so don't duplicate its content here.

Antigravity notes: the marketplace is **Open VSX**, so Pylance and Dev Containers are
unavailable — `detachhead.basedpyright` is used instead. Full steps in
**[ANTIGRAVITY.md](ANTIGRAVITY.md)**.

```bash
pip install -r requirements.txt && cd frontend/web && npm install && cd ../..
./start.sh          # dashboard :5173 · API :8000 · docs :8000/docs
python -m pytest tests -q     # expect: 52 passed
```
