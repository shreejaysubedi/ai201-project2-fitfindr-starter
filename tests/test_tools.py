from types import SimpleNamespace

import httpx
import pytest
from groq import BadRequestError, RateLimitError

import agent
import app
import tools
from utils.data_loader import get_empty_wardrobe, get_example_wardrobe, load_listings


@pytest.fixture
def item():
    return next(piece for piece in load_listings() if piece['id'] == 'lst_033')


def test_search_returns_ranked_tees():
    results = tools.search_listings('vintage graphic tee', max_price=30)
    assert results[0]['id'] == 'lst_033'
    assert all('tee' in tools._words(x['title']) | tools._words(' '.join(x['style_tags'])) for x in results)


def test_search_empty_results():
    assert tools.search_listings('designer ballgown', 'XXS', 5) == []


def test_search_price_filter():
    results = tools.search_listings('tee', max_price=19)
    assert results
    assert all(x['price'] <= 19 for x in results)


def test_search_size_filter():
    results = tools.search_listings('tee', 'm', 30)
    assert results and all(x['size'] == 'S/M' for x in results)


@pytest.mark.parametrize('wanted, actual, matches', [
    ('M', 'S/M', True), ('M', 'M/L', True), ('M', 'XL (oversized)', False),
    ('L', 'XL', False), ('8', 'US 8', True), ('8', 'US 8.5', False),
    ('US 8', 'US 8.5', False), ('W30', 'W30 L30', True),
    ('OS', 'One Size / Oversized', True),
])
def test_size_boundaries(wanted, actual, matches):
    assert tools._size_matches(wanted, actual) is matches


def test_search_blank():
    assert tools.search_listings('  ') == []


@pytest.mark.parametrize('budget', [-1, float('nan'), float('inf'), True, 'cheap'])
def test_bad_budget(budget):
    with pytest.raises(tools.ToolError, match='price'):
        tools.search_listings('tee', max_price=budget)


def test_search_broken_file(monkeypatch):
    def fail():
        raise OSError('private system details')
    monkeypatch.setattr(tools, 'load_listings', fail)
    with pytest.raises(tools.ToolError, match='data/listings.json'):
        tools.search_listings('tee')


def test_search_broken_listing(monkeypatch):
    monkeypatch.setattr(tools, 'load_listings', lambda: [{'title': 'tee'}])
    with pytest.raises(tools.ToolError, match='incomplete'):
        tools.search_listings('tee')


def test_outfit_uses_owned_pieces(monkeypatch, item):
    calls = []
    def generate(prompt, temperature):
        calls.append(prompt)
        return 'Pair the tee with your baggy jeans and chunky sneakers.', None
    monkeypatch.setattr(tools, '_generate', generate)
    assert 'baggy jeans' in tools.suggest_outfit(item, get_example_wardrobe())
    assert 'Chunky white sneakers' in calls[0]
    assert item['title'] in calls[0]


def test_empty_wardrobe_still_calls_ai(monkeypatch, item):
    calls = []
    def generate(prompt, temperature):
        calls.append(prompt)
        return 'Suggested extras: jeans and sneakers. Half-tuck the tee.', None
    monkeypatch.setattr(tools, '_generate', generate)
    assert 'Suggested extras' in tools.suggest_outfit(item, get_empty_wardrobe())
    assert '"items": []' in calls[0]


def test_outfit_missing_key_fallback(monkeypatch, item):
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    result = tools.suggest_outfit(item, get_empty_wardrobe())
    assert result.startswith('Fallback:')
    assert 'GROQ_API_KEY' in result
    assert 'Suggested extras' in result
    assert 'jeans' in result and 'sneakers' in result


def test_minimal_wardrobe_fallback(monkeypatch, item):
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    result = tools.suggest_outfit(item, {'items': [get_example_wardrobe()['items'][0]]})
    assert 'Baggy straight-leg jeans' in result
    assert 'Suggested extras' in result and 'sneakers' in result


@pytest.mark.parametrize('wardrobe', [{}, {'items': None}, {'items': [{}]}])
def test_invalid_wardrobe(item, wardrobe):
    assert tools.suggest_outfit(item, wardrobe).startswith('Error:')


