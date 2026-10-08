# ranking9ja: how to add things

Run `python build.py` from this folder after any change below. It checks your files, rebuilds the pages, and prints the ranking. Then commit and push with GitHub Desktop.

## Add or update a business
Open `data/<category>.json`, copy one business block, and change it. Only put in evidence we have seen or confirmed.
- `gates`: every gate listed in the category file must be `true`, or the business is left out.
- `inputs`: one entry per measure in the category file (rating, counts, and the lists of checks passed).
- Set `"sample": true` only for placeholders. Delete it for real businesses.

## Add a category
1. Copy `categories/dental-abuja.json` to `categories/<new-slug>.json`.
2. Change the label, city, gates and measures. Measure types: `rating`, `banded`, `flags`, `per_item`.
3. The measures must add up to 100. `build.py` stops and tells you if they do not.
4. Create `data/<new-slug>.json` with the businesses.
5. Have someone who knows the field check the measures before the category goes live.

## Rules
- Never put a business's own claim in `inputs`. Only evidence.
- A business that fails a gate is left out entirely.
