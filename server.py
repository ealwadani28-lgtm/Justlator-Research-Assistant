from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import anthropic
import os
import time
import json
import threading
import urllib.request
import urllib.parse
from collections import defaultdict

# ── Static file protection ──────────────────────────────────────────────────
# Do NOT set static_folder to '.' (repo root) — that would expose server.py,
# .replit, replit.md and every other project file as public downloads.
app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024  # reject bodies > 1 MB

# ── CORS ─────────────────────────────────────────────────────────────────────
# Restrict to the Replit preview domain and localhost only.
_dev_domain = os.environ.get('REPLIT_DEV_DOMAIN', '')
_allowed_origins = ['http://localhost:5000', 'http://127.0.0.1:5000']
if _dev_domain:
    _allowed_origins.append(f'https://{_dev_domain}')
CORS(app, origins=_allowed_origins, supports_credentials=True)

# ── Simple in-memory rate limiter ─────────────────────────────────────────────
# Applied only on the server-billed path.
_rate_store: dict = defaultdict(list)
_RATE_WINDOW = 60   # seconds
_RATE_MAX    = 20   # requests per window per IP

def _rate_limit_ok(ip: str) -> bool:
    now = time.time()
    cutoff = now - _RATE_WINDOW
    hits = [t for t in _rate_store[ip] if t > cutoff]
    _rate_store[ip] = hits
    if len(hits) >= _RATE_MAX:
        return False
    _rate_store[ip].append(now)
    return True


def _replit_user_id() -> str:
    """Return the authenticated Replit user ID for this request, or ''.

    Replit's reverse proxy authenticates users and injects X-Replit-User-Id
    (and companion headers) into every request before forwarding to the app.
    This header is stripped from raw client requests by the proxy, so it
    cannot be spoofed by external callers. When running outside Replit's proxy
    (e.g. on localhost) the header is simply absent, which is safe.

    Enabling Replit Auth in the project settings is a prerequisite for this
    header to be present in production requests.
    """
    return request.headers.get('X-Replit-User-Id', '').strip()


@app.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


# ── Global impact stats (file-based, persists across restarts) ───────────────
_STATS_FILE = 'stats.json'
_STATS_LOCK = threading.Lock()
_STATS_DEFAULTS = {'visits': 0, 'papersGenerated': 0, 'wordsProduced': 0, 'sourcesAdded': 0}

# ── Replit Database helpers (persists across container resets) ────────────────
# REPLIT_DB_URL is injected by the Replit runtime. When absent (local dev) all
# _db_* calls are no-ops and we fall back to the JSON file.
_REPLIT_DB_URL = os.environ.get('REPLIT_DB_URL', '').rstrip('/')

_USER_STATS_DB_KEY = 'user_stats'


def _db_get(key: str) -> str | None:
    """GET a single key from Replit Database. Returns raw string or None."""
    if not _REPLIT_DB_URL:
        return None
    try:
        url = f'{_REPLIT_DB_URL}/{urllib.parse.quote(key, safe="")}'
        with urllib.request.urlopen(url, timeout=3) as r:
            return r.read().decode('utf-8')
    except Exception:
        return None


def _db_set(key: str, value: str) -> bool:
    """POST a key=value pair to Replit Database. Returns True on success."""
    if not _REPLIT_DB_URL:
        return False
    try:
        payload = urllib.parse.urlencode({key: value}).encode('utf-8')
        req = urllib.request.Request(_REPLIT_DB_URL, data=payload, method='POST')
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


# ── Per-user stats (Replit DB primary, JSON file fallback) ────────────────────
_USER_STATS_FILE = 'user_stats.json'
_USER_STATS_LOCK = threading.Lock()
_USER_STATS_DEFAULTS = {'papersGenerated': 0, 'wordsProduced': 0, 'tokensUsed': 0}


