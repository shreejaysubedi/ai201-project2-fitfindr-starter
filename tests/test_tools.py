from types import SimpleNamespace

import httpx
import pytest
from groq import BadRequestError, RateLimitError

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
