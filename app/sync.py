from datetime import date, datetime, timezone
from decimal import Decimal
import json
import plaid
from flask import current_app
from app.models import db, Institution, Transaction, SyncLog, Account
from app.plaid_client import PlaidClient


def _get_plaid_error_code(api_exception):
    """Extract error_code from a plaid.ApiException without touching the mocked class."""
    try:
        return json.loads(api_exception.body).get('error_code', '')
    except Exception:
        return ''


def _utcnow():
    return datetime.now(timezone.utc)


def run_daily_sync():
    """The 7am scheduled job: sync everything, then text the daily digest.

    This is the ONLY path that notifies. The sync `/api/sync` kicks off on every
    dashboard page load calls ``sync_all_institutions`` directly and stays
    silent, so the digest lands at a predictable hour instead of whenever the
    dashboard is next opened. Syncing first means the balances in the text are
    as fresh as Plaid can make them.
    """
    sync_all_institutions()
    _send_daily_digest_safe()


def sync_all_institutions():
    """Sync all active institutions. Must be called within an app context."""
    config = current_app.config
    client = PlaidClient(config)
    institutions = Institution.query.filter_by(status='active').all()
    for institution in institutions:
        _sync_institution(client, institution)


def _send_daily_digest_safe():
    """Send the daily digest SMS, non-fatally.

    A notification failure must never abort the sync (mirrors the non-fatal
    _refresh_balances contract). The notifier already swallows per-send errors;
    this guards any other failure (e.g. the DB query) so it only annotates the
    log.
    """
    try:
        # Imported inside the try so even an import-time failure in the
        # notification path (or its transitive imports) is non-fatal.
        from app.localtime import local_today
        from app.notifications import send_daily_digest
        send_daily_digest(
            db.session, local_today(current_app.config), current_app.config,
        )
    except Exception:
        current_app.logger.exception('daily digest dispatch failed')


def _sync_institution(client, institution):
    log = SyncLog(institution_id=institution.id, started_at=_utcnow())
    db.session.add(log)

    try:
        added, modified, removed, new_cursor, accounts = client.sync_transactions(
            institution.access_token, institution.plaid_cursor
        )
        added_count = _upsert_transactions(institution.id, added + modified)
        removed_count = _mark_removed(removed)
        _upsert_accounts(institution.id, accounts)

        # Force-refresh balances via the dedicated Plaid endpoint, then pull
        # liability details (due dates / statement balances). Both are
        # best-effort: a failure annotates the SyncLog but does not abort the
        # sync — the transactions above have already landed.
        errors = []
        balance_error = _refresh_balances(client, institution)
        if balance_error:
            errors.append(balance_error)
        liability_error = _refresh_liabilities(client, institution)
        if liability_error:
            errors.append(liability_error)
        if errors:
            log.error = '; '.join(errors)

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


def _refresh_balances(client, institution):
    """Force-refresh real-time balances via Plaid's accounts/balance/get.

    Returns an error string to record on the SyncLog if the call fails,
    None on success. Never re-raises — balance refresh failures are
    non-fatal to the sync.
    """
    try:
        accounts = client.get_balances(institution.access_token)
    except plaid.ApiException as e:
        code = _get_plaid_error_code(e)
        return f'balance refresh failed: {code}: {e}'

    for acct in accounts:
        balances = getattr(acct, 'balances', None)
        if balances is None:
            continue
        row = Account.query.filter_by(plaid_account_id=acct.account_id).first()
        if row is None:
            continue
        row.current_balance = _to_decimal(getattr(balances, 'current', None))
        row.available_balance = _to_decimal(getattr(balances, 'available', None))
        iso = getattr(balances, 'iso_currency_code', None)
        if iso:
            row.iso_currency_code = iso
        row.last_synced_at = _utcnow()
    return None


# Liability error codes that are expected/normal, not worth annotating a
# SyncLog with: the Item was never consented to the `liabilities` product
# (every Item linked before this feature), or it simply has no credit/loan
# accounts. Treated as a no-op refresh rather than an error.
#
# ADDITIONAL_CONSENT_REQUIRED is the code Plaid actually returns for a
# never-consented Item — it is the common case for every Item linked before
# liabilities was added as an additional consented product, so it would
# otherwise annotate every institution on every sync. The remedy is for the
# user to re-connect the institution (Plaid update mode now requests the
# liabilities consent); until then the liability columns simply stay null.
_BENIGN_LIABILITY_ERROR_CODES = frozenset({
    'ADDITIONAL_CONSENT_REQUIRED',
    'PRODUCTS_NOT_SUPPORTED',
    'NO_LIABILITY_ACCOUNTS',
    'NO_ACCOUNTS',
})


