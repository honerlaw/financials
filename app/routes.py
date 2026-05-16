from functools import wraps
from datetime import date, datetime, timezone
import threading

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, jsonify, current_app,
)

from app.models import db, Institution, Transaction, SyncLog

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

@bp.route('/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    institution_id = request.args.get('institution', type=int)
    month = request.args.get('month', '')

    query = Transaction.query.filter_by(removed=False)
    if institution_id:
        query = query.filter_by(institution_id=institution_id)
    if month:
        try:
            year, mon = int(month[:4]), int(month[5:7])
            next_year = year + 1 if mon == 12 else year
            next_mon = 1 if mon == 12 else mon + 1
            query = query.filter(
                Transaction.date >= date(year, mon, 1),
                Transaction.date < date(next_year, next_mon, 1),
            )
        except (ValueError, IndexError):
            pass

    transactions = query.order_by(Transaction.date.desc()).paginate(
        page=page, per_page=50, error_out=False
    )
    institutions = Institution.query.order_by(Institution.name).all()
    return render_template(
        'index.html',
        transactions=transactions,
        institutions=institutions,
        selected_institution=institution_id,
        selected_month=month,
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
