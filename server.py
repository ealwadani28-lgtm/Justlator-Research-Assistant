from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import anthropic
import os

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

@app.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/api/humanize', methods=['POST'])
def humanize():
    data = request.get_json()
    api_key = (data.get('apiKey') or '').strip()
    text = (data.get('text') or '').strip()

    if not api_key:
        return jsonify({'error': 'API key required'}), 400
    if not text:
        return jsonify({'error': 'Please paste some text to humanize'}), 400

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
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/write', methods=['POST'])
def write():
    data = request.get_json()
    api_key = (data.get('apiKey') or '').strip()
    topic = (data.get('topic') or '').strip()
    section = (data.get('section') or 'introduction')
    notes = (data.get('notes') or '').strip()
    sources = data.get('sources') or []
    existing = (data.get('existing') or '').strip()

    if not api_key:
        return jsonify({'error': 'API key required'}), 400
    if not topic:
        return jsonify({'error': 'Please enter a research topic'}), 400

    section_labels = {
        'fullpaper': 'Full Academic Paper (Introduction, Literature Review, Methodology, Analysis, and Conclusion)',
        'abstract': 'Abstract',
        'introduction': 'Introduction',
        'literature': 'Literature Review',
        'methodology': 'Methodology',
        'analysis': 'Analysis and Findings',
        'conclusion': 'Conclusion'
    }
    section_label = section_labels.get(section, section.title())

    sources_block = ''
    if sources:
        lines = []
        for s in sources[:15]:
            author = s.get('author', '')
            year = s.get('year', '')
            title = s.get('title', '')
            src_type = s.get('type', '')
            lines.append(f'- {author} ({year}). "{title}" [{src_type}]')
        sources_block = '\n\nKnowledge Base Sources — incorporate relevant citations from these:\n' + '\n'.join(lines)

    existing_block = ''
    if existing:
        existing_block = f'\n\nExisting paper content (continue from here):\n---\n{existing[:3000]}\n---\n'

    notes_block = f'\nAdditional notes: {notes}' if notes else ''

    prompt = (
        f'Write a scholarly, well-structured {section_label} for a research paper in Translation Studies on this topic:\n\n'
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
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/similarity', methods=['POST'])
def similarity():
    data = request.get_json()
    api_key = (data.get('apiKey') or '').strip()
    text1 = (data.get('text1') or '').strip()
    text2 = (data.get('text2') or '').strip()

    if not api_key:
        return jsonify({'error': 'API key required'}), 400
    if not text1 or not text2:
        return jsonify({'error': 'Please provide both texts to compare'}), 400

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
                    'Analysis: [2-3 sentences explaining what overlaps, what differs, and the nature of the similarity]\n\n'
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
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
