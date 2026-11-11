import os
import pytest
from app import create_app

@pytest.fixture
def client():
    app = create_app()
    with app.test_client() as client:
        yield client

def test_welcome_page_has_no_theme_or_lang_toggle(client):
    res = client.get('/')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    # Theme toggle and language select should NOT be on the welcome page
    assert 'theme-toggle-btn' not in html
    assert 'global-lang-select' not in html

def test_theme_toggle_elements_in_profile_settings(client):
    from app.database.connection import get_db
    with get_db() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute('SELECT id, username, full_name, email FROM users LIMIT 1')
        user = cur.fetchone()
        cur.close()

    with client.session_transaction() as sess:
        sess['user_id'] = user['id'] if user else 1
        sess['username'] = user['username'] if user else 'testuser'
        sess['full_name'] = user['full_name'] if user else 'Test User'
        sess['email'] = user['email'] if user else 'test@example.com'

    res = client.get('/auth/profile')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    
    # Check theme toggle button
    assert 'theme-toggle-btn' in html
    assert 'theme-icon-dark' in html
    assert 'theme-icon-light' in html
    assert 'theme-label' in html
    assert 'global-lang-select' in html

def test_theme_css_and_js_files_exist():
    js_path = os.path.join('app', 'static', 'js', 'theme.js')
    css_path = os.path.join('app', 'static', 'css', 'style.css')
    
    assert os.path.exists(js_path)
    assert os.path.exists(css_path)
    
    with open(js_path, 'r', encoding='utf-8') as f:
        js_content = f.read()
    assert 'dnaura_theme_preference' in js_content
    assert 'data-theme' in js_content
    assert 'data-bs-theme' in js_content
    assert 'dark-theme' in js_content
    
    with open(css_path, 'r', encoding='utf-8') as f:
        css_content = f.read()
    assert '[data-theme="dark"]' in css_content
    assert '[data-bs-theme="dark"]' in css_content
