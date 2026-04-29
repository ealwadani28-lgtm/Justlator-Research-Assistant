# Replit Justlator

## Overview
Justlator — a Translation Studies Research Assistant web app with AI-powered tools for academic researchers.

## Project Architecture
- `index.html`: Main app file (served as root). Contains the full React app, landing page, and all feature tabs.
- `server.py`: **Flask** server (port 5000). Serves index.html and provides 4 endpoints.
- `requirements.txt`: Python dependencies — flask, anthropic, flask-cors.

## AI Integration
- server.py provides:
  - `GET /api/config` — tells frontend if server has `ANTHROPIC_API_KEY` set
  - `POST /api/humanize` — humanizes AI-generated academic text
  - `POST /api/write` — generates paper sections using Knowledge Base sources as context
  - `POST /api/similarity` — compares two texts and returns a similarity % + analysis
- Uses `claude-3-5-haiku-20241022` model
- **Hybrid API key policy**:
  - Priority 1: `ANTHROPIC_API_KEY` environment variable (server-side, silent, no UI prompt)
  - Priority 2: User-provided key sent in request body (`apiKey` field)
- If server has a key, frontend shows "✓ AI ready" and skips the key input UI
- User-provided key is stored in **sessionStorage** as `justlator-claude-key` (not localStorage — clears when the browser tab closes)

## Features
- Knowledge Base with source management and Citation Generator (APA/MLA/Chicago)
- AI Humanizer (real Claude integration — hybrid key: server env or user BYOK)
- Paper Writer (real Claude integration — uses Knowledge Base sources as context)
- Similarity Checker (real Claude integration)
- Translation Glossary with sort/filter, CSV/TBX export/import
- Seasonal theme switcher (Auto-Season mode)
- Usage/cost meter (tracks tokens/cost per session)
- RTL/Arabic support

## Recent Changes
- Task #15: Connected all 3 AI tools to real Claude API via Flask backend proxy
  - server.py upgraded from SimpleHTTPRequestHandler to Flask
  - Hybrid key model: ANTHROPIC_API_KEY env var takes priority; falls back to user-provided key
  - /api/config endpoint tells frontend whether server key is configured
  - User key stored in sessionStorage (tab-session only); shows "AI ready" if server key present
  - Generic 500 errors use a safe message (no internal exception strings leaked)
- Task #13: Added persistent draft summary bar in Paper Writer header
- Task #12 (merged): Glossary sort and filter by domain/language pair