def test_invalid_new_item():
    assert tools.suggest_outfit({}, get_example_wardrobe()).startswith('Error:')
    assert tools.create_fit_card('An outfit.', {}).startswith('Error:')


@pytest.mark.parametrize('outfit', ['', '  ', None, 'Error: No outfit.', 'Fallback: no usable text'])
def test_card_missing_outfit(item, outfit):
    result = tools.create_fit_card(outfit, item)
    assert result.startswith('Error:') and 'outfit' in result


def test_card_receives_both_inputs(monkeypatch, item):
    calls = []
    def generate(prompt, temperature):
        calls.append((prompt, temperature))
        return 'A $19 depop tee with jeans. Ready for the weekend.', None
    monkeypatch.setattr(tools, '_generate', generate)
    assert tools.create_fit_card('Baggy jeans and boots.', item).startswith('A $19')
    assert 'Baggy jeans and boots.' in calls[0][0] and item['title'] in calls[0][0]
    assert calls[0][1] == 1.0


def test_card_fallback_changes_with_inputs(monkeypatch, item):
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    a = tools.create_fit_card('Jeans and boots.', item)
    b = tools.create_fit_card('Khakis and sneakers.', item)
    assert a != b and 'Jeans and boots' in a and 'Khakis and sneakers' in b
    assert '$19' in a and 'depop' in a


def test_card_strips_outfit_warning(monkeypatch, item):
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    result = tools.create_fit_card('Fallback: service failed\n\nJeans and boots.', item)
    caption = result.partition('\n\n')[2]
    assert 'service failed' not in caption and 'Jeans and boots' in caption


def test_rate_limit_has_actionable_fallback(monkeypatch, item):
    response = httpx.Response(429, request=httpx.Request('POST', 'https://api.groq.com'))
    def fail(*args):
        raise RateLimitError('busy', response=response, body={})
    monkeypatch.setattr(tools, '_generate', fail)
    assert 'free limit' in tools.suggest_outfit(item, get_example_wardrobe())
    assert 'free limit' in tools.create_fit_card('Jeans and boots.', item)


def test_model_retirement_retries_once(monkeypatch):
    calls = []
    def create(**kwargs):
        calls.append(kwargs['model'])
        if len(calls) == 1:
            response = httpx.Response(400, request=httpx.Request('POST', 'https://api.groq.com'))
            raise BadRequestError('retired', response=response, body={'error': {'code': 'model_decommissioned'}})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='A useful reply.'))])
    monkeypatch.setattr(tools, '_get_groq_client', lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.delenv('GROQ_MODEL', raising=False)
    monkeypatch.delenv('GROQ_FALLBACK_MODEL', raising=False)
    text, notice = tools._generate('Style this.', 0.7)
    assert text == 'A useful reply.' and 'unavailable' in notice
    assert calls == [tools.COURSE_MODEL, 'openai/gpt-oss-120b']


def test_empty_ai_reply(monkeypatch, item):
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: SimpleNamespace(choices=[]))))
    monkeypatch.setattr(tools, '_get_groq_client', lambda: client)
    assert 'no usable text' in tools.suggest_outfit(item, get_example_wardrobe())
    assert 'no usable text' in tools.create_fit_card('Jeans and boots.', item)


def test_timeout_uses_local_text(monkeypatch, item):
    from groq import APITimeoutError
    def fail(*args):
        raise APITimeoutError(request=httpx.Request('POST', 'https://api.groq.com'))
    monkeypatch.setattr(tools, '_generate', fail)
    assert tools.suggest_outfit(item, get_empty_wardrobe()).startswith('Fallback:')
    assert tools.create_fit_card('Jeans and boots.', item).startswith('Fallback:')


def test_bad_style_tags_do_not_crash(item):
    broken = dict(item, style_tags=None)
    assert tools.suggest_outfit(broken, get_example_wardrobe()).startswith('Error:')
    assert tools.create_fit_card('Jeans and boots.', broken).startswith('Error:')
    wardrobe = {'items': [{'name': 'jeans', 'category': 'bottoms', 'style_tags': None}]}
    assert tools.suggest_outfit(item, wardrobe).startswith('Error:')


# Agent flow

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


# App

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


# Extra features

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
