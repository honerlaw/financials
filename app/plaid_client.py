import json
import re
import plaid
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.item_get_request import ItemGetRequest
from plaid.model.item_remove_request import ItemRemoveRequest
from plaid.model.institutions_get_by_id_request import InstitutionsGetByIdRequest
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.model.transactions_sync_request_options import TransactionsSyncRequestOptions


def slugify(name):
    name = name.lower()
    name = re.sub(r'[^a-z0-9]+', '_', name)
    return name.strip('_')


class PlaidClient:
    def __init__(self, config):
        env = config.get('PLAID_ENV', 'development')
        host = plaid.Environment.Development if env == 'development' else plaid.Environment.Sandbox
        configuration = plaid.Configuration(
            host=host,
            api_key={
                'clientId': config['PLAID_CLIENT_ID'],
                'secret': config['PLAID_SECRET'],
            },
        )
        self._client = plaid_api.PlaidApi(plaid.ApiClient(configuration))

    def create_link_token(self):
        response = self._client.link_token_create(
            LinkTokenCreateRequest(
                products=[Products('transactions')],
                client_name='Financial Sync',
                country_codes=[CountryCode('US')],
                language='en',
                user=LinkTokenCreateRequestUser(client_user_id='local-user'),
            )
        )
        return response.link_token

    def exchange_token(self, public_token):
        exchange_resp = self._client.item_public_token_exchange(
            ItemPublicTokenExchangeRequest(public_token=public_token)
        )
        access_token = exchange_resp.access_token
        item_id = exchange_resp.item_id

        item_resp = self._client.item_get(ItemGetRequest(access_token=access_token))
        institution_id = item_resp.item.institution_id

        inst_resp = self._client.institutions_get_by_id(
            InstitutionsGetByIdRequest(
                institution_id=institution_id,
                country_codes=[CountryCode('US')],
            )
        )
        name = inst_resp.institution.name
        return access_token, item_id, name, slugify(name)

    def remove_item(self, access_token):
        self._client.item_remove(ItemRemoveRequest(access_token=access_token))

    def sync_transactions(self, access_token, cursor=''):
        added, modified, removed = [], [], []
        while True:
            response = self._client.transactions_sync(
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
        return added, modified, removed, cursor

    @staticmethod
    def get_error_code(api_exception):
        try:
            return json.loads(api_exception.body).get('error_code', '')
        except Exception:
            return ''
