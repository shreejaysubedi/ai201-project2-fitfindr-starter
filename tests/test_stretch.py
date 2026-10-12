import pytest

import agent
import tools
from utils.data_loader import get_example_wardrobe, load_listings


def test_price_comparison_excludes_selected_item():
    item = load_listings()[32]
    result = tools.compare_price(item)
    assert item['id'] not in result['comparable_ids']
    assert result['median_price'] == 21.0 and result['verdict'] == 'fair'


@pytest.mark.parametrize('price, verdict', [(5, 'below typical'), (20, 'fair'), (50, 'above typical')])
def test_price_verdicts(monkeypatch, price, verdict):
    item = dict(load_listings()[32], price=price)
    comps = [dict(item, id='other_a', price=18), dict(item, id='other_b', price=22), item]
    monkeypatch.setattr(tools, 'load_listings', lambda: comps)
    result = tools.compare_price(item)
    assert result['verdict'] == verdict and result['median_price'] == 20
    assert result['comparable_count'] == 2


def test_price_insufficient_data(monkeypatch):
    item = load_listings()[32]
    monkeypatch.setattr(tools, 'load_listings', lambda: [item])
    result = tools.compare_price(item)
    assert result['verdict'] == 'not enough data' and result['median_price'] is None


def test_price_broken_file(monkeypatch):
    def fail():
        raise OSError('file gone')
    monkeypatch.setattr(tools, 'load_listings', fail)
    assert tools.compare_price(load_listings()[32])['verdict'] == 'unavailable'
    assert tools.compare_price({})['verdict'] == 'unavailable'


def test_retry_keeps_budget_and_description(monkeypatch):
    item = load_listings()[32]
    calls = []
    def search(**kwargs):
        calls.append(kwargs)
        return [] if kwargs['size'] else [item]
    monkeypatch.setattr(agent, 'search_listings', search)
    monkeypatch.setattr(agent, 'suggest_outfit', lambda *args: 'Tee, jeans, sneakers.')
    monkeypatch.setattr(agent, 'create_fit_card', lambda *args: 'A caption.')
    result = agent.run_agent('vintage band tee size XXS under $30', get_example_wardrobe())
    assert calls == [dict(description='vintage band tee', size='XXS', max_price=30.0), dict(description='vintage band tee', size=None, max_price=30.0)]
    assert result['parsed']['size'] == 'XXS' and result['retry_used']
    assert len(result['search_attempts']) == 2 and 'other sizes' in result['notices'][0]
    assert result['fit_card'] == 'A caption.'


def test_two_failed_searches_stop(monkeypatch):
    monkeypatch.setattr(agent, 'suggest_outfit', lambda *args: pytest.fail('must skip outfit'))
    result = agent.run_agent('designer ballgown size XXS under $5', get_example_wardrobe())
    assert result['error'] and len(result['search_attempts']) == 2 and result['fit_card'] is None


def test_no_size_does_not_retry(monkeypatch):
    result = agent.run_agent('designer ballgown under $5', get_example_wardrobe())
    assert len(result['search_attempts']) == 1 and not result['retry_used']


def test_unavailable_price_does_not_block_outfit(monkeypatch):
    monkeypatch.setattr(agent, 'compare_price', lambda *args: {'verdict': 'unavailable', 'message': 'Unavailable.'})
    monkeypatch.setattr(agent, 'suggest_outfit', lambda *args: 'Tee, jeans, sneakers.')
    monkeypatch.setattr(agent, 'create_fit_card', lambda *args: 'A caption.')
    result = agent.run_agent('tee', get_example_wardrobe())
    assert result['fit_card'] and result['error'] is None
