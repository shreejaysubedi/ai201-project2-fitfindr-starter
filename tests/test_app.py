import pytest

import app


def test_empty_query_panels():
    listing, outfit, card = app.handle_query('', 'Example wardrobe')
    assert 'Describe a piece' in listing and outfit == card == ''


def test_error_panels():
    result = app.handle_query_detailed('designer ballgown size XXS under $5', 'Example wardrobe', '', '')
    assert 'No matches' in result[0] and result[1] == result[2] == ''
    assert result[-1]['fit_card'] is None


def test_custom_wardrobe_and_preferences():
    wardrobe = app.make_wardrobe('Add my clothes', 'bottoms: blue jeans\nshoes: white sneakers', 'Loose fits')
    assert wardrobe['items'][0]['name'] == 'blue jeans'
    assert wardrobe['items'][1]['category'] == 'shoes'
    assert wardrobe['style_preferences'] == 'Loose fits'


def test_profile_round_trip():
    profile, message = app.save_profile('Add my clothes', 'bottoms: blue jeans', 'Earth tones')
    assert 'saved' in message
    assert app.restore_profile(profile) == ('Add my clothes', 'bottoms: blue jeans', 'Earth tones', 'Your saved style is loaded.')
    assert app.clear_profile()[0] == {}


def test_corrupt_profile_uses_defaults():
    assert app.restore_profile(None)[:3] == ('Example wardrobe', '', '')
    assert app.restore_profile({'wardrobe_choice': 'Example wardrobe', 'style_preferences': []})[:3] == ('Example wardrobe', '', '')


def test_bad_clothes_message():
    result = app.handle_query_detailed('tee', 'Add my clothes', 'something without a category', '')
    assert 'one piece per line' in result[0] and result[-1] == {}


def test_invalid_profile_does_not_save():
    profile, message = app.save_profile('Add my clothes', 'jeans', '')
    assert profile == app.gr.skip() and 'one piece per line' in message


def test_three_panels_receive_completed_session(monkeypatch):
    monkeypatch.setattr(app, 'run_agent', lambda *args: {
        'selected_item': {'title': 'Band tee', 'price': 19, 'platform': 'depop', 'size': 'L', 'condition': 'good', 'description': 'Soft cotton.'},
        'search_results': [{}], 'outfit_suggestion': 'Tee, jeans, boots.', 'fit_card': 'A thrifted fit.', 'error': None,
    })
    listing, outfit, card = app.handle_query('tee', 'Example wardrobe')
    assert '$19' in listing and outfit == 'Tee, jeans, boots.' and card == 'A thrifted fit.'


def test_interface_builds():
    assert app.build_interface().title == 'FitFindr'