def _refresh_liabilities(client, institution):
    """Populate credit/loan due dates & statement balances via liabilities/get.

    Returns an error string to record on the SyncLog for *unexpected* failures,
    or None on success — including the benign "this Item has no liabilities"
    responses that are normal for depository-only or non-consented Items. Never
    re-raises; like balance refresh, liability refresh is non-fatal to the sync.
    """
    try:
        liabilities = client.get_liabilities(institution.access_token)
    except plaid.ApiException as e:
        code = _get_plaid_error_code(e)
        if code in _BENIGN_LIABILITY_ERROR_CODES:
            return None
        return f'liability refresh failed: {code}: {e}'

    if liabilities is None:
        return None

    now = _utcnow()
    groups = (
        getattr(liabilities, 'credit', None) or [],
        getattr(liabilities, 'student', None) or [],
        getattr(liabilities, 'mortgage', None) or [],
    )
    for group in groups:
        for entry in group:
            account_id = getattr(entry, 'account_id', None)
            if not account_id:
                continue
            row = Account.query.filter_by(plaid_account_id=account_id).first()
            if row is None:
                continue
            row.next_payment_due_date = _to_date(getattr(entry, 'next_payment_due_date', None))
            row.last_statement_balance = _to_decimal(getattr(entry, 'last_statement_balance', None))
            # Mortgages express the amount owed as next_monthly_payment rather
            # than a minimum_payment_amount; fall back to it so every liability
            # type surfaces an amount due.
            minimum = getattr(entry, 'minimum_payment_amount', None)
            if minimum is None:
                minimum = getattr(entry, 'next_monthly_payment', None)
            row.minimum_payment_amount = _to_decimal(minimum)
            row.last_synced_at = now
    return None


def _to_jsonable(value):
    """Recursively convert Plaid SDK model objects to plain JSON-able dicts."""
    if value is None:
        return None
    if hasattr(value, 'to_dict'):
        return _to_jsonable(value.to_dict())
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _extract_fields(txn):
    """Pull every column we persist out of a Plaid Transaction object."""
    pfc = getattr(txn, 'personal_finance_category', None)
    category = ''
    category_detailed = None
    category_confidence = None
    if pfc is not None:
        category = getattr(pfc, 'primary', '') or ''
        category_detailed = getattr(pfc, 'detailed', None)
        category_confidence = getattr(pfc, 'confidence_level', None)
    elif getattr(txn, 'category', None):
        category = txn.category[0] if txn.category else ''

    txn_code = getattr(txn, 'transaction_code', None)
    if txn_code is not None and hasattr(txn_code, 'value'):
        txn_code = txn_code.value

    return {
        'account_id': txn.account_id,
        'date': txn.date,
        'authorized_date': getattr(txn, 'authorized_date', None),
        'description': txn.name or '',
        'original_description': getattr(txn, 'original_description', None),
        'merchant_name': txn.merchant_name or '',
        'merchant_entity_id': getattr(txn, 'merchant_entity_id', None),
        'website': getattr(txn, 'website', None),
        'amount': Decimal(str(txn.amount)),
        'iso_currency_code': getattr(txn, 'iso_currency_code', None),
        'category': category,
        'category_detailed': category_detailed,
        'category_confidence': category_confidence,
        'payment_channel': getattr(txn, 'payment_channel', None),
        'transaction_code': txn_code,
        'check_number': getattr(txn, 'check_number', None),
        'account_owner': getattr(txn, 'account_owner', None),
        'pending': bool(getattr(txn, 'pending', False)),
        'pending_transaction_id': getattr(txn, 'pending_transaction_id', None),
        'location': _to_jsonable(getattr(txn, 'location', None)),
        'counterparties': _to_jsonable(getattr(txn, 'counterparties', None)),
    }


def _upsert_transactions(institution_id, transactions):
    new_count = 0
    for txn in transactions:
        fields = _extract_fields(txn)

        existing = Transaction.query.filter_by(
            plaid_transaction_id=txn.transaction_id
        ).first()

        if existing:
            for key, value in fields.items():
                setattr(existing, key, value)
            existing.removed = False
            existing.updated_at = _utcnow()
        else:
            db.session.add(Transaction(
                plaid_transaction_id=txn.transaction_id,
                institution_id=institution_id,
                **fields,
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


def _to_decimal(value):
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _to_date(value):
    """Coerce a Plaid date field (a ``date`` or 'YYYY-MM-DD' string) to a date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _enum_value(value):
    if value is None:
        return None
    if hasattr(value, 'value'):
        return value.value
    return str(value)


def _upsert_accounts(institution_id, accounts):
    now = _utcnow()
    for acct in accounts:
        balances = getattr(acct, 'balances', None)
        fields = {
            'name': acct.name or '',
            'official_name': getattr(acct, 'official_name', None),
            'mask': getattr(acct, 'mask', None),
            'type': _enum_value(getattr(acct, 'type', None)),
            'subtype': _enum_value(getattr(acct, 'subtype', None)),
            'current_balance': _to_decimal(getattr(balances, 'current', None)) if balances else None,
            'available_balance': _to_decimal(getattr(balances, 'available', None)) if balances else None,
            'iso_currency_code': getattr(balances, 'iso_currency_code', None) if balances else None,
            'last_synced_at': now,
        }
        existing = Account.query.filter_by(plaid_account_id=acct.account_id).first()
        if existing:
            for key, value in fields.items():
                setattr(existing, key, value)
            existing.institution_id = institution_id
        else:
            db.session.add(Account(
                institution_id=institution_id,
                plaid_account_id=acct.account_id,
                **fields,
            ))
