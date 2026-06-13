from functools import wraps
from datetime import date, datetime, timedelta, timezone
import threading

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, jsonify, current_app,
)

from app.models import db, Institution, Transaction, SyncLog, Account

bp = Blueprint('main', __name__)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('main.login'))
        return f(*args, **kwargs)
    return decorated


# ── Auth ──────────────────────────────────────────────────────────────────────

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == current_app.config['APP_PASSWORD']:
            session['authenticated'] = True
            return redirect(url_for('main.index'))
        return render_template('login.html', error='Incorrect password')
    return render_template('login.html', error=None)


@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('main.login'))


# ── Pages ─────────────────────────────────────────────────────────────────────

def _week_label(week_start):
    week_end = week_start + timedelta(days=6)
    if week_start.year != week_end.year:
        return f"{week_start.strftime('%b %-d, %Y')} – {week_end.strftime('%b %-d, %Y')}"
    if week_start.month != week_end.month:
        return f"{week_start.strftime('%b %-d')} – {week_end.strftime('%b %-d, %Y')}"
    return f"{week_start.strftime('%b %-d')}–{week_end.day}, {week_end.year}"


def _group_by_week(transactions):
    """Group an ordered list of transactions into (week_label, [txns]) pairs.

    Weeks run Sunday–Saturday. Input order is preserved within each group.
    """
    groups = {}
    order = []
    for txn in transactions:
        days_back = (txn.date.weekday() + 1) % 7
        week_start = txn.date - timedelta(days=days_back)
        if week_start not in groups:
            groups[week_start] = []
            order.append(week_start)
        groups[week_start].append(txn)
    return [(_week_label(ws), groups[ws]) for ws in order]


def _month_bounds(month):
    """Parse 'YYYY-MM' into (start_date, end_date_exclusive), or (None, None) on failure."""
    if not month:
        return None, None
    try:
        year, mon = int(month[:4]), int(month[5:7])
        next_year = year + 1 if mon == 12 else year
        next_mon = 1 if mon == 12 else mon + 1
        return date(year, mon, 1), date(next_year, next_mon, 1)
    except (ValueError, IndexError):
        return None, None


@bp.route('/')
@login_required
def index():
    institution_id = request.args.get('institution', type=int)
    month = request.args.get('month', '')
    month_start, month_end = _month_bounds(month)

    query = Transaction.query.filter_by(removed=False)
    if institution_id:
        query = query.filter_by(institution_id=institution_id)
    if month_start is not None:
        query = query.filter(
            Transaction.date >= month_start,
            Transaction.date < month_end,
        )

    transactions = query.order_by(Transaction.date.desc()).paginate(
        page=1, per_page=50, error_out=False
    )
    institutions = Institution.query.order_by(Institution.name).all()
    account_totals = _account_totals(institution_id, month_start, month_end)
    return render_template(
        'index.html',
        transactions=transactions,
        week_groups=_group_by_week(transactions.items),
        institutions=institutions,
        selected_institution=institution_id,
        selected_month=month,
        account_totals=account_totals,
    )


@bp.route('/api/transactions')
@login_required
def transactions_json():
    page = request.args.get('page', 1, type=int)
    institution_id = request.args.get('institution', type=int)
    month = request.args.get('month', '')
    month_start, month_end = _month_bounds(month)

    query = Transaction.query.filter_by(removed=False)
    if institution_id:
        query = query.filter_by(institution_id=institution_id)
    if month_start is not None:
        query = query.filter(
            Transaction.date >= month_start,
            Transaction.date < month_end,
        )

    pagination = query.order_by(Transaction.date.desc()).paginate(
        page=page, per_page=50, error_out=False
    )

    items = []
    for txn in pagination.items:
        items.append({
            'date': txn.date.strftime('%b %d, %Y'),
            'description': txn.description,
            'merchant_name': txn.merchant_name if txn.merchant_name and txn.merchant_name != txn.description else None,
            'institution_name': txn.institution.name,
            'amount': '%.2f' % abs(float(txn.amount)),
            'amount_sign': '-' if txn.amount > 0 else '+',
            'amount_class': 'text-danger' if txn.amount > 0 else 'text-success',
        })

    return jsonify({
        'items': items,
        'has_next': pagination.has_next,
        'next_page': pagination.next_num,
    })


def _account_totals(institution_id, month_start, month_end):
    """Per-(institution, account) totals honoring the same filters as the table.

    Accounts with no matching transactions still render with a $0.00 total so a
    freshly-linked account shows up immediately; filtering by institution hides
    accounts from other institutions.
    """
    txn_join = db.and_(
        Transaction.account_id == Account.plaid_account_id,
        Transaction.institution_id == Account.institution_id,
        Transaction.removed.is_(False),
    )
    if month_start is not None:
        txn_join = db.and_(
            txn_join,
            Transaction.date >= month_start,
            Transaction.date < month_end,
        )

    rows_query = (
        db.session.query(
            Institution.id.label('institution_id'),
            Institution.name.label('institution_name'),
            Account.id.label('account_id'),
            Account.name.label('account_name'),
            Account.mask.label('mask'),
            Account.current_balance.label('current_balance'),
            Account.iso_currency_code.label('iso_currency_code'),
            db.func.coalesce(db.func.sum(Transaction.amount), 0).label('total'),
            db.func.count(Transaction.id).label('txn_count'),
        )
        .select_from(Account)
        .join(Institution, Institution.id == Account.institution_id)
        .outerjoin(Transaction, txn_join)
        .group_by(
            Institution.id, Institution.name,
            Account.id, Account.name, Account.mask,
            Account.current_balance, Account.iso_currency_code,
        )
        .order_by(Institution.name, Account.name)
    )
    if institution_id:
        rows_query = rows_query.filter(Account.institution_id == institution_id)

    return rows_query.all()


