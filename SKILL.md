---
name: travel-itinerary-map
description: Generate standalone HTML travel itinerary maps on real map tiles with numbered stops, time labels, route lines, and optional stops marked clearly. Use when the user wants a trip map or route graphic based on actual places, especially when the map must not be invented.
---

# Travel Itinerary Map

Use this skill for travel maps that must sit on a real geographic base map and be delivered as HTML.
Generated HTML should auto-scale the complete map to fit the current browser window without requiring page scrolling at the default fit view, while preserving the fixed high-detail map internally. Include zoom controls so readers can zoom in, zoom out, and return to the fitted view; allow scrolling when a zoomed-in map exceeds the viewport.

For screenshots, use `scripts/screenshot_itinerary_map_html.mjs` with Playwright. Pass the rendered HTML via `--url`, and drive the capture with URL query parameters such as `show=day-1` or `show=day-2&hide=legend,controls&title=10/1 罗马&subtitle=仅展示当天行程`.

Requirements:
- Use real map tiles and real place coordinates only.
- Geocode named places before drawing them.
- Number stops in visit order and print the time beside each stop.
- In each stop information box, format the sequence as circled numerals such as `①`, `②`, `③` when possible.
- Draw a separate route per day, with a distinct color or line style.
- Mark optional stops as `机动` when the itinerary says they are flexible, using the same day color with semi-transparent styling instead of a separate optional color.
- Include per-legend-item checkboxes. Toggling a day hides or shows that day's route line, markers, and information boxes together; toggling optional or lodging entries hides or shows those corresponding markers and boxes. Route lines must be redrawn from the currently visible points, so hiding optional or lodging points reconnects the remaining visible stops in visit order.
- If the user gives an area instead of an exact hotel, use a representative point and label it as the lodging area representative point.
- Do not draw fake streets or precise internal walking paths unless reliable road data is available.
- The screenshot script should read URL query parameters and apply them before capture, so a single rendered HTML file can produce day-specific screenshots without editing the page manually.

For the canonical input shape and the renderer, read [references/input-format.md](references/input-format.md) and use [scripts/render_itinerary_map_html.py](scripts/render_itinerary_map_html.py).