def _load_user_stats() -> dict:
    """Load all per-user stats. Prefers Replit DB; falls back to local file."""
    if _REPLIT_DB_URL:
        raw = _db_get(_USER_STATS_DB_KEY)
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
        # Replit DB is available but key is absent — check if the file has data
        # to migrate (happens the first time after switching to DB storage).
        try:
            with open(_USER_STATS_FILE, 'r') as f:
                migrated = json.load(f)
            if migrated:
                _db_set(_USER_STATS_DB_KEY, json.dumps(migrated))
            return migrated
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}
    # Local dev fallback: read from file.
    try:
        with open(_USER_STATS_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_user_stats(data: dict) -> None:
    """Persist all per-user stats to Replit DB when available, else to file."""
    if _REPLIT_DB_URL:
        _db_set(_USER_STATS_DB_KEY, json.dumps(data))
    else:
        with open(_USER_STATS_FILE, 'w') as f:
            json.dump(data, f)


def _get_user_stats(user_id: str) -> dict:
    all_stats = _load_user_stats()
    return {**_USER_STATS_DEFAULTS, **all_stats.get(user_id, {})}


def _update_user_stats(user_id: str, **increments) -> dict:
    """Atomically increment per-user counters and return updated stats."""
    with _USER_STATS_LOCK:
        all_stats = _load_user_stats()
        user = {**_USER_STATS_DEFAULTS, **all_stats.get(user_id, {})}
        for key, value in increments.items():
            if key in _USER_STATS_DEFAULTS:
                user[key] = user.get(key, 0) + value
        all_stats[user_id] = user
        _save_user_stats(all_stats)
        return user


def _load_stats() -> dict:
    try:
        with open(_STATS_FILE, 'r') as f:
            data = json.load(f)
        return {**_STATS_DEFAULTS, **{k: v for k, v in data.items() if k in _STATS_DEFAULTS}}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return dict(_STATS_DEFAULTS)


def _save_stats(stats: dict) -> None:
    with open(_STATS_FILE, 'w') as f:
        json.dump(stats, f)


@app.route('/api/stats', methods=['GET'])
def get_stats():
    with _STATS_LOCK:
        return jsonify(_load_stats())


@app.route('/api/track', methods=['POST'])
def track():
    data = request.get_json(silent=True) or {}
    event = (data.get('event') or '').strip()
    if event not in ('visit', 'paper', 'source'):
        return jsonify({'error': 'Unknown event'}), 400
    with _STATS_LOCK:
        stats = _load_stats()
        if event == 'visit':
            stats['visits'] += 1
        elif event == 'paper':
            stats['papersGenerated'] += 1
            try:
                words = max(0, int(data.get('words') or 0))
            except (ValueError, TypeError):
                words = 0
            if words > 0:
                stats['wordsProduced'] += words
        elif event == 'source':
            stats['sourcesAdded'] += 1
        _save_stats(stats)

    # Also update per-user stats for authenticated users.
    user_id = _replit_user_id()
    if user_id and event == 'paper':
        try:
            words = max(0, int(data.get('words') or 0))
        except (ValueError, TypeError):
            words = 0
        try:
            tokens = max(0, int(data.get('tokens') or 0))
        except (ValueError, TypeError):
            tokens = 0
        _update_user_stats(user_id, papersGenerated=1, wordsProduced=words, tokensUsed=tokens)

    return jsonify(stats)


@app.route('/')
def index():
    return send_file('index.html')


@app.route('/api/me', methods=['GET'])
def me():
    """Return the authenticated Replit user's name, id, and profile image.

    Reads proxy-injected headers that cannot be spoofed by external callers.
    Returns empty strings when running outside Replit's proxy or when the
    user is not signed in.
    """
    return jsonify({
        'name':         request.headers.get('X-Replit-User-Name', '').strip(),
        'id':           request.headers.get('X-Replit-User-Id', '').strip(),
        'profileImage': request.headers.get('X-Replit-User-Profile-Image', '').strip(),
    })


@app.route('/api/me/stats', methods=['GET'])
def me_stats():
    """Return personal usage stats for the currently authenticated user.

    Returns 404 when called without a valid Replit user session so the
    frontend can fall back to showing only global stats for anonymous visitors.
    """
    user_id = _replit_user_id()
    if not user_id:
        return jsonify({'error': 'Not authenticated'}), 404
    return jsonify(_get_user_stats(user_id))


@app.route('/api/config', methods=['GET'])
def config():
    """Tell the frontend whether the server-side API key is usable.

    The server key is only advertised as available when the current request
    comes from an authenticated Replit user (X-Replit-User-Id is set by
    Replit's proxy). Anonymous callers see hasServerKey=false and must supply
    their own Claude API key.
    """
    server_key = bool(os.environ.get('ANTHROPIC_API_KEY', '').strip())
    # Server key is only usable when the caller is authenticated via Replit Auth.
    has_server_key = server_key and bool(_replit_user_id())
    return jsonify({'hasServerKey': has_server_key})


def _get_api_key(data):
    """Return (api_key, is_server_key).

    The server-side ANTHROPIC_API_KEY is used only when the caller has been
    authenticated by Replit's proxy (X-Replit-User-Id header present).
    Anonymous callers use their own user-supplied key or receive a 400.
    """
    server_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if server_key and _replit_user_id():
        return server_key, True
    user_key = (data.get('apiKey') or '').strip()
    return user_key, False


# ── Input length caps ─────────────────────────────────────────────────────────
_MAX_TEXT   = 50_000   # humanize / similarity text fields
_MAX_TOPIC  =  2_000
_MAX_NOTES  =  5_000
_MAX_EXIST  = 50_000   # existing paper content


@app.route('/api/humanize', methods=['POST'])
def humanize():
    data = request.get_json() or {}
    api_key, is_server_key = _get_api_key(data)
    text = (data.get('text') or '').strip()

    if not api_key:
        return jsonify({'error': 'No API key configured. Please enter your Claude API key.'}), 400
    if not text:
        return jsonify({'error': 'Please paste some text to humanize'}), 400
    if len(text) > _MAX_TEXT:
        return jsonify({'error': f'Text is too long (max {_MAX_TEXT:,} characters).'}), 400
    if is_server_key and not _rate_limit_ok(request.remote_addr):
        return jsonify({'error': 'Too many requests. Please wait a moment and try again.'}), 429

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model='claude-3-5-haiku-20241022',
            max_tokens=4096,
            messages=[{
                'role': 'user',
                'content': (
                    'Rewrite the following AI-generated text to sound natural and '
                    'human-authored, suitable for academic writing. Preserve all the '
                    'meaning, arguments, and factual content exactly — just make it '
                    'read like a thoughtful researcher wrote it naturally.\n\n'
                    'Return only the rewritten text with no explanation or commentary.\n\n'
                    f'Text to humanize:\n{text}'
                )
            }]
        )
        return jsonify({
            'result': message.content[0].text,
            'inputTokens': message.usage.input_tokens,
            'outputTokens': message.usage.output_tokens
        })
    except anthropic.AuthenticationError:
        return jsonify({'error': 'Invalid API key. Please check your key at console.anthropic.com'}), 401
    except anthropic.RateLimitError:
        return jsonify({'error': 'Rate limit reached. Please wait a moment and try again'}), 429
    except Exception:
        return jsonify({'error': 'An unexpected error occurred. Please try again.'}), 500


