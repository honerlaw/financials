"""
Daily transaction sync: pulls new/changed transactions from all connected institutions
and writes them to monthly CSV files under data/{institution}/{YYYY-MM}.csv.

Usage:
    python sync.py

Cron (runs at 7am daily):
    0 7 * * * /path/to/venv/bin/python /Users/derekhonerlaw/Development/financials/sync.py >> sync.log 2>&1
"""

import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
import plaid
from plaid.api import plaid_api
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.model.transactions_sync_request_options import TransactionsSyncRequestOptions

BASE_DIR = Path(__file__).parent
ENV_FILE = BASE_DIR / '.env'
CURSORS_FILE = BASE_DIR / 'cursors.json'
DATA_DIR = BASE_DIR / 'data'

CSV_HEADERS = ['date', 'description', 'merchant_name', 'amount', 'category',
               'institution', 'account_id', 'transaction_id', 'removed']

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


def load_cursors():
    if CURSORS_FILE.exists():
        return json.loads(CURSORS_FILE.read_text())
    return {}


def save_cursors(cursors):
    CURSORS_FILE.write_text(json.dumps(cursors, indent=2))


def institution_slug(env_key):
    return env_key.replace('PLAID_TOKEN_', '').lower()


def txn_to_row(txn, slug):
    category = ''
    if getattr(txn, 'personal_finance_category', None):
        category = txn.personal_finance_category.primary
    elif getattr(txn, 'category', None):
        category = txn.category[0] if txn.category else ''

    return {
        'date': str(txn.date),
        'description': txn.name or '',
        'merchant_name': txn.merchant_name or '',
        'amount': txn.amount,
        'category': category,
        'institution': slug,
        'account_id': txn.account_id,
        'transaction_id': txn.transaction_id,
        'removed': '',
    }


def load_month_rows(csv_path):
    """Returns dict of transaction_id -> row for an existing CSV, or empty dict."""
    if not csv_path.exists():
        return {}
    with open(csv_path, newline='') as f:
        return {row['transaction_id']: row for row in csv.DictReader(f)}


def write_month_rows(csv_path, rows_by_id):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    sorted_rows = sorted(rows_by_id.values(), key=lambda r: r['date'])
    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows(sorted_rows)


def apply_added(slug, transactions):
    """Upserts added/modified transactions into monthly CSVs. Returns count of new rows."""
    by_month = {}
    for txn in transactions:
        month = str(txn.date)[:7]
        by_month.setdefault(month, []).append(txn)

    new_count = 0
    for month, txns in by_month.items():
        csv_path = DATA_DIR / slug / f'{month}.csv'
        rows = load_month_rows(csv_path)
        for txn in txns:
            if txn.transaction_id not in rows:
                new_count += 1
            rows[txn.transaction_id] = txn_to_row(txn, slug)
        write_month_rows(csv_path, rows)

    return new_count


def apply_removed(slug, removed_transactions):
    """Marks removed transactions in CSVs. Returns count marked."""
    if not removed_transactions:
        return 0

    removed_ids = {r.transaction_id for r in removed_transactions}
    inst_dir = DATA_DIR / slug
    if not inst_dir.exists():
        return 0

    marked = 0
    for csv_path in inst_dir.glob('*.csv'):
        rows = load_month_rows(csv_path)
        changed = False
        for txn_id, row in rows.items():
            if txn_id in removed_ids and row.get('removed') != 'true':
                row['removed'] = 'true'
                changed = True
                marked += 1
        if changed:
            write_month_rows(csv_path, rows)

    return marked


def sync_institution(client, env_key, access_token, cursors):
    slug = institution_slug(env_key)
    cursor = cursors.get(env_key, '')
    added = []
    modified = []
    removed = []

    try:
        while True:
            response = client.transactions_sync(
                TransactionsSyncRequest(
                    access_token=access_token,
                    cursor=cursor,
                    options=TransactionsSyncRequestOptions(
                        include_personal_finance_category=True,
                    ),
                )
            )
            added.extend(response.added)
            modified.extend(response.modified)
            removed.extend(response.removed)
            cursor = response.next_cursor
            if not response.has_more:
                break

    except plaid.ApiException as e:
        body = json.loads(e.body)
        code = body.get('error_code', '')
        if code == 'ITEM_LOGIN_REQUIRED':
            print(f'  [{slug}] Re-authentication required — run setup.py to reconnect this institution')
        else:
            print(f'  [{slug}] Plaid error {code}: {body.get("error_message", "")}')
        return cursors.get(env_key, '')

    new_count = apply_added(slug, added + modified)
    removed_count = apply_removed(slug, removed)
    print(f'  [{slug}] {new_count} new, {removed_count} removed')

    return cursor


def main():
    if not os.getenv('PLAID_CLIENT_ID') or not os.getenv('PLAID_SECRET'):
        print('Error: PLAID_CLIENT_ID and PLAID_SECRET must be set in .env')
        sys.exit(1)

    tokens = {k: v for k, v in os.environ.items() if k.startswith('PLAID_TOKEN_')}
    if not tokens:
        print('No institutions connected. Run setup.py first.')
        sys.exit(1)

    client = get_client()
    cursors = load_cursors()

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    print(f'[{timestamp}] Syncing {len(tokens)} institution(s)...')

    for env_key, access_token in sorted(tokens.items()):
        new_cursor = sync_institution(client, env_key, access_token, cursors)
        cursors[env_key] = new_cursor
        save_cursors(cursors)

    print('Done.')


if __name__ == '__main__':
    main()
