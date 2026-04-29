from flask import Flask, request, jsonify, send_file, session
from flask_cors import CORS
import anthropic
import os
import secrets
import time
from collections import defaultdict

# ── Static file protection ──────────────────────────────────────────────────
# Do NOT set static_folder to '.' (repo root) — that would expose server.py,
# .replit, replit.md and every other project file as public downloads.
app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024  # reject bodies > 1 MB

# ── Session secret ────────────────────────────────────────────────────────────
# If FLASK_SECRET_KEY is set in the environment, use it (survives restarts).
# Otherwise generate a fresh random key — sessions issued before a restart
# will be invalid, which is acceptable for this app's usage pattern.
app.secret_key = os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32)

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


@app.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/')
def index():
    """Serve the app and establish a signed server-side session on first load.

    The session acts as the credential that proves a request came from a real
    browser that loaded the UI.  Without a valid session the server-side
    ANTHROPIC_API_KEY is never used, so anonymous HTTP clients (curl/bots)
    cannot spend server credits even when they know the endpoint URLs.
    """
    if 'sid' not in session:
        session['sid'] = secrets.token_hex(16)
        session.permanent = False  # expires when the browser tab is closed
    return send_file('index.html')


def _has_valid_session() -> bool:
    """Return True only when the request carries a valid signed session cookie."""
    return bool(session.get('sid'))


@app.route('/api/config', methods=['GET'])
def config():
    """Tell the frontend whether a server-side API key is configured."""
    has_server_key = bool(os.environ.get('ANTHROPIC_API_KEY', '').strip())
    return jsonify({'hasServerKey': has_server_key})


def _get_api_key(data):
    """
    Return (api_key, is_server_key).

    Server-side ANTHROPIC_API_KEY is used only when the caller has a valid
    signed session (i.e. loaded the page through the Flask app).  Without a
    session the server key is never used; the call either uses the user's own
    API key or fails with 'no key configured'.
    """
    server_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if server_key and _has_valid_session():
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
