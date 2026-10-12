"""Choose the next tool from the current session's results."""

import re

from tools import ERROR_PREFIX, FALLBACK_PREFIX, NOTICE_PREFIX, ToolError, compare_price, create_fit_card, search_listings, suggest_outfit

_PRICE = re.compile(r"(?:\b(?:under|below|less than|up to|at most|max(?:imum)?(?: price)?|budget(?: of)?)\s*[:=]?\s*\$?\s*|\$\s*)(-?\d+(?:\.\d+)?)", re.I)
_SIZE = re.compile(r"\bsize\s*[:=]?\s*((?:US|UK|EU)\s*\d+(?:\.\d+)?|W\d+(?:\s+L\d+)?|(?:XXXS|XXS|XXXL|XXL|XS|XL|S|M|L)(?:/(?:XXXS|XXS|XXXL|XXL|XS|XL|S|M|L))?|\d+(?:\.\d+)?|one\s+size)\b", re.I)


def _new_session(query: str, wardrobe: dict) -> dict:
    return {
        'query': query, 'parsed': {}, 'search_results': [], 'selected_item': None,
        'wardrobe': wardrobe, 'outfit_suggestion': None, 'fit_card': None,
        'error': None, 'notices': [], 'steps': [],
        'price_comparison': None, 'search_attempts': [], 'retry_used': False,
    }


def parse_query(query: str) -> dict:
    """Read common size/budget phrases without a model call."""
    text = query.strip()
    price_match = _PRICE.search(text)
    size_match = _SIZE.search(text)
    if re.search(r'\bsize\b', text, re.I) and not size_match:
        raise ToolError('Use a size such as M, W30, or US 8, or leave size out.')
    price = float(price_match[1]) if price_match else None
    if price is not None and price < 0:
        raise ToolError('Use a price of $0 or more, or leave the budget out.')
    size = re.sub(r'\s+', ' ', size_match[1]).upper() if size_match else None
    text = _PRICE.sub('', _SIZE.sub('', text))
    text = re.split(r"\b(?:i\s+(?:mostly\s+)?wear|my\s+wardrobe|what(?:'s| is)\s+out|how\s+(?:would|can|should|do)\s+i\s+(?:wear|style))\b", text, maxsplit=1, flags=re.I)[0]
    text = re.sub(r"^(?:(?:i(?:'m| am)?\s+)?(?:looking for|want|need)|(?:please\s+)?(?:find(?: me)?|show me))\s+(?:an?\s+)?", '', text, flags=re.I)
    text = re.sub(r'\bin\s*$', '', text.strip(' ,.;?!'), flags=re.I)
    description = re.sub(r'\s+', ' ', text).strip(' ,.;?!')
    if not description:
        raise ToolError('Name a piece to find, such as a vintage tee or a denim jacket.')
    return {'description': description, 'size': size, 'max_price': price}


def _accept_text(session: dict, tool_name: str, field: str, result: str) -> bool:
    if not isinstance(result, str) or not result.strip():
        session['error'] = f'{tool_name} returned no text. Try again.'
        session['steps'].append({'tool': tool_name, 'status': 'stopped', 'detail': session['error']})
        return False
    if result.startswith(ERROR_PREFIX):
        session['error'] = result.removeprefix(ERROR_PREFIX).strip()
        session['steps'].append({'tool': tool_name, 'status': 'stopped', 'detail': session['error']})
        return False
    status = 'done'
    if result.startswith((FALLBACK_PREFIX, NOTICE_PREFIX)):
        notice, _, result = result.partition('\n\n')
        session['notices'].append(notice)
        status = 'local fallback' if notice.startswith(FALLBACK_PREFIX) else 'model fallback'
        if not result.strip():
            session['error'] = f'{tool_name} returned no usable text. Try again.'
            return False
    session[field] = result.strip()
    session['steps'].append({'tool': tool_name, 'status': status, 'detail': f'Saved {field}.'})
    return True


def run_agent(query: str, wardrobe: dict) -> dict:
    """Return results, notices, and tool history. Keep completed work on errors."""
    session = _new_session(query, wardrobe)
    if not isinstance(query, str) or not query.strip():
        session['error'] = 'Describe a piece to find, such as a vintage tee under $30.'
        return session
    try:
        session['parsed'] = parse_query(query)
    except ToolError as exc:
        session['error'] = str(exc)
        return session

    while not session['fit_card'] and not session['error']:
        try:
            if not session['search_results']:
                args = session['parsed'].copy()
                if session['search_attempts']:
                    args['size'] = None
                    session['retry_used'] = True
                    session['notices'].append('No exact size match. Searching other sizes within your budget; check the listed size before buying.')
                session['search_results'] = search_listings(**args)
                session['search_attempts'].append({'filters': args.copy(), 'match_count': len(session['search_results'])})
                session['steps'].append({'tool': 'search_listings', 'status': 'done', 'inputs': args.copy(), 'detail': f"Found {len(session['search_results'])} matches."})
                if not session['search_results'] and (args['size'] is None or session['retry_used']):
                    session['error'] = 'No matches in the sample listings. Try a broader item name, another size, or a higher budget.'
            elif session['selected_item'] is None:
                session['selected_item'] = session['search_results'][0]
            elif session['price_comparison'] is None:
                session['price_comparison'] = compare_price(session['selected_item'])
                session['steps'].append({'tool': 'compare_price', 'status': session['price_comparison']['verdict'], 'detail': session['price_comparison']['message']})
            elif session['outfit_suggestion'] is None:
                _accept_text(session, 'suggest_outfit', 'outfit_suggestion', suggest_outfit(session['selected_item'], session['wardrobe']))
            else:
                _accept_text(session, 'create_fit_card', 'fit_card', create_fit_card(session['outfit_suggestion'], session['selected_item']))
        except ToolError as exc:
            session['error'] = str(exc)
        except Exception:
            # Keep a bad tool/plugin from taking down the UI; don't expose secrets.
            session['error'] = 'This step could not finish. Check your inputs and try again.'
    return session


if __name__ == '__main__':
    import json
    from utils.data_loader import get_example_wardrobe

    for query in ('vintage graphic tee under $30', 'designer ballgown size XXS under $5'):
        print(json.dumps(run_agent(query, get_example_wardrobe()), indent=2, ensure_ascii=False))
