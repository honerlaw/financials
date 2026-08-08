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


@bp.app_context_processor
def inject_login_required_institutions():
    """Expose institutions needing re-auth to every template.

    Drives the reconnect banner in base.html. Skips the DB query entirely for
    unauthenticated requests (login page, future error pages).
    """
    if not session.get('authenticated'):
        return {'login_required_institutions': []}
    return {
        'login_required_institutions': Institution.query
        .filter_by(status='login_required')
        .order_by(Institution.name)
        .all()
    }


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


def _parse_iso(s):
    """Parse a 'YYYY-MM-DD' string to a date, or None if missing/invalid."""
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _table_date_bounds(args):
    """Effective (start, end_exclusive) date filter for the transactions table.

    A valid ?start=&end= window (from clicking a chart element) takes precedence
    over ?month=. Returns (None, None) when neither is set or valid — a
    malformed window falls back to the month filter rather than erroring.
    """
    start = _parse_iso(args.get('start'))
    end = _parse_iso(args.get('end'))
    if start and end and start < end:
        return start, end
    return _month_bounds(args.get('month', ''))


def _spending_context(institution_id, chart_month, today):
    """Daily spend series + weekly-budget rows for the dashboard spending section.

    Scoped to ``chart_month`` (the selected month, or the current month by
    default), honoring the institution filter. The transaction fetch is padded
    to full Sun–Sat week boundaries covering the month so edge weeks that
    straddle the month boundary are summed in full rather than undercounted.
    """
    from app.spending import daily_spend, weekly_budget, week_start, WEEKLY_BUDGET

    month_start, month_end = _month_bounds(chart_month)
    if month_start is None:
        # Malformed ?month= — fall back to the current month rather than 500,
        # matching the transactions table's tolerance of a bad month param.
        month_start, month_end = _month_bounds(today.strftime('%Y-%m'))
    span_start = week_start(month_start)
    span_end = week_start(month_end - timedelta(days=1)) + timedelta(days=7)

    query = Transaction.query.filter_by(removed=False).filter(
        Transaction.date >= span_start,
        Transaction.date < span_end,
    )
    if institution_id:
        query = query.filter_by(institution_id=institution_id)
    txns = query.all()

    spend_series = daily_spend(txns, month_start, month_end)
    spend_max = max((total for _, total in spend_series), default=0)
    spend_bars = [
        {
            'date': day,
            'total': total,
            'pct': int(total / spend_max * 100) if spend_max else 0,
        }
        for day, total in spend_series
    ]
    return {
        'spend_bars': spend_bars,
        'spend_max': spend_max,
        'month_total': sum((total for _, total in spend_series), 0),
        'budget_weeks': weekly_budget(txns, month_start, month_end, today),
        'weekly_budget': WEEKLY_BUDGET,
        'spending_month_label': month_start.strftime('%B %Y'),
    }


@bp.route('/')
@login_required
def index():
    institution_id = request.args.get('institution', type=int)
    month = request.args.get('month', '')
    filter_start, filter_end = _table_date_bounds(request.args)

    query = Transaction.query.filter_by(removed=False)
    if institution_id:
        query = query.filter_by(institution_id=institution_id)
    if filter_start is not None:
        query = query.filter(
            Transaction.date >= filter_start,
            Transaction.date < filter_end,
        )

    transactions = query.order_by(Transaction.date.desc()).paginate(
        page=1, per_page=50, error_out=False
    )
    institutions = Institution.query.order_by(Institution.name).all()
    account_totals = _account_totals(institution_id, filter_start, filter_end)

    # A ?start/?end window (chart click) drives a "Showing …" indicator above
    # the table; the spending chart itself stays scoped to the month.
    window_start = _parse_iso(request.args.get('start'))
    window_end = _parse_iso(request.args.get('end'))
    window_active = bool(window_start and window_end and window_start < window_end)
    window_label = None
    if window_active:
        last = window_end - timedelta(days=1)
        window_label = (
            window_start.strftime('%b %-d, %Y') if window_start == last
            else f"{window_start.strftime('%b %-d')} – {last.strftime('%b %-d, %Y')}"
        )

    today = date.today()
    spending = _spending_context(institution_id, month or today.strftime('%Y-%m'), today)
    return render_template(
        'index.html',
        transactions=transactions,
        week_groups=_group_by_week(transactions.items),
        institutions=institutions,
        selected_institution=institution_id,
        selected_month=month,
        account_totals=account_totals,
        today=today,
        window_active=window_active,
        window_label=window_label,
        selected_start=request.args.get('start') if window_active else None,
        **spending,
    )


@bp.route('/api/transactions')
@login_required
def transactions_json():
    page = request.args.get('page', 1, type=int)
    institution_id = request.args.get('institution', type=int)
    filter_start, filter_end = _table_date_bounds(request.args)

    query = Transaction.query.filter_by(removed=False)
    if institution_id:
        query = query.filter_by(institution_id=institution_id)
    if filter_start is not None:
        query = query.filter(
            Transaction.date >= filter_start,
            Transaction.date < filter_end,
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
            Account.next_payment_due_date.label('next_payment_due_date'),
            Account.last_statement_balance.label('last_statement_balance'),
            Account.minimum_payment_amount.label('minimum_payment_amount'),
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
            Account.next_payment_due_date, Account.last_statement_balance,
            Account.minimum_payment_amount,
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


@bp.route('/api/plaid/update_link_token/<int:institution_id>', methods=['POST'])
@login_required
def update_link_token(institution_id):
    """Create a Plaid Link token in update mode for an existing institution.

    Used by the reconnect flow to re-authenticate an Item that hit
    ITEM_LOGIN_REQUIRED, without creating a new Item.
    """
    from app.plaid_client import PlaidClient
    inst = db.session.get(Institution, institution_id)
    if inst is None:
        return jsonify({'error': 'Institution not found'}), 404
    client = PlaidClient(current_app.config)
    try:
        return jsonify({'link_token': client.create_update_link_token(inst.access_token)})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/api/plaid/reconnect/<int:institution_id>', methods=['POST'])
@login_required
def reconnect_institution(institution_id):
    """Mark an institution active again after a successful update-mode re-auth.

    Update mode keeps the existing access_token, so there is no token to
    exchange — we just clear the login_required state and kick a background
    sync to backfill the transactions missed while the Item was disconnected.
    For an already-active Item (re-connected to add the `liabilities` consent)
    the status write is a no-op and the sync is what pulls the newly-consented
    liability data.
    """
    from app.sync import sync_all_institutions
    inst = db.session.get(Institution, institution_id)
    if inst is None:
        return jsonify({'error': 'Institution not found'}), 404

    inst.status = 'active'
    db.session.commit()

    app = current_app._get_current_object()

    def run():
        with app.app_context():
            sync_all_institutions()

    threading.Thread(target=run, daemon=True).start()
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
