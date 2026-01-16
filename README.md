# cbz-doctor

## Agent and Logs

- Agent profile: `AGENTS.md`
- Logs (local-only): `CONVERSATION.md`, `BOOKMARKS.md`, `Action-Log.md` (when present)


Validate/repair CBZ archives and ComicInfo.xml; can emit Metron XML.

## Quickstart
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Action Log
- 2025-10-19 — Initialized repository skeleton (MIT, Python 3 only).

## Appendix: Directory Structure — cbz-doctor

<!-- BEGIN DIR TREE -->
```
cbz-doctor
├── cbz_doctor
│   ├── __init__.py
│   └── cli.py
├── LICENSE
├── Makefile
├── README.md
└── requirements.txt
```
<!-- END DIR TREE -->
