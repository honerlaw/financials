from datetime import datetime, timezone
from decimal import Decimal
import json
import plaid
from flask import current_app
from app.models import db, Institution, Transaction, SyncLog
from app.plaid_client import PlaidClient


def _get_plaid_error_code(api_exception):
    """Extract error_code from a plaid.ApiException without touching the mocked class."""
    try:
        return json.loads(api_exception.body).get('error_code', '')
    except Exception:
        return ''


def _utcnow():
    return datetime.now(timezone.utc)


def sync_all_institutions():
    """Sync all active institutions. Must be called within an app context."""
    config = current_app.config
    client = PlaidClient(config)
    institutions = Institution.query.filter_by(status='active').all()
    for institution in institutions:
        _sync_institution(client, institution)


def _sync_institution(client, institution):
    log = SyncLog(institution_id=institution.id, started_at=_utcnow())
    db.session.add(log)

    try:
        added, modified, removed, new_cursor = client.sync_transactions(
            institution.access_token, institution.plaid_cursor
        )
        added_count = _upsert_transactions(institution.id, added + modified)
        removed_count = _mark_removed(removed)

        institution.plaid_cursor = new_cursor
        institution.last_synced_at = _utcnow()
        institution.status = 'active'

        log.completed_at = _utcnow()
        log.added_count = added_count
        log.removed_count = removed_count

    except plaid.ApiException as e:
        code = _get_plaid_error_code(e)
        if code == 'ITEM_LOGIN_REQUIRED':
            institution.status = 'login_required'
        log.error = f'{code}: {e}'

    db.session.commit()


def _upsert_transactions(institution_id, transactions):
    new_count = 0
    for txn in transactions:
        category = ''
        if getattr(txn, 'personal_finance_category', None):
            category = txn.personal_finance_category.primary
        elif getattr(txn, 'category', None):
            category = txn.category[0] if txn.category else ''

        existing = Transaction.query.filter_by(
            plaid_transaction_id=txn.transaction_id
        ).first()

        if existing:
            existing.description = txn.name or ''
            existing.merchant_name = txn.merchant_name or ''
            existing.amount = Decimal(str(txn.amount))
            existing.category = category
            existing.removed = False
            existing.updated_at = _utcnow()
        else:
            db.session.add(Transaction(
                plaid_transaction_id=txn.transaction_id,
                institution_id=institution_id,
                account_id=txn.account_id,
                date=txn.date,
                description=txn.name or '',
                merchant_name=txn.merchant_name or '',
                amount=Decimal(str(txn.amount)),
                category=category,
            ))
            new_count += 1

    return new_count


def _mark_removed(removed_transactions):
    count = 0
    for removed_txn in removed_transactions:
        txn = Transaction.query.filter_by(
            plaid_transaction_id=removed_txn.transaction_id
        ).first()
        if txn and not txn.removed:
            txn.removed = True
            txn.updated_at = _utcnow()
            count += 1
    return count
