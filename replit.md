# Replit Justlator

## Overview
Justlator — a Translation Studies Research Assistant web app with AI-powered tools for academic researchers.

## Project Architecture
- `index.html`: Main app file (served as root). Contains the full React app, landing page, and all feature tabs.
- `server.py`: **Flask** server (port 5000). Serves index.html and provides 3 AI proxy endpoints.
- `requirements.txt`: Python dependencies — flask, anthropic, flask-cors.

## AI Integration
- server.py provides POST endpoints: `/api/humanize`, `/api/write`, `/api/similarity`
- All endpoints accept the user's own Claude API key in the request body (`apiKey` field)
- Uses `claude-3-5-haiku-20241022` model
- No server-side API key needed — users provide their own key (stored in localStorage)
- Key is stored in localStorage as `justlator-claude-key`

## Features
- Knowledge Base with source management and Citation Generator (APA/MLA/Chicago)
- AI Humanizer (real Claude integration — user brings own key)
- Paper Writer (real Claude integration — uses Knowledge Base sources as context)
- Similarity Checker (real Claude integration)
- Translation Glossary with sort/filter, CSV/TBX export/import
- Seasonal theme switcher (Auto-Season mode)
- Usage/cost meter (tracks tokens/cost per session)
- RTL/Arabic support

## Recent Changes
- Task #15: Connected all 3 AI tools to real Claude API via Flask backend proxy
- server.py upgraded from SimpleHTTPRequestHandler to Flask
- Users enter their own Claude API key once (saved to localStorage, persists across sessions)
- Task #13: Added persistent draft summary bar in Paper Writer header
- Task #12 (merged): Glossary sort and filter by domain/language pair
