# Travel Itinerary Map Skill

A Codex skill for generating standalone travel itinerary maps on real map tiles.

The renderer geocodes real places, embeds OpenStreetMap tiles, labels stops in visit order, adds visit times, draws per-day route overlays, and outputs a standalone HTML file that can be opened directly in a browser.

## Features

- Real map tiles and real geocoded coordinates.
- Numbered itinerary stops with visit times.
- Circled numerals in stop information boxes, such as `①`, `②`, `③`.
- Distinct per-day route color or line style.
- Optional stops marked as `机动` using the same day color with semi-transparent styling.
- Per-legend checkboxes for days, optional stops, and lodging points.
- Routes redraw through the remaining visible stops after filtering optional or lodging points.
- Built-in zoom controls for zooming in, zooming out, and returning to the fitted view.
- Default browser view auto-fits the full map without scrolling.

## Usage

Create an itinerary JSON file using the shape documented in `references/input-format.md`, then run:

```bash
python3 scripts/render_itinerary_map_html.py --input itinerary.json --output-dir outputs
```

The script writes a standalone `.html` file to the output directory.

## Screenshots

Use Playwright through `scripts/screenshot_itinerary_map_html.mjs` to capture a rendered HTML page:

```bash
node scripts/screenshot_itinerary_map_html.mjs --url "file:///path/to/map.html?show=day-1&hide=legend,controls&title=10/1%20罗马" --output outputs/day1.png
```

The screenshot script reads URL query parameters such as `show`, `hide`, `title`, and `subtitle` before capture.

## Dependencies

```bash
python3 -m pip install -r requirements.txt
```

The renderer uses Nominatim for geocoding and OpenStreetMap tiles for the base map. Respect the usage policies of both services when generating maps.