@bp.route('/subscriptions')
@login_required
def subscriptions():
    from app.subscriptions import detect_subscriptions

    # Full in-memory load is the intended tradeoff at personal-finance
    # volumes. The removed=False filter here is a query optimization;
    # detect_subscriptions owns the removed-gate as its tested contract.
    transactions = Transaction.query.filter_by(removed=False).all()
    streams = detect_subscriptions(transactions, date.today())

    accounts = {a.plaid_account_id: a for a in Account.query.all()}
    institution_names = {i.id: i.name for i in Institution.query.all()}
    for stream in streams:
        labels = set()
        for institution_id, account_id in stream.pop('account_keys'):
            institution = institution_names.get(institution_id, '')
            account = accounts.get(account_id)
            labels.add(f'{institution} · {account.name}' if account else institution)
        stream['accounts'] = sorted(labels)

    active_count = sum(1 for s in streams if s['active'])
    return render_template(
        'subscriptions.html',
        streams=streams,
        active_count=active_count,
        inactive_count=len(streams) - active_count,
    )


@bp.route('/bills')
@login_required
def bills():
    from app.bills import detect_bills

    transactions = Transaction.query.filter_by(removed=False).all()
    bill_list = detect_bills(transactions, date.today())

    accounts = {a.plaid_account_id: a for a in Account.query.all()}
    institution_names = {i.id: i.name for i in Institution.query.all()}
    for bill in bill_list:
        labels = set()
        for institution_id, account_id in bill.pop('account_keys'):
            institution = institution_names.get(institution_id, '')
            account = accounts.get(account_id)
            labels.add(f'{institution} · {account.name}' if account else institution)
        bill['accounts'] = sorted(labels)

    paid_count = sum(1 for b in bill_list if b['payment_status'] == 'paid')
    unpaid_count = sum(1 for b in bill_list if b['payment_status'] == 'unpaid')
    upcoming_count = sum(1 for b in bill_list if b['payment_status'] == 'upcoming')
    return render_template(
        'bills.html',
        bills=bill_list,
        paid_count=paid_count,
        unpaid_count=unpaid_count,
        upcoming_count=upcoming_count,
    )


@bp.route('/settings')
@login_required
def settings():
    institutions = Institution.query.order_by(Institution.name).all()
    sync_logs = SyncLog.query.order_by(SyncLog.started_at.desc()).limit(50).all()
    return render_template('settings.html', institutions=institutions, sync_logs=sync_logs)


# ── Plaid API ─────────────────────────────────────────────────────────────────

@bp.route('/api/plaid/create_link_token', methods=['POST'])
@login_required
def create_link_token():
    from app.plaid_client import PlaidClient
    client = PlaidClient(current_app.config)
    try:
        return jsonify({'link_token': client.create_link_token()})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/api/plaid/exchange_token', methods=['POST'])
@login_required
def exchange_token():
    from app.plaid_client import PlaidClient
    client = PlaidClient(current_app.config)
    try:
        access_token, item_id, name, slug = client.exchange_token(
            request.json['public_token']
        )
        if Institution.query.filter_by(slug=slug).first():
            return jsonify({'error': f'{name} is already connected'}), 400

        inst = Institution(
            name=name, slug=slug,
            access_token=access_token, item_id=item_id,
        )
        db.session.add(inst)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return jsonify({'error': f'{name} is already connected'}), 400
        return jsonify({'name': name, 'id': inst.id})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/api/plaid/remove/<int:institution_id>', methods=['POST'])
@login_required
def remove_institution(institution_id):
    from app.plaid_client import PlaidClient
    inst = db.session.get(Institution, institution_id)
    if inst is None:
        return jsonify({'error': 'Institution not found'}), 404
    try:
        PlaidClient(current_app.config).remove_item(inst.access_token)
    except Exception:
        pass  # clean up locally even if Plaid call fails
    db.session.delete(inst)
    db.session.commit()
    return jsonify({'status': 'ok'})


# ── Sync API ──────────────────────────────────────────────────────────────────

@bp.route('/api/sync', methods=['POST'])
@login_required
def trigger_sync():
    from app.sync import sync_all_institutions
    app = current_app._get_current_object()

    def run():
        with app.app_context():
            sync_all_institutions()

    threading.Thread(target=run, daemon=True).start()
    return jsonify({'status': 'started'})


@bp.route('/api/sync/full', methods=['POST'])
@login_required
def trigger_full_resync():
    """Reset every active institution's Plaid cursor and run a sync.

    Pulls every transaction Plaid still has cached for each item (bounded by
    the per-link days_requested window set at link time). Existing rows are
    updated in place; the unique plaid_transaction_id prevents duplicates.
    """
    from app.sync import sync_all_institutions
    app = current_app._get_current_object()

    reset_count = 0
    for inst in Institution.query.filter_by(status='active').all():
        inst.plaid_cursor = ''
        reset_count += 1
    db.session.commit()

    def run():
        with app.app_context():
            sync_all_institutions()

    threading.Thread(target=run, daemon=True).start()
    return jsonify({'status': 'started', 'reset_count': reset_count})


@bp.route('/api/sync/status')
@login_required
def sync_status():
    last_log = SyncLog.query.order_by(SyncLog.started_at.desc()).first()
    institutions = Institution.query.order_by(Institution.name).all()
    return jsonify({
        'last_sync': last_log.started_at.isoformat() if last_log else None,
        'institutions': [
            {
                'id': i.id,
                'name': i.name,
                'status': i.status,
                'last_synced_at': i.last_synced_at.isoformat() if i.last_synced_at else None,
            }
            for i in institutions
        ],
    })