@app.route('/api/write', methods=['POST'])
def write():
    data = request.get_json() or {}
    api_key, is_server_key = _get_api_key(data)
    topic    = (data.get('topic')    or '').strip()
    section  = (data.get('section')  or 'introduction')
    notes    = (data.get('notes')    or '').strip()
    sources  = data.get('sources') or []
    existing = (data.get('existing') or '').strip()

    if not api_key:
        return jsonify({'error': 'No API key configured. Please enter your Claude API key.'}), 400
    if not topic:
        return jsonify({'error': 'Please enter a research topic'}), 400
    if len(topic) > _MAX_TOPIC:
        return jsonify({'error': f'Topic is too long (max {_MAX_TOPIC:,} characters).'}), 400
    if len(notes) > _MAX_NOTES:
        return jsonify({'error': f'Notes are too long (max {_MAX_NOTES:,} characters).'}), 400
    if len(existing) > _MAX_EXIST:
        return jsonify({'error': f'Existing content is too long (max {_MAX_EXIST:,} characters).'}), 400
    if is_server_key and not _rate_limit_ok(request.remote_addr):
        return jsonify({'error': 'Too many requests. Please wait a moment and try again.'}), 429

    section_labels = {
        'fullpaper':   'Full Academic Paper (Introduction, Literature Review, Methodology, Analysis, and Conclusion)',
        'abstract':    'Abstract',
        'introduction':'Introduction',
        'literature':  'Literature Review',
        'methodology': 'Methodology',
        'analysis':    'Analysis and Findings',
        'conclusion':  'Conclusion'
    }
    section_label = section_labels.get(section, section.title())

    sources_block = ''
    if sources:
        lines = []
        for s in sources[:15]:
            lines.append(
                f'- {s.get("author", "")} ({s.get("year", "")}). '
                f'"{s.get("title", "")}" [{s.get("type", "")}]'
            )
        sources_block = '\n\nKnowledge Base Sources — incorporate relevant citations:\n' + '\n'.join(lines)

    existing_block = ''
    if existing:
        existing_block = f'\n\nExisting paper content (continue from here):\n---\n{existing[:3000]}\n---\n'

    notes_block = f'\nAdditional notes: {notes}' if notes else ''

    prompt = (
        f'Write a scholarly, well-structured {section_label} for a research paper '
        f'in Translation Studies on this topic:\n\n'
        f'Topic: {topic}{notes_block}{sources_block}{existing_block}\n\n'
        'Requirements:\n'
        '- Use formal academic language appropriate for Translation Studies scholarship\n'
        '- Include in-text citations in author-date format (e.g., Smith, 2020) where relevant\n'
        '- Structure the content with clear academic flow and argumentation\n'
        '- For a full paper: include all sections with clear headings\n'
        '- Aim for depth, scholarly rigor, and critical analysis\n'
        '- Return only the paper content — no meta-commentary or preamble'
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model='claude-3-5-haiku-20241022',
            max_tokens=8192,
            messages=[{'role': 'user', 'content': prompt}]
        )
        return jsonify({
            'result': message.content[0].text,
            'inputTokens': message.usage.input_tokens,
            'outputTokens': message.usage.output_tokens
        })
    except anthropic.AuthenticationError:
        return jsonify({'error': 'Invalid API key. Please check your key at console.anthropic.com'}), 401
    except anthropic.RateLimitError:
        return jsonify({'error': 'Rate limit reached. Please wait a moment and try again'}), 429
    except Exception:
        return jsonify({'error': 'An unexpected error occurred. Please try again.'}), 500


