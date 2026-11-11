import json
import re
import pytest
from app import create_app

def parse_translations():
    with open("app/static/js/translations.js", "r", encoding="utf-8") as f:
        content = f.read()
    match = re.search(r'window\.TRANSLATIONS\s*=\s*(\{[\s\S]*\});', content)
    assert match, "Could not find window.TRANSLATIONS in translations.js"
    json_str = match.group(1)
    return json.loads(json_str)

LANGUAGES = ["en", "kn", "hi", "te", "ta"]

SIDEBAR_ROUTES = [
    '/dashboard/',
    '/analysis/complete',
    '/analysis/sequence',
    '/analysis/similarity',
    '/analysis/mutation',
    '/analysis/classification',
    '/analysis/disease',
    '/analysis/visualization',
    '/hospitals/',
    '/health-guidance/',
    '/appointments/my-appointments',
    '/appointments/book',
    '/auth/profile',
    '/reports/'
]

def test_all_translations_exist():
    translations = parse_translations()
    for lang in LANGUAGES:
        assert lang in translations, f"Language '{lang}' missing in translations.js"
        assert len(translations[lang]) > 300, f"Language '{lang}' has insufficient keys"

def test_no_missing_keys_for_any_language():
    translations = parse_translations()
    en_keys = set(translations["en"].keys())
    for lang in ["kn", "hi", "te", "ta"]:
        lang_keys = set(translations[lang].keys())
        missing = en_keys - lang_keys
        assert len(missing) == 0, f"Language '{lang}' is missing keys: {missing}"

def test_all_sidebar_routes_render():
    app = create_app()
    with app.test_client() as client:
        for route in SIDEBAR_ROUTES:
            response = client.get(route)
            assert response.status_code in [200, 301, 302, 308], f"Route '{route}' failed with status {response.status_code}"

def test_health_guidance_sidebar_isolation():
    # 1. Verify template isolation structure
    with open("app/templates/health/guidance.html", "r", encoding="utf-8") as f:
        guidance_html = f.read()
    assert 'id="health-guidance-module-area"' in guidance_html, "guidance.html missing #health-guidance-module-area wrapper"
    assert 'global-lang-select' not in guidance_html, "#health-lang-select should not have global-lang-select class"
    assert 'id="health-lang-select"' in guidance_html, "guidance.html missing #health-lang-select dropdown"

    # 2. Verify language.js isolates health-lang-select
    with open("app/static/js/language.js", "r", encoding="utf-8") as f:
        lang_js = f.read()

    # Must target health-guidance-module-area
    assert 'health-guidance-module-area' in lang_js, "language.js must scope health translations to #health-guidance-module-area"
    # Scoped translations must protect #sidebar
    assert 'el.closest("#sidebar, .app-sidebar' in lang_js or 'closest("#sidebar' in lang_js, "language.js must safeguard #sidebar from scoped translations"

