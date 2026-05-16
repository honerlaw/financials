"""
One-time setup: connects bank accounts via Plaid Link and saves access tokens to .env.
Run this once per institution, and again whenever you want to add a new one.

Usage:
    python setup.py

Prerequisites:
    1. Sign up at https://dashboard.plaid.com (free)
    2. Copy your Client ID and Secret from Settings > API
    3. Create a .env file with PLAID_CLIENT_ID and PLAID_SECRET (see .env.example)
"""

import os
import re
import sys
import json
import threading
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request, render_template_string
from dotenv import load_dotenv, set_key
import plaid
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.item_get_request import ItemGetRequest
from plaid.model.institutions_get_by_id_request import InstitutionsGetByIdRequest

BASE_DIR = Path(__file__).parent
ENV_FILE = BASE_DIR / '.env'

load_dotenv(ENV_FILE)


def get_client():
    env = os.getenv('PLAID_ENV', 'development')
    host = plaid.Environment.Development if env == 'development' else plaid.Environment.Sandbox
    configuration = plaid.Configuration(
        host=host,
        api_key={
            'clientId': os.getenv('PLAID_CLIENT_ID'),
            'secret': os.getenv('PLAID_SECRET'),
        },
    )
    return plaid_api.PlaidApi(plaid.ApiClient(configuration))


def slugify(name):
    name = name.lower()
    name = re.sub(r'[^a-z0-9]+', '_', name)
    return name.strip('_')


app = Flask(__name__)
_plaid_client = None
_done = threading.Event()

HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Financial Sync Setup</title>
  <style>
    body { font-family: -apple-system, sans-serif; max-width: 560px; margin: 60px auto; padding: 0 24px; color: #1e293b; }
    h1 { font-size: 22px; margin-bottom: 6px; }
    p { color: #475569; line-height: 1.6; }
    button { padding: 12px 22px; font-size: 15px; cursor: pointer; border: none; border-radius: 8px; font-weight: 500; }
    #add-btn { background: #2563eb; color: white; }
    #add-btn:hover { background: #1d4ed8; }
    #done-btn { background: #16a34a; color: white; display: none; margin-top: 16px; }
    #done-btn:hover { background: #15803d; }
    .item { padding: 10px 14px; margin: 6px 0; background: #f0fdf4; border-left: 4px solid #16a34a; border-radius: 4px; }
    .error { color: #dc2626; margin-top: 8px; font-size: 14px; }
  </style>
</head>
<body>
  <h1>Financial Sync Setup</h1>
  <p>Connect each bank or credit card. Plaid opens a secure hosted window where you log in (including 2FA). Your credentials go directly to your bank — Plaid never stores them.</p>
  <p>After connecting all institutions, click <strong>Done</strong> to finish.</p>

  <div id="connected"></div>
  <div id="error"></div>

  <button id="add-btn" onclick="addInstitution()">+ Connect Institution</button>
  <br>
  <button id="done-btn" onclick="finish()">Done — finish setup</button>

  <script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
  <script>
    async function addInstitution() {
      document.getElementById('error').textContent = '';
      try {
        const res = await fetch('/create_link_token');
        const { link_token, error } = await res.json();
        if (error) { document.getElementById('error').textContent = 'Error: ' + error; return; }

        const handler = Plaid.create({
          token: link_token,
          onSuccess: async (public_token, metadata) => {
            const result = await fetch('/exchange_token', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ public_token }),
            });
            const info = await result.json();
            if (info.error) { document.getElementById('error').textContent = 'Error: ' + info.error; return; }

            const div = document.createElement('div');
            div.className = 'item';
            div.textContent = '✓ ' + info.name + ' connected (saved as ' + info.env_key + ')';
            document.getElementById('connected').appendChild(div);
            document.getElementById('done-btn').style.display = 'inline-block';
          },
          onExit: (err) => {
            if (err) document.getElementById('error').textContent = err.display_message || err.error_message || '';
          },
        });
        handler.open();
      } catch (e) {
        document.getElementById('error').textContent = e.message;
      }
    }

    async function finish() {
      await fetch('/done', { method: 'POST' });
      document.body.innerHTML = '<h1>Setup complete!</h1><p>Run <code>python sync.py</code> to pull your first transactions, or let the daily cron job handle it.</p>';
    }
  </script>
</body>
</html>"""


@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/create_link_token')
def create_link_token():
    try:
        response = _plaid_client.link_token_create(
            LinkTokenCreateRequest(
                products=[Products('transactions')],
                client_name='Financial Sync',
                country_codes=[CountryCode('US')],
                language='en',
                user=LinkTokenCreateRequestUser(client_user_id='local-user'),
            )
        )
        return jsonify({'link_token': response.link_token})
    except plaid.ApiException as e:
        body = json.loads(e.body)
        return jsonify({'error': body.get('error_message', str(e))}), 400


@app.route('/exchange_token', methods=['POST'])
def exchange_token():
    try:
        public_token = request.json['public_token']

        exchange_resp = _plaid_client.item_public_token_exchange(
            ItemPublicTokenExchangeRequest(public_token=public_token)
        )
        access_token = exchange_resp.access_token

        item_resp = _plaid_client.item_get(ItemGetRequest(access_token=access_token))
        institution_id = item_resp.item.institution_id

        inst_resp = _plaid_client.institutions_get_by_id(
            InstitutionsGetByIdRequest(
                institution_id=institution_id,
                country_codes=[CountryCode('US')],
            )
        )
        institution_name = inst_resp.institution.name
        slug = slugify(institution_name)
        env_key = f'PLAID_TOKEN_{slug.upper()}'

        set_key(str(ENV_FILE), env_key, access_token)
        print(f'  Saved {env_key}')

        return jsonify({'name': institution_name, 'env_key': env_key, 'slug': slug})
    except plaid.ApiException as e:
        body = json.loads(e.body)
        return jsonify({'error': body.get('error_message', str(e))}), 400


@app.route('/done', methods=['POST'])
def done():
    _done.set()
    return jsonify({'status': 'ok'})


def main():
    global _plaid_client

    if not os.getenv('PLAID_CLIENT_ID') or not os.getenv('PLAID_SECRET'):
        print('Error: PLAID_CLIENT_ID and PLAID_SECRET must be set in .env')
        print('Get them at https://dashboard.plaid.com/developers/keys')
        sys.exit(1)

    _plaid_client = get_client()

    url = 'http://localhost:8080'
    print(f'Starting setup server at {url}')
    print('Your browser will open automatically. Connect each institution, then click Done.')
    print('Press Ctrl+C to exit if needed.\n')

    server = threading.Thread(
        target=lambda: app.run(port=8080, debug=False, use_reloader=False),
        daemon=True,
    )
    server.start()

    threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    _done.wait()
    print('\nSetup complete. Run: python sync.py')


if __name__ == '__main__':
    main()
