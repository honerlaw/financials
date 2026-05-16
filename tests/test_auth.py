def test_index_redirects_to_login_when_unauthenticated(client):
    res = client.get('/')
    assert res.status_code == 302
    assert '/login' in res.headers['Location']

def test_settings_redirects_to_login_when_unauthenticated(client):
    res = client.get('/settings')
    assert res.status_code == 302
    assert '/login' in res.headers['Location']

def test_login_correct_password_redirects_to_index(client):
    res = client.post('/login', data={'password': 'testpass'}, follow_redirects=True)
    assert res.status_code == 200

def test_login_wrong_password_shows_error(client):
    res = client.post('/login', data={'password': 'wrong'}, follow_redirects=True)
    assert b'Incorrect password' in res.data

def test_logout_clears_session(auth_client):
    auth_client.get('/logout')
    res = auth_client.get('/')
    assert res.status_code == 302
    assert '/login' in res.headers['Location']