@app.route('/api/similarity', methods=['POST'])
def similarity():
    data = request.get_json() or {}
    api_key, is_server_key = _get_api_key(data)
    text1 = (data.get('text1') or '').strip()
    text2 = (data.get('text2') or '').strip()

    if not api_key:
        return jsonify({'error': 'No API key configured. Please enter your Claude API key.'}), 400
    if not text1 or not text2:
        return jsonify({'error': 'Please provide both texts to compare'}), 400
    if len(text1) > _MAX_TEXT or len(text2) > _MAX_TEXT:
        return jsonify({'error': f'Each text must be under {_MAX_TEXT:,} characters.'}), 400
    if is_server_key and not _rate_limit_ok(request.remote_addr):
        return jsonify({'error': 'Too many requests. Please wait a moment and try again.'}), 429

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model='claude-3-5-haiku-20241022',
            max_tokens=512,
            messages=[{
                'role': 'user',
                'content': (
                    'Analyze the similarity between these two texts.\n\n'
                    'Respond in exactly this format:\n'
                    'Similarity: [X]%\n'
                    'Analysis: [2-3 sentences explaining what overlaps, what differs, '
                    'and the nature of the similarity]\n\n'
                    f'Text 1:\n{text1[:3000]}\n\n'
                    f'Text 2:\n{text2[:3000]}'
                )
            }]
        )
        return jsonify({
            'result': message.content[0].text,
            'inputTokens': message.usage.input_tokens,
            'outputTokens': message.usage.output_tokens
        })
    except anthropic.AuthenticationError:
        return jsonify({'error': 'Invalid API key. Please check your key at console.anthropic.com'}), 401
    except anthropic.RateLimitError:
        return jsonify({'error': 'Rate limit reached. Please wait a moment and try again'}), 429
    except Exception:
        return jsonify({'error': 'An unexpected error occurred. Please try again.'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
