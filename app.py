"""A local Gradio app for secondhand finds and outfit ideas."""

import os
from pathlib import Path

os.environ.setdefault('GRADIO_ANALYTICS_ENABLED', 'False')

import gradio as gr

from agent import run_agent
from utils.data_loader import get_empty_wardrobe, get_example_wardrobe

WARDROBE_CHOICES = ['Example wardrobe', 'Empty wardrobe (new user)', 'Add my clothes']
EXAMPLE_QUERIES = [
    'vintage graphic tee under $30, size M',
    '90s track jacket in size M',
    'vintage slip dress under $40',
    'black combat boots size 8',
    'vintage band tee size XXS under $30',
    'designer ballgown size XXS under $5',
]


def make_wardrobe(choice: str, wardrobe_text: str = '', preferences: str = '') -> dict:
    if choice not in WARDROBE_CHOICES:
        raise ValueError('Choose a wardrobe option first.')
    wardrobe = get_example_wardrobe() if choice == WARDROBE_CHOICES[0] else get_empty_wardrobe()
    if choice == 'Add my clothes':
        pieces = []
        for line in wardrobe_text.splitlines():
            if not line.strip():
                continue
            category, separator, name = line.partition(':')
            category, name = category.strip().lower(), name.strip()
            if not separator or category not in {'tops', 'bottoms', 'outerwear', 'shoes', 'accessories'} or not name:
                raise ValueError('Use one piece per line, like bottoms: baggy blue jeans. Categories: tops, bottoms, outerwear, shoes, accessories.')
            pieces.append({'id': f'custom_{len(pieces) + 1}', 'name': name, 'category': category, 'colors': [], 'style_tags': [], 'notes': None})
        wardrobe['items'] = pieces
    wardrobe['style_preferences'] = preferences.strip()
    return wardrobe


def render_session(session: dict) -> tuple[str, str, str]:
    item = session['selected_item']
    if item:
        listing = f"### {item['title']}\n\n**${item['price']:g}** · {item['platform']}\n\nSize **{item['size']}** · {item['condition'].capitalize()} condition\n\n{item['description']}"
        price = session.get('price_comparison')
        if price:
            listing += '\n\n' + price['message']
        listing += f"\n\n{len(session['search_results'])} matching sample listing(s)."
    else:
        listing = session['error'] or 'No listing selected.'
    return listing, session['outfit_suggestion'] or '', session['fit_card'] or ''


def handle_query(user_query: str, wardrobe_choice: str) -> tuple[str, str, str]:
    """Keep the starter's three-panel handler available for direct use."""
    session = run_agent(user_query, make_wardrobe(wardrobe_choice))
    return render_session(session)


