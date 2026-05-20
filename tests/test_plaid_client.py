import json
from unittest.mock import MagicMock, patch
import pytest
import plaid
from app.plaid_client import PlaidClient, slugify


def test_slugify():
    assert slugify('American Express') == 'american_express'
    assert slugify('Citi Bank') == 'citi_bank'
    assert slugify('Truist') == 'truist'
    assert slugify('U.S. Bank') == 'u_s_bank'


def _make_client():
    return PlaidClient({
        'PLAID_CLIENT_ID': 'test-id',
        'PLAID_SECRET': 'test-secret',
        'PLAID_ENV': 'sandbox',
    })


@patch('app.plaid_client.plaid_api.PlaidApi')
def test_create_link_token(MockApi):
    mock_response = MagicMock()
    mock_response.link_token = 'link-sandbox-xyz'
    MockApi.return_value.link_token_create.return_value = mock_response

    client = _make_client()
    client._client = MockApi.return_value
    assert client.create_link_token() == 'link-sandbox-xyz'


@patch('app.plaid_client.plaid_api.PlaidApi')
def test_exchange_token(MockApi):
    api = MockApi.return_value
    api.item_public_token_exchange.return_value = MagicMock(
        access_token='access-sandbox-abc', item_id='item-123'
    )
    api.item_get.return_value = MagicMock(item=MagicMock(institution_id='ins_10'))

    institution_mock = MagicMock()
    institution_mock.name = 'American Express'
    api.institutions_get_by_id.return_value = MagicMock(institution=institution_mock)

    client = _make_client()
    client._client = api
    access_token, item_id, name, slug = client.exchange_token('public-token-xxx')

    assert access_token == 'access-sandbox-abc'
    assert item_id == 'item-123'
    assert name == 'American Express'
    assert slug == 'american_express'


@patch('app.plaid_client.plaid_api.PlaidApi')
def test_sync_transactions_handles_pagination(MockApi):
    page1 = MagicMock(
        added=[MagicMock(transaction_id='t1')], modified=[], removed=[],
        accounts=[MagicMock(account_id='acc-1')],
        next_cursor='cursor-2', has_more=True,
    )
    page2 = MagicMock(
        added=[MagicMock(transaction_id='t2')], modified=[], removed=[],
        accounts=[MagicMock(account_id='acc-1'), MagicMock(account_id='acc-2')],
        next_cursor='cursor-final', has_more=False,
    )
    api = MockApi.return_value
    api.transactions_sync.side_effect = [page1, page2]

    client = _make_client()
    client._client = api
    added, modified, removed, cursor, accounts = client.sync_transactions('access-token', '')

    assert len(added) == 2
    assert cursor == 'cursor-final'
    assert api.transactions_sync.call_count == 2
    # accounts from the final page win (freshest balances)
    assert [a.account_id for a in accounts] == ['acc-1', 'acc-2']


def test_get_error_code():
    e = MagicMock(spec=plaid.ApiException)
    e.body = json.dumps({'error_code': 'ITEM_LOGIN_REQUIRED'})
    assert PlaidClient.get_error_code(e) == 'ITEM_LOGIN_REQUIRED'


def test_get_error_code_invalid_body():
    e = MagicMock(spec=plaid.ApiException)
    e.body = 'not-json'
    assert PlaidClient.get_error_code(e) == ''
