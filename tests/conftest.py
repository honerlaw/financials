import pytest
from app import create_app
from app.models import db as _db


@pytest.fixture(scope='function')
def app():
    test_config = {
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'APP_PASSWORD': 'testpass',
        'SECRET_KEY': 'test-secret-key',
        'PLAID_CLIENT_ID': 'test-client-id',
        'PLAID_SECRET': 'test-secret',
        'PLAID_ENV': 'sandbox',
        'OPENROUTER_API_KEY': 'test-key',
        'OPENROUTER_MODEL': 'test-model',
        'CHAT_MAX_ITERATIONS': 5,
        'CHAT_QUERY_ROW_LIMIT': 200,
    }
    app = create_app(test_config)
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture(scope='function')
def client(app):
    return app.test_client()


@pytest.fixture(scope='function')
def auth_client(client):
    client.post('/login', data={'password': 'testpass'}, follow_redirects=True)
    return client
