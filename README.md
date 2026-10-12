# FitFindr

Find secondhand clothes, build an outfit, and get a caption to share.
Uses 40 sample listings, your wardrobe, and Groq.

[My GitHub repo](https://github.com/shreejaysubedi/ai201-project2-fitfindr-starter)

## Run it

Python 3.10 or newer:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

On Windows, activate with `.venv\Scripts\activate`.
Add your Groq key to `.env`, then run:

```bash
python app.py
```

Open the local URL printed in the terminal. `.env` is ignored by Git.
Without a key, the app still works with clearly marked local outfit ideas and
captions. Those fallbacks are not AI replies.

The course model is `meta-llama/llama-4-scout-17b-16e-instruct`.
Groq [retired it on July 17, 2026](https://console.groq.com/docs/deprecations),
so the app tries it first, then uses `openai/gpt-oss-120b` if unavailable.
The app shows the switch. Optional `.env` settings are in `.env.example`.

## Use it

Try `vintage graphic tee under $30, size M`. Choose the example wardrobe,
an empty wardrobe, or add your clothes under **Your clothes & style**:

```text
bottoms: baggy blue jeans
shoes: chunky white sneakers
tops: white tank
```

Add a style note and click **Save my style** to remember these choices across
sessions in this browser. **Clear saved style** removes them.
**How it worked** shows the calls; **View stored results** shows their saved inputs
and outputs. The fit card has a copy button.

## Tool inventory

All four tools are in `tools.py`. The loader reads the supplied data files.

```python
search_listings(description: str, size: str | None = None,
                max_price: float | None = None) -> list[dict]
```

Find matching pieces. `description` names the item/style; `size` is optional;
`max_price` is an inclusive dollar limit. Return ranked listing dicts with
`id`, `title`, `description`, `category`, `style_tags: list[str]`, `size`,
`condition`, `price: float`, `colors: list[str]`, `brand: str | None`, and
`platform`. No matches returns `[]`; bad filters/data raise a handled `ToolError`.

```python
suggest_outfit(new_item: dict, wardrobe: dict) -> str
```

Use the listing and `wardrobe['items']` to suggest a complete outfit with a tip.
Owned pieces have `id`, `name`, `category`, `colors`, `style_tags`, and optional
`notes`. Optional `style_preferences: str` guides the AI. Return outfit text;
missing clothes get labeled suggestions. Bad input returns an `Error:` string.

```python
create_fit_card(outfit: str, new_item: dict) -> str
```

Use the outfit text and the same listing to write a short caption mentioning
the item, price, and platform. Return caption text; missing inputs return an
`Error:` string. Temperature 1.0 helps captions vary.

Both AI tools can return `Fallback: reason\n\ntext` when the service fails,
or `Notice: reason\n\ntext` when the model changes. The loop shows the reason
separately and stores only the useful text.

```python
compare_price(new_item: dict) -> dict
```

Compare the selected listing with other similar sample pieces. Return
`verdict: str`, `median_price: float | None`, `comparable_count: int`,
`comparable_ids: list[str]`, and `message: str`. Exclude the selected item.
With two or more comparisons, within 20% of the median is `fair`;
lower is `below typical`, higher is `above typical`. Otherwise return
`not enough data` or `unavailable`. This rough check excludes shipping.

## Planning loop

`run_agent(query: str, wardrobe: dict) -> dict` reads size and budget from
common phrases, then uses a `while` loop to choose the next tool from saved results:

1. Search. If empty and size was given, retry once without size. Keep the budget
   and item description, and tell the user to check the returned size.
2. If still empty, stop with a useful message. Do not call outfit/card tools.
3. Pick the top result, then check its price. A failed price check does not stop styling.
4. Suggest an outfit. Invalid input stops the loop; an AI failure uses marked local text.
5. Make a card only from a usable outfit. Stop when the card is saved.

A failed later step keeps earlier results visible. Each call is recorded in `steps`.
The full text diagram and original plan are in [planning.md](planning.md).

## State management

Each query gets a fresh session. `parsed` holds description, size, and budget.
`search_attempts`, `retry_used`, and `search_results` track search and retry.
`selected_item` stores the actual top listing dict, which goes into both later
tools. `price_comparison` holds the price check. `outfit_suggestion` is passed
directly into the card tool, then `fit_card` stores its result.
`wardrobe`, `notices`, `steps`, and `error` hold clothes, messages, call history,
and any early stop. Browser memory saves profile settings, not old search results.

## A complete interaction

Query: `I'm looking for a vintage graphic tee under $30. I mostly wear baggy
jeans and chunky sneakers. What's out there and how would I style it?`

1. `search_listings("vintage graphic tee", None, 30.0)` finds tees. The top
   listing is `lst_033`: Vintage Band Tee — Faded Grey, $19, L, depop.
2. `compare_price(selected_item)` finds two other tees; median $21, verdict `fair`.
3. `suggest_outfit(selected_item, wardrobe)` uses that tee and named clothes
   from the example wardrobe. The returned outfit is saved, without re-entry.
4. `create_fit_card(outfit_suggestion, selected_item)` writes the final caption.
   The listing, outfit, caption, price check, and call history appear together.

AI wording varies. A size-M query selects the S/M butterfly tee instead; the
app respects the filter rather than showing the size-L band tee.

## Error handling and checks

- **Search:** `designer ballgown size XXS under $5` fails both searches. The app
  says “No matches in the sample listings. Try a broader item name, another
  size, or a higher budget.” Outfit/card remain unset. Bad data gives a file-fix message.
- **Outfit:** An empty wardrobe gets a complete outfit with labeled extra pieces.
  A small wardrobe uses what fits and suggests missing pieces. Invalid clothes
  stop the card. Missing key, timeout, empty AI reply, and rate limit produce
  a visible reason plus a local outfit.
- **Card:** `create_fit_card('', item)` returns
  `Error: Add an outfit before making a fit card.` Service failures produce a
  local caption based on the real inputs. Warning text never enters the caption.
- **Price check:** Missing data or too few similar pieces returns an explanatory
  message and lets the rest of the workflow continue.

Run the required checks without spending API calls:

```bash
python -m pytest tests/ -q
python utils/data_loader.py
```

Tests cover filters, every tool's failure path, retries, profile settings, and
state passing. Groq replies are mocked in tests; live checks are separate.
See [check results](docs/checks.md) and the saved [failure screenshot](docs/no-results.jpg).

## Spec reflection

**What helped:** Defining each tool's input and output made the handoffs clear.
The diagram made it easy to check that an empty search could never reach the
outfit tool. Tests verify the exact item and outfit passed between tools.

**What changed:** The first plan stopped after any empty search. The final version
retries once without size, while keeping the budget and explaining the change.
That stretch update was added to the plan before its code. The retired course
model also needed a visible replacement path.

## AI use

- Codex received the assignment, Tool blocks, Error Handling, and loader to build
  the individual functions and tests. Review added stricter clothing-kind checks
  so a tee request would not select jeans just because both were vintage.
- Codex used Planning Loop, State Management, and the Mermaid diagram to connect
  the tools. Review kept notices separate from captions and preserved completed
  results when a later tool failed.
- Live review found a reply cut short by the replacement model. The response
  limit was raised and its reasoning setting lowered, then real replies were rechecked.

## Extra features

Price comparison, saved style profiles, and one search retry are implemented.
Trend awareness is not included.

## Demo and submission

**Video:** To be recorded and linked here by me later.

Record 3–5 minutes: run the complete interaction above, open **How it worked**
and **View stored results** to show the same item/outfit passing between tools,
then run the ballgown query to show a handled failure. The video is the only
unfinished project artifact. Submit the repo link through the Course Portal
when the video is ready.
