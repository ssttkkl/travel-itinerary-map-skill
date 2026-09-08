# Travel Itinerary Map Input Format

Use a JSON file like this:

```json
{
  "title": "Rome / Vatican itinerary map",
  "subtitle": "2026-10-01 / 2026-10-02 · real map base · internal walking paths shown only as order",
  "output_basename": "rome_itinerary_map",
  "zoom": 15,
  "connect_home": true,
  "home": {
    "label": "Piazza della Repubblica",
    "query": "Piazza della Repubblica, Rome, Italy",
    "note": "lodging area representative point"
  },
  "days": [
    {
      "day": 1,
      "label": "10/1",
      "color": "#d84b4b",
      "line_style": "solid",
      "points": [
        {
          "seq": 1,
          "name": "Colosseum",
          "query": "Colosseum, Rome, Italy",
          "time": "10:15-13:45",
          "optional": false
        }
      ]
    }
  ]
}
```

Field rules:
- `home` is optional, but required if the user gives a lodging area.
- `connect_home` defaults to `true` when `home` exists. Set it to `false` only when the lodging point should be marked but not connected into each day's route.
- Each point can use either `query` or exact `lat`/`lon`.
- `optional: true` marks a stop as `机动`. Optional stops use the same day color with semi-transparent styling, not a separate optional color.
- `line_style` may be `solid` or `dashed`.
- `color` is optional. If omitted, the renderer chooses a default palette.
- `label_offset` may be added as `[dx, dy]` when labels need manual nudging.

The renderer produces one standalone HTML file. It embeds the map tiles, labels, route overlays, circled sequence labels, per-legend-item visibility checkboxes, and zoom controls directly into the page so the result can be opened as a normal webpage. The page automatically scales the complete map to fit the browser window at the default view, and lets readers zoom in or out from there. When optional or lodging points are hidden, each visible day's route is redrawn through the remaining visible stops in visit order.

Screenshot workflow:
- Use `scripts/screenshot_itinerary_map_html.mjs` with Playwright.
- Pass the HTML URL through `--url` and control the capture with query parameters such as `show=day-1`, `show=day-2&hide=legend,controls`, `title=10/1 罗马`, and `subtitle=仅展示当天行程`.