def handle_query_detailed(user_query: str, wardrobe_choice: str, wardrobe_text: str, preferences: str) -> tuple[str, str, str, str, str, dict]:
    try:
        wardrobe = make_wardrobe(wardrobe_choice, wardrobe_text, preferences)
    except (ValueError, OSError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else 'Could not load the wardrobe. Check data/wardrobe_schema.json.'
        return message, '', '', message, '', {}
    session = run_agent(user_query, wardrobe)
    notices = list(dict.fromkeys(session['notices']))
    if session['error']:
        notices.insert(0, session['error'])
    status = '\n\n'.join(notices) if notices else 'Your find, outfit, and caption are ready.'
    steps = []
    for number, step in enumerate(session['steps'], 1):
        name = {'search_listings': 'Find pieces', 'compare_price': 'Check the price', 'suggest_outfit': 'Build an outfit', 'create_fit_card': 'Write a caption'}[step['tool']]
        detail = step['detail']
        if step['tool'] == 'suggest_outfit':
            detail = f"Used listing {session['selected_item']['id']} and {len(wardrobe['items'])} wardrobe pieces."
        elif step['tool'] == 'create_fit_card':
            detail = f"Used the saved outfit and the same listing, {session['selected_item']['id']}."
        steps.append(f"**{number}. {name}** — {detail}")
    return (*render_session(session), status, '\n\n'.join(steps), session)


def save_profile(choice: str, wardrobe_text: str, preferences: str) -> tuple[dict, str]:
    try:
        make_wardrobe(choice, wardrobe_text, preferences)
    except (ValueError, OSError) as exc:
        return gr.skip(), str(exc)
    return {'wardrobe_choice': choice, 'wardrobe_text': wardrobe_text, 'style_preferences': preferences}, 'Style saved in this browser.'


def restore_profile(profile: dict) -> tuple[str, str, str, str]:
    if not isinstance(profile, dict) or profile.get('wardrobe_choice') not in WARDROBE_CHOICES:
        return WARDROBE_CHOICES[0], '', '', ''
    text, preferences = profile.get('wardrobe_text', ''), profile.get('style_preferences', '')
    if not isinstance(text, str) or not isinstance(preferences, str):
        return WARDROBE_CHOICES[0], '', '', ''
    return profile['wardrobe_choice'], text, preferences, 'Your saved style is loaded.'


def clear_profile() -> tuple[dict, str, str, str, str]:
    return {}, WARDROBE_CHOICES[0], '', '', 'Saved style cleared.'


HERO = '''
<div class="hero">
  <div class="brand-row"><span class="brand-mark">f.</span><span class="wordmark">fitfindr</span><span class="little-label">SECONDHAND, FIRST CHOICE</span></div>
  <div class="hero-body">
    <div><div class="eyebrow">A GOOD FIND IS JUST THE START</div><h1>Good finds.<br><span>Better fits.</span></h1><p>Find a piece you love. Make it work with what you own.</p></div>
    <div class="hero-art" aria-hidden="true">
      <svg viewBox="0 0 300 250" role="presentation"><circle cx="158" cy="122" r="104" fill="#ecd9c4"/><circle cx="242" cy="61" r="14" fill="#c86245"/>
      <path d="M147 46q0-17 15-17t15 14q0 9-17 17v13" fill="none" stroke="#243c33" stroke-width="5" stroke-linecap="round"/>
      <path d="M160 72L72 126q-12 9 3 9h171q15 0 3-9z" fill="none" stroke="#243c33" stroke-width="5" stroke-linejoin="round"/>
      <path d="M119 86l-45 27 20 42 22-11v72h88v-72l22 11 20-42-45-27q-11 23-41 23t-41-23" fill="#c86245" stroke="#243c33" stroke-width="3" stroke-linejoin="round"/>
      <path d="M136 159q24-27 48 0q-24 33-48 0z" fill="#f8f3ea"/><path d="M153 145l8 25" stroke="#c86245" stroke-width="3"/>
      <path d="M43 68v20m-10-10h20M262 178v20m-10-10h20" stroke="#b49d80" stroke-width="3" stroke-linecap="round"/>
      <path d="M87 222h145" stroke="#243c33" stroke-width="3" stroke-linecap="round"/>
      </svg><span class="art-note">less new. more you.</span>
    </div>
  </div>
  <div class="hero-footer"><span>01 &nbsp; FIND IT</span><span>02 &nbsp; STYLE IT</span><span>03 &nbsp; SHARE IT</span><span class="mock-note">40 sample finds · no live shopping</span></div>
</div>
'''

CSS = '''
.gradio-container { max-width: 1140px !important; margin: auto !important; padding: 28px 28px 40px !important; background: #f8f3ea !important;
--background-fill-primary: #fffdf8 !important; --background-fill-secondary: #eee7db !important;
--block-label-text-color: #243c33 !important; --block-title-text-color: #243c33 !important;
--body-text-color-subdued: #626b5d !important; --border-color-primary: #d9d2c5 !important;
--input-background-fill: #fffdf8 !important; --input-border-color: #d9d2c5 !important; }
body { background: #f8f3ea !important; }
.hero { color: #243c33; padding: 0 8px; }
.brand-row { display: flex; align-items: center; gap: 11px; border-bottom: 1px solid #d9d2c5; padding: 0 0 18px; }
.brand-mark { background: #243c33; color: #f8f3ea; width: 34px; height: 34px; border-radius: 50%; font: italic bold 26px Georgia, serif; text-align: center; }
.wordmark { font-size: 23px; font-weight: 700; letter-spacing: -1px; }
.little-label { margin-left: auto; font-size: 10px; letter-spacing: 1.5px; }
.hero-body { display: flex; justify-content: space-between; align-items: center; padding: 35px 25px 24px 0; }
.eyebrow { font-size: 10px; font-weight: 700; letter-spacing: 1.5px; margin-bottom: 14px; }
.hero h1 { font: 64px/1.04 Georgia, serif; letter-spacing: -2px; margin: 0; }
.hero h1 span { color: #c86245; font-style: italic; }
.hero p { margin: 18px 0 0; font-size: 15px; color: #59635a; }
.hero-art { width: 255px; text-align: center; transform: rotate(3deg); }
.hero-art svg { width: 100%; }
.art-note { font: italic 15px Georgia, serif; color: #59635a; }
.hero-footer { display: flex; gap: 35px; border-top: 1px solid #d9d2c5; padding: 17px 0; font-size: 10px; font-weight: 700; letter-spacing: 1px; }
.mock-note { margin-left: auto; color: #6c7267; font-weight: 400; letter-spacing: 0; }
#search-box { background: #eee7db; border: 1px solid #dfd7c9; padding: 24px; border-radius: 14px; }
#search-box .block { background: transparent; border: none; box-shadow: none; }
#search-box .form, #caption-card .form { background: transparent !important; }
#search-box label { color: #243c33 !important; }
#search-box label:has(input[type="radio"]) { background: #fffdf8 !important; border: 1px solid #d9d2c5 !important; }
#search-box label:has(input[type="radio"]:checked) { background: #e7ece4 !important; }
#search-box textarea { background: #fffdf8 !important; border-radius: 9px; font-size: 16px; }
#find-button { min-height: 48px; font-size: 15px; border-radius: 9px; background: #243c33 !important; color: #fffdf8 !important; }
.result-card { background: #fffdf8; border: 1px solid #dfd7c9 !important; border-radius: 14px !important; padding: 22px !important; min-height: 245px; }
.result-card .block { background: transparent !important; border: none !important; box-shadow: none !important; }
.result-card h3 { font-family: Georgia, serif; font-size: 23px !important; font-weight: 400; line-height: 1.2; }
.card-kicker p { color: #9c543e; font-size: 10px !important; font-weight: 700; letter-spacing: 1.5px; }
#caption-card { background: #e7ece4; }
#caption-card textarea { background: transparent !important; border: none !important; font: 18px/1.55 Georgia, serif !important; }
#status { color: #626b5d; font-size: 13px; }
#status p { margin-bottom: 8px; }
.footer-note { text-align: center; font-size: 11px; color: #747a6c; padding-top: 8px; }
@media (max-width: 700px) { .gradio-container { padding: 16px !important; } .hero-body { padding-right: 0; } .hero h1 { font-size: 47px; } .hero-art { width: 140px; } .hero-footer { gap: 16px; } .mock-note, .little-label { display: none; } }
'''


def build_interface():
    with gr.Blocks(title='FitFindr', analytics_enabled=False) as demo:
        profile = gr.BrowserState({}, storage_key='fitfindr-style-v1', secret='fitfindr-local-style-profile-v1')
        gr.HTML(HERO)
        with gr.Column(elem_id='search-box'):
            with gr.Row():
                query_input = gr.Textbox(label='What are you looking for?', placeholder='Vintage graphic tee under $30, size M', lines=2, scale=3)
                wardrobe_choice = gr.Radio(choices=WARDROBE_CHOICES, value=WARDROBE_CHOICES[0], label='Your wardrobe', scale=2)
            with gr.Accordion('Your clothes & style', open=False):
                preferences = gr.Textbox(label='What do you like?', placeholder='Loose fits, earth tones, chunky sneakers', lines=1)
                wardrobe_text = gr.Textbox(label='Your clothes — used with “Add my clothes”', placeholder='bottoms: baggy blue jeans\nshoes: chunky white sneakers\ntops: white tank', lines=3)
                with gr.Row():
                    save_button = gr.Button('Save my style', size='sm')
                    clear_button = gr.Button('Clear saved style', size='sm')
                profile_status = gr.Markdown('')
                gr.Markdown('Saved only in this browser. The example wardrobe has jeans, tees, sneakers, boots, and a jacket.')
            submit_button = gr.Button('Find my fit ↗', variant='primary', elem_id='find-button')
        gr.Examples(examples=[[q] for q in EXAMPLE_QUERIES], inputs=[query_input], label='Try a find')
        status = gr.Markdown('', elem_id='status')
        with gr.Row(equal_height=True):
            with gr.Column(elem_classes=['result-card']):
                gr.Markdown('01 / THE FIND', elem_classes=['card-kicker'])
                listing_output = gr.Markdown('Your next good find starts above.')
            with gr.Column(elem_classes=['result-card']):
                gr.Markdown('02 / THE OUTFIT', elem_classes=['card-kicker'])
                outfit_output = gr.Markdown('A little inspiration for what you already own.')
            with gr.Column(elem_classes=['result-card'], elem_id='caption-card'):
                gr.Markdown('03 / THE FIT CARD', elem_classes=['card-kicker'])
                card_output = gr.Textbox(label='Your caption', show_label=False, placeholder='Your shareable caption will appear here.', lines=7, interactive=False, buttons=['copy'])
        with gr.Accordion('How it worked', open=False):
            history = gr.Markdown('Run a search to see each step.')
            with gr.Accordion('View stored results', open=False):
                state_output = gr.JSON(label='Results passed between tools')
        gr.HTML('<div class="footer-note">Made for secondhand style. Listings and price checks use sample data.</div>')
        inputs = [query_input, wardrobe_choice, wardrobe_text, preferences]
        outputs = [listing_output, outfit_output, card_output, status, history, state_output]
        submit_button.click(handle_query_detailed, inputs, outputs, api_name='find_fit', concurrency_limit=4)
        query_input.submit(handle_query_detailed, inputs, outputs, api_name=False, concurrency_limit=4)
        save_button.click(save_profile, [wardrobe_choice, wardrobe_text, preferences], [profile, profile_status], api_name=False)
        clear_button.click(clear_profile, [], [profile, wardrobe_choice, wardrobe_text, preferences, profile_status], api_name=False)
        demo.load(restore_profile, profile, [wardrobe_choice, wardrobe_text, preferences, profile_status], api_name=False)
    return demo


def launch_app():
    theme = gr.themes.Base(primary_hue='orange', neutral_hue='stone', font=['Arial', 'sans-serif']).set(
        body_background_fill='#f8f3ea', body_background_fill_dark='#f8f3ea',
        body_text_color='#243c33', body_text_color_dark='#243c33',
        block_background_fill='#fffdf8', block_background_fill_dark='#fffdf8',
        button_primary_background_fill='#243c33', button_primary_background_fill_dark='#243c33',
        button_primary_background_fill_hover='#365648', button_primary_text_color='#fffdf8',
        input_background_fill='#fffdf8', input_background_fill_dark='#fffdf8',
    )
    build_interface().launch(server_name='127.0.0.1', share=False, theme=theme, css=CSS, footer_links=[], blocked_paths=[str(Path(__file__).with_name('.env')), str(Path(__file__).with_name('.git'))])


if __name__ == '__main__':
    launch_app()
