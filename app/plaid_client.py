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
from plaid.model.link_token_transactions import LinkTokenTransactions
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.model.transactions_sync_request_options import TransactionsSyncRequestOptions
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.liabilities_get_request import LiabilitiesGetRequest
from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest


def slugify(name):
    name = name.lower()
    name = re.sub(r'[^a-z0-9]+', '_', name)
    return name.strip('_')


class PlaidClient:
    def __init__(self, config):
        env = config.get('PLAID_ENV', 'development')
        env_map = {
            'development': plaid.Environment.Sandbox,
            'production': plaid.Environment.Production,
        }
        host = env_map.get(env, plaid.Environment.Sandbox)
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
                # `liabilities` and `investments` are consented but not
                # required: institutions that don't support them still link
                # (transactions stays the only required product), and when
                # present we can call /liabilities/get for credit-card due
                # dates & balances and /investments/holdings/get for
                # vested/unvested equity compensation.
                additional_consented_products=[
                    Products('liabilities'), Products('investments'),
                ],
                client_name='Financial Sync',
                country_codes=[CountryCode('US')],
                language='en',
                user=LinkTokenCreateRequestUser(client_user_id='local-user'),
                transactions=LinkTokenTransactions(days_requested=730),
            )
        )
        return response.link_token

    def create_update_link_token(self, access_token):
        """Create a link token in *update mode* for an existing Item.

        Passing ``access_token`` puts Plaid Link into update mode for that
        specific Item, letting the user re-authenticate after an
        ITEM_LOGIN_REQUIRED without creating a new Item. ``products`` and
        ``transactions`` are link-time-only parameters and are omitted — Plaid
        rejects them when ``access_token`` is present.

        ``additional_consented_products`` *is* accepted alongside
        ``access_token``, and update mode is Plaid's remedy for
        ADDITIONAL_CONSENT_REQUIRED: an Item linked before a product was
        consented can only start returning that product's data once the user
        re-consents here. Re-connecting is therefore useful for a healthy Item
        too, not just after a login failure — it is the only way an Item linked
        before `investments` was consented starts reporting vested holdings.
        """
        response = self._client.link_token_create(
            LinkTokenCreateRequest(
                client_name='Financial Sync',
                country_codes=[CountryCode('US')],
                language='en',
                user=LinkTokenCreateRequestUser(client_user_id='local-user'),
                access_token=access_token,
                additional_consented_products=[
                    Products('liabilities'), Products('investments'),
                ],
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

    def get_balances(self, access_token):
        """Force-refresh balances for every account on this Item.

        Unlike the accounts payload returned by transactions/sync (which is a
        cached snapshot), accounts/balance/get instructs Plaid to pull live
        balances from the institution.
        """
        response = self._client.accounts_balance_get(
            AccountsBalanceGetRequest(access_token=access_token)
        )
        return response.accounts

    def get_liabilities(self, access_token):
        """Fetch liability details (due dates, statement/minimum amounts).

        Returns the ``liabilities`` object, which carries ``.credit``,
        ``.student``, and ``.mortgage`` arrays. Each entry ties back to an
        ``Account`` via ``account_id`` and exposes the payment fields we surface
        on the dashboard. Raises ``plaid.ApiException`` when the Item wasn't
        consented to the ``liabilities`` product (callers treat this as
        non-fatal — see app/sync.py::_refresh_liabilities).
        """
        response = self._client.liabilities_get(
            LiabilitiesGetRequest(access_token=access_token)
        )
        return response.liabilities

    def get_investments(self, access_token):
        """Fetch investment accounts and holdings (with vested equity-comp figures).

        Returns ``(accounts, holdings)``.

        ``holdings`` is the response's ``holdings`` list. Each ``Holding`` ties
        back to an ``Account`` via ``account_id`` and carries
        ``institution_value`` plus, for equity compensation the institution
        reports on, ``vested_value`` / ``vested_quantity``.

        ``accounts`` is the response's ``accounts`` list — "the accounts
        associated with the Item". This is the one payload *guaranteed by
        schema* to carry the Item's investment accounts, which
        ``transactions/sync`` never returns; ``_refresh_investments`` creates
        rows from it so a brokerage account can reach the dashboard at all.
        Each entry is an ``InvestmentAccount``, which composes ``AccountBase``
        and exposes the same ``account_id`` / ``name`` / ``mask`` / ``subtype``
        / ``balances`` fields ``_upsert_accounts`` reads.

        Named ``get_investments`` rather than ``get_investment_holdings``
        because the return shape changed from a bare list to a tuple: a
        same-named method would let an existing ``return_value = [...]`` mock
        destructure two holdings into ``accounts, holdings`` without raising.

        Raises ``plaid.ApiException`` when the Item wasn't consented to the
        ``investments`` product (callers treat this as non-fatal — see
        app/sync.py::_refresh_investments).
        """
        response = self._client.investments_holdings_get(
            InvestmentsHoldingsGetRequest(access_token=access_token)
        )
        return response.accounts, response.holdings

    def sync_transactions(self, access_token, cursor=''):
        added, modified, removed = [], [], []
        accounts = []
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
            # transactions/sync returns the institution's accounts on every page;
            # the last page wins so we end with the freshest balances.
            page_accounts = getattr(response, 'accounts', None) or []
            if page_accounts:
                accounts = list(page_accounts)
            cursor = response.next_cursor
            if not response.has_more:
                break
        return added, modified, removed, cursor, accounts

    @staticmethod
    def get_error_code(api_exception):
        try:
            return json.loads(api_exception.body).get('error_code', '')
        except Exception:
            return ''
