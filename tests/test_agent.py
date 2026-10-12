import pytest

import agent
from utils.data_loader import get_example_wardrobe, load_listings


@pytest.mark.parametrize('query, description, size, price', [
    ('vintage graphic tee under $30, size M', 'vintage graphic tee', 'M', 30.0),
    ('90s track jacket in size M', '90s track jacket', 'M', None),
    ('black combat boots size 8', 'black combat boots', '8', None),
    ('jeans size W30 L30 up to $40', 'jeans', 'W30 L30', 40.0),
    ('shoes size US 8.5 below 50', 'shoes', 'US 8.5', 50.0),
    ("I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?", 'vintage graphic tee', None, 30.0),
])
def test_query_parsing(query, description, size, price):
    assert agent.parse_query(query) == {'description': description, 'size': size, 'max_price': price}


def test_state_flows_between_tools(monkeypatch):
    item = load_listings()[32]
    wardrobe = get_example_wardrobe()
    calls = []
    def search(**kwargs):
        calls.append('search')
        return [item]
    def outfit(received, clothes):
        assert received is item and clothes is wardrobe
        calls.append('outfit')
        return 'Tee, jeans, sneakers.'
    def card(received_outfit, received):
        assert received_outfit == 'Tee, jeans, sneakers.' and received is item
        calls.append('card')
        return 'A thrifted tee and an easy outfit.'
    monkeypatch.setattr(agent, 'search_listings', search)
    monkeypatch.setattr(agent, 'suggest_outfit', outfit)
    monkeypatch.setattr(agent, 'create_fit_card', card)
    session = agent.run_agent('tee under $30', wardrobe)
    assert calls == ['search', 'outfit', 'card']
    assert session['error'] is None and session['selected_item'] is item
    assert session['fit_card'] == 'A thrifted tee and an easy outfit.'


def test_no_match_skips_later_tools(monkeypatch):
    def forbidden(*args):
        pytest.fail('Later tools must not run after an empty search')
    monkeypatch.setattr(agent, 'suggest_outfit', forbidden)
    monkeypatch.setattr(agent, 'create_fit_card', forbidden)
    result = agent.run_agent('designer ballgown size XXS under $5', get_example_wardrobe())
    assert 'Try a broader' in result['error']
    assert result['selected_item'] is result['outfit_suggestion'] is result['fit_card'] is None


def test_fallback_notice_does_not_flow_into_card(monkeypatch):
    monkeypatch.setattr(agent, 'suggest_outfit', lambda *args: 'Fallback: AI is busy.\n\nTee, jeans, boots.')
    def card(outfit, item):
        assert outfit == 'Tee, jeans, boots.'
        return 'The final caption.'
    monkeypatch.setattr(agent, 'create_fit_card', card)
    result = agent.run_agent('vintage tee', get_example_wardrobe())
    assert result['error'] is None and result['notices'] == ['Fallback: AI is busy.']


def test_outfit_error_skips_card(monkeypatch):
    monkeypatch.setattr(agent, 'suggest_outfit', lambda *args: 'Error: Fix your wardrobe.')
    monkeypatch.setattr(agent, 'create_fit_card', lambda *args: pytest.fail('must skip card'))
    result = agent.run_agent('tee', {})
    assert result['error'] == 'Fix your wardrobe.' and result['fit_card'] is None


def test_card_error_preserves_outfit(monkeypatch):
    monkeypatch.setattr(agent, 'suggest_outfit', lambda *args: 'Tee, jeans, boots.')
    monkeypatch.setattr(agent, 'create_fit_card', lambda *args: 'Error: Try again.')
    result = agent.run_agent('tee', get_example_wardrobe())
    assert result['error'] == 'Try again.' and result['outfit_suggestion'] == 'Tee, jeans, boots.'


@pytest.mark.parametrize('query', ['', ' ', 'tee under $-5', 'size M under $20', 'tee size purple'])
def test_invalid_query_skips_tools(monkeypatch, query):
    monkeypatch.setattr(agent, 'search_listings', lambda **args: pytest.fail('must not search'))
    assert agent.run_agent(query, get_example_wardrobe())['error']


def test_search_failure_is_visible(monkeypatch):
    def fail(**args):
        raise agent.ToolError('Could not read the sample listings.')
    monkeypatch.setattr(agent, 'search_listings', fail)
    result = agent.run_agent('tee', get_example_wardrobe())
    assert result['error'] == 'Could not read the sample listings.'


def test_new_run_has_no_old_results(monkeypatch):
    monkeypatch.setattr(agent, 'suggest_outfit', lambda *args: 'Tee, jeans, sneakers.')
    monkeypatch.setattr(agent, 'create_fit_card', lambda *args: 'A caption.')
    good = agent.run_agent('tee', get_example_wardrobe())
    bad = agent.run_agent('designer ballgown size XXS under $5', get_example_wardrobe())
    assert good['fit_card'] and bad['fit_card'] is None
