#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import html as html_lib
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont


DEFAULT_COLORS = ['#d84b4b', '#2f6de1', '#19a974', '#8b5cf6', '#f59e0b']
HOME_COLOR = '#6b7280'
TEXT_COLOR = '#1f2937'

FONT_CANDIDATES = [
    '/System/Library/Fonts/Hiragino Sans GB.ttc',
    '/System/Library/Fonts/STHeiti Medium.ttc',
    '/System/Library/Fonts/STHeiti Light.ttc',
    '/System/Library/Fonts/Supplemental/Songti.ttc',
]


@dataclass
class Point:
    key: str
    seq: int | None
    name: str
    query: str | None = None
    lat: float | None = None
    lon: float | None = None
    time_text: str = ''
    optional: bool = False
    label: str | None = None
    label_offset: tuple[int, int] | None = None
    note: str | None = None
    kind: str = 'sight'


@dataclass
class Day:
    day: int
    label: str
    points: list[Point] = field(default_factory=list)
    color: str | None = None
    line_style: str = 'solid'


def pick_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        p = Path(path)
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def mercator(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    scale = 256 * (2**zoom)
    x = (lon + 180.0) / 360.0 * scale
    lat_r = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * scale
    return x, y


def geocode(query: str, session: requests.Session, cache: dict[str, tuple[float, float]]) -> tuple[float, float]:
    if query in cache:
        return cache[query]
    headers = {'User-Agent': 'CodexTravelItineraryMap/1.0 (html-renderer)'}
    r = session.get(
        'https://nominatim.openstreetmap.org/search',
        params={'format': 'jsonv2', 'limit': 1, 'q': query},
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if not data:
        raise ValueError(f'Geocoding failed for {query!r}')
    lat = float(data[0]['lat'])
    lon = float(data[0]['lon'])
    cache[query] = (lat, lon)
    time.sleep(1)
    return lat, lon


def fetch_tile(z: int, x: int, y: int, session: requests.Session, cache_dir: Path) -> bytes:
    tile_path = cache_dir / str(z) / str(x) / f'{y}.png'
    tile_path.parent.mkdir(parents=True, exist_ok=True)
    if tile_path.exists():
        return tile_path.read_bytes()
    url = f'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
    r = session.get(url, headers={'User-Agent': 'CodexTravelItineraryMap/1.0'}, timeout=30)
    r.raise_for_status()
    tile_path.write_bytes(r.content)
    return r.content


def multiline_text_bbox(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font, spacing: int = 4):
    return draw.multiline_textbbox(xy, text, font=font, spacing=spacing, stroke_width=1)


def css_rgba(hex_color: str, alpha: float) -> str:
    color = hex_color.strip().lstrip('#')
    if len(color) != 6:
        return hex_color
    r = int(color[0:2], 16)
    g = int(color[2:4], 16)
    b = int(color[4:6], 16)
    return f'rgba({r},{g},{b},{alpha:.2f})'


def slug(value: str) -> str:
    return ''.join(ch.lower() if ch.isalnum() else '-' for ch in value).strip('-') or 'item'


def circled_number(seq: int | None) -> str:
    if seq is None:
        return ''
    if 1 <= seq <= 20:
        return chr(0x245F + seq)
    return f'({seq})'


def point_center(point: Point, projected: dict[str, tuple[float, float]], tile_origin: tuple[int, int], outer: tuple[int, int]) -> tuple[int, int]:
    x, y = projected[point.key]
    tile_x0, tile_y0 = tile_origin
    ox, oy = outer
    return int(round(x - tile_x0 * 256 + ox)), int(round(y - tile_y0 * 256 + oy))


def default_label_offset(point: Point, point_xy: tuple[int, int], canvas_size: tuple[int, int]) -> tuple[int, int]:
    if point.label_offset:
        return point.label_offset
    cx, cy = point_xy
    canvas_w, canvas_h = canvas_size
    if point.kind == 'home':
        return (18, -84)
    if point.optional:
        return (24, -92) if point.seq and point.seq % 2 else (-252, -92)
    dx = 24 if cx < canvas_w / 2 else -252
    dy = 16 if cy < canvas_h / 2 else -84
    if point.seq is not None and point.seq % 3 == 0:
        dy -= 18
    return dx, dy


def normalize_input(raw: dict[str, Any]) -> tuple[Point | None, list[Day]]:
    home = None
    if raw.get('home'):
        h = raw['home']
        home = Point(
            key='home',
            seq=None,
            name=h.get('name', 'Home'),
            query=h.get('query'),
            lat=h.get('lat'),
            lon=h.get('lon'),
            label=h.get('label'),
            note=h.get('note'),
            kind='home',
        )

    days: list[Day] = []
    for day_raw in raw.get('days', []):
        points: list[Point] = []
        for idx, p in enumerate(day_raw.get('points', []), start=1):
            seq = int(p.get('seq', idx))
            points.append(
                Point(
                    key=f"d{day_raw['day']}_{seq}",
                    seq=seq,
                    name=p.get('name', p.get('label', f'Point {seq}')),
                    query=p.get('query'),
                    lat=p.get('lat'),
                    lon=p.get('lon'),
                    time_text=p.get('time', ''),
                    optional=bool(p.get('optional', False)),
                    label=p.get('label'),
                    label_offset=tuple(p['label_offset']) if p.get('label_offset') else None,
                    note=p.get('note'),
                )
            )
        days.append(
            Day(
                day=int(day_raw['day']),
                label=str(day_raw.get('label', f"Day {day_raw['day']}")),
                points=points,
                color=day_raw.get('color'),
                line_style=day_raw.get('line_style', 'solid'),
            )
        )
    return home, days


def clip_box(box: list[int], width: int, height: int, margin: int = 12) -> list[int]:
    x1, y1, x2, y2 = box
    if x1 < margin:
        dx = margin - x1
        box = [x1 + dx, y1, x2 + dx, y2]
    if y1 < margin:
        dy = margin - y1
        box = [box[0], y1 + dy, box[2], y2 + dy]
    if box[2] > width - margin:
        dx = (width - margin) - box[2]
        box = [box[0] + dx, box[1], box[2] + dx, box[3]]
    if box[3] > height - margin:
        dy = (height - margin) - box[3]
        box = [box[0], box[1] + dy, box[2], box[3] + dy]
    return box


def overlap_area(a: list[int], b: list[int]) -> int:
    x_overlap = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    y_overlap = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return x_overlap * y_overlap


def expand_box(box: list[int], padding: int = 10) -> list[int]:
    return [box[0] - padding, box[1] - padding, box[2] + padding, box[3] + padding]


def choose_label_box(
    anchor: tuple[int, int],
    box_w: int,
    box_h: int,
    canvas_size: tuple[int, int],
    placed_boxes: list[list[int]],
    preferred_offset: tuple[int, int] | None = None,
) -> list[int]:
    x, y = anchor
    canvas_w, canvas_h = canvas_size
    offsets: list[tuple[int, int]] = []
    if preferred_offset:
        offsets.append(preferred_offset)
    offsets.extend(
        [
            (28, -box_h - 18),
            (28, 22),
            (-box_w - 28, -box_h - 18),
            (-box_w - 28, 22),
            (-box_w // 2, -box_h - 36),
            (-box_w // 2, 34),
            (52, -box_h // 2),
            (-box_w - 52, -box_h // 2),
            (92, -box_h - 58),
            (-box_w - 92, -box_h - 58),
            (92, 62),
            (-box_w - 92, 62),
            (28, -box_h - 120),
            (-box_w - 28, -box_h - 120),
            (28, 126),
            (-box_w - 28, 126),
        ]
    )

    best: tuple[float, list[int]] | None = None
    seen: set[tuple[int, int]] = set()
    for dx, dy in offsets:
        if (dx, dy) in seen:
            continue
        seen.add((dx, dy))
        raw = [x + dx, y + dy, x + dx + box_w, y + dy + box_h]
        box = clip_box(raw, canvas_w, canvas_h)
        total_overlap = sum(overlap_area(box, other) for other in placed_boxes)
        movement = abs(box[0] - raw[0]) + abs(box[1] - raw[1])
        distance = abs(dx) + abs(dy)
        score = total_overlap * 1000 + movement * 8 + distance
        if best is None or score < best[0]:
            best = (score, box)
        if total_overlap == 0 and movement == 0:
            break
    assert best is not None
    return best[1]


def path_d(points: list[tuple[int, int]]) -> str:
    return ' '.join([f'M {points[0][0]} {points[0][1]}'] + [f'L {x} {y}' for x, y in points[1:]])


def build_html(config: dict[str, Any], output_dir: Path) -> Path:
    home, days = normalize_input(config)
    if not days:
        raise ValueError('No days were supplied')

    zoom = int(config.get('zoom', 15))
    title = config.get('title', 'Travel itinerary map')
    subtitle = config.get('subtitle', '')
    footnote = config.get('footnote', '底图：OpenStreetMap contributors；点位来自真实坐标投影')
    note = config.get('note', '不同颜色/线型表示不同日期；机动点用“机动”标记并以半透明样式呈现；住宿区域用代表点近似表示。')
    output_basename = config.get('output_basename', 'itinerary_map')
    connect_home = bool(config.get('connect_home', bool(config.get('home'))))

    session = requests.Session()
    geocode_cache: dict[str, tuple[float, float]] = {}

    all_points: list[Point] = []
    if home:
        if home.lat is None or home.lon is None:
            if not home.query:
                raise ValueError('Home point needs either query or lat/lon')
            home.lat, home.lon = geocode(home.query, session, geocode_cache)
        all_points.append(home)

    for day in days:
        for p in day.points:
            if p.lat is None or p.lon is None:
                if not p.query:
                    raise ValueError(f'Point {p.name!r} needs either query or lat/lon')
                p.lat, p.lon = geocode(p.query, session, geocode_cache)
            all_points.append(p)

    projected = {p.key: mercator(p.lat, p.lon, zoom) for p in all_points}
    xs = [x for x, _ in projected.values()]
    ys = [y for _, y in projected.values()]

    pad_x = int(config.get('pad_x', 380))
    pad_y = int(config.get('pad_y', 320))
    minx = min(xs) - pad_x
    maxx = max(xs) + pad_x
    miny = min(ys) - pad_y
    maxy = max(ys) + pad_y

    tile_x0 = math.floor(minx / 256)
    tile_x1 = math.floor(maxx / 256)
    tile_y0 = math.floor(miny / 256)
    tile_y1 = math.floor(maxy / 256)

    base_w = (tile_x1 - tile_x0 + 1) * 256
    base_h = (tile_y1 - tile_y0 + 1) * 256

    outer_left = int(config.get('outer_left', 280))
    outer_top = int(config.get('outer_top', 210))
    outer_right = int(config.get('outer_right', 260))
    outer_bottom = int(config.get('outer_bottom', 260))
    canvas_w = base_w + outer_left + outer_right
    canvas_h = base_h + outer_top + outer_bottom

    coords = [(x, y) for x in range(tile_x0, tile_x1 + 1) for y in range(tile_y0, tile_y1 + 1)]
    cache_dir = output_dir / '.tile-cache'
    tiles: list[tuple[int, int, str]] = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(fetch_tile, zoom, x, y, session, cache_dir): (x, y) for x, y in coords}
        for fut in as_completed(futures):
            x, y = futures[fut]
            data = fut.result()
            tiles.append((x, y, 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')))

    tiles.sort(key=lambda item: (item[1], item[0]))

    measure_draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    label_font = pick_font(18)

    day_colors: dict[int, str] = {}
    for i, day in enumerate(days):
        day_colors[day.day] = day.color or DEFAULT_COLORS[i % len(DEFAULT_COLORS)]

    tile_origin = (tile_x0, tile_y0)

    route_paths: list[str] = []
    route_data: list[dict[str, Any]] = []
    for day in days:
        day_key = f'day-{slug(str(day.day))}'
        route_points: list[Point] = []
        if home and connect_home and day.points:
            route_points.append(home)
        route_points.extend(day.points)
        if home and connect_home and day.points:
            route_points.append(home)
        route_points_payload = []
        for p in route_points:
            x, y = point_center(p, projected, tile_origin, (outer_left, outer_top))
            route_points_payload.append({'key': p.key, 'x': x, 'y': y, 'optional': p.optional, 'home': p.kind == 'home'})
        route_data.append({'dayClass': day_key, 'points': route_points_payload})
        if len(route_points_payload) >= 2:
            color = day_colors[day.day]
            dash = ' stroke-dasharray="18 12"' if day.line_style == 'dashed' else ''
            route_paths.append(
                f'<path class="map-route {day_key}" data-route-day="{day_key}" d="" fill="none" stroke="{color}" stroke-width="6" stroke-linejoin="round" stroke-linecap="round"{dash} />'
            )

    marker_elems: list[str] = []
    if home:
        hx, hy = point_center(home, projected, tile_origin, (outer_left, outer_top))
        marker_elems.append(
            f'<g class="map-item home-item"><circle cx="{hx}" cy="{hy}" r="16" fill="{HOME_COLOR}" stroke="#fff" stroke-width="3"></circle>'
            f'<text x="{hx}" y="{hy + 6}" text-anchor="middle" font-family="Hiragino Sans GB, PingFang SC, Microsoft YaHei, sans-serif" '
            f'font-size="18" font-weight="700" fill="#fff">S</text></g>'
        )

    for day in days:
        color = day_colors[day.day]
        day_key = f'day-{slug(str(day.day))}'
        for p in day.points:
            x, y = point_center(p, projected, tile_origin, (outer_left, outer_top))
            fill_opacity = '0.45' if p.optional else '1'
            optional_class = ' optional-item' if p.optional else ''
            marker_elems.append(
                f'<g class="map-item {day_key}{optional_class}"><circle cx="{x}" cy="{y}" r="{15 if p.optional else 16}" fill="{color}" fill-opacity="{fill_opacity}" stroke="#fff" stroke-width="3"></circle>'
                f'<text x="{x}" y="{y + 6}" text-anchor="middle" font-family="Hiragino Sans GB, PingFang SC, Microsoft YaHei, sans-serif" '
                f'font-size="18" font-weight="700" fill="#fff">{p.seq}</text></g>'
            )

    label_divs: list[str] = []
    placed_label_boxes: list[list[int]] = [
        [20, 18, 650, 150],
        [canvas_w - 824, canvas_h - 190, canvas_w - 24, canvas_h - 24],
    ]
    for p in all_points:
        px, py = point_center(p, projected, tile_origin, (outer_left, outer_top))
        placed_label_boxes.append([px - 42, py - 42, px + 42, py + 42])

    if home:
        hx, hy = point_center(home, projected, tile_origin, (outer_left, outer_top))
        home_text = f'{home.label or home.name}\n{home.note or ""}'.strip()
        bbox = multiline_text_bbox(measure_draw, (0, 0), home_text, label_font, spacing=4)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        box_w = max(320, w + 24)
        box_h = h + 24
        box = choose_label_box((hx, hy), box_w, box_h, (canvas_w, canvas_h), placed_label_boxes, home.label_offset or (18, -84))
        placed_label_boxes.append(expand_box(box))
        lines = [html_lib.escape(line) for line in home_text.split('\n')]
        label_divs.append(
            f'<div class="label-box map-item home-item" style="left:{box[0]}px; top:{box[1]}px; width:{box_w}px; min-height:{box_h}px; border-color:{HOME_COLOR};">'
            f'<div class="label-title">{lines[0]}</div>'
            + (f'<div class="label-time">{lines[1]}</div>' if len(lines) > 1 else '')
            + (f'<div class="label-note">{lines[2]}</div>' if len(lines) > 2 else '')
            + '</div>'
        )

    for day in days:
        color = day_colors[day.day]
        day_key = f'day-{slug(str(day.day))}'
        for p in day.points:
            x, y = point_center(p, projected, tile_origin, (outer_left, outer_top))
            border = css_rgba(color, 0.48) if p.optional else color
            label_style = ' background:rgba(255,255,255,0.76);' if p.optional else ''
            display = p.label or p.name
            if p.optional:
                display = f'机动·{display}'
            text_lines = [f'{day.label} {circled_number(p.seq)} {display}', p.time_text]
            if p.note:
                text_lines.append(p.note)
            text = '\n'.join(line for line in text_lines if line)
            if p.kind == 'home':
                text = f'{display}\n{p.note or ""}'.strip()
            dx, dy = p.label_offset or default_label_offset(p, (x, y), (canvas_w, canvas_h))
            bbox = multiline_text_bbox(measure_draw, (0, 0), text, label_font, spacing=4)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            if p.kind == 'home':
                box_w = max(300, w + 24)
            else:
                box_w = max(250, w + 24)
            box_h = h + 24
            box = choose_label_box((x, y), box_w, box_h, (canvas_w, canvas_h), placed_label_boxes, (dx, dy))
            placed_label_boxes.append(expand_box(box))
            lines = [html_lib.escape(line) for line in text.split('\n')]
            time_html = f'<div class="label-time">{lines[1]}</div>' if len(lines) > 1 else ''
            note_html = f'<div class="label-note">{lines[2]}</div>' if len(lines) > 2 else ''
            optional_class = ' optional-item' if p.optional else ''
            label_divs.append(
                f'<div class="label-box map-item {day_key}{optional_class}" style="left:{box[0]}px; top:{box[1]}px; width:{box_w}px; min-height:{box_h}px; border-color:{border};{label_style}">'
                f'<div class="label-title">{lines[0]}</div>{time_html}{note_html}</div>'
            )

    title_html = html_lib.escape(title)
    subtitle_html = html_lib.escape(subtitle)
    footnote_html = html_lib.escape(footnote)
    note_html = html_lib.escape(note)

    legend_day_html = []
    for idx, day in enumerate(days[:2]):
        line_style = f'border-top:6px {"dashed" if day.line_style == "dashed" else "solid"} {day_colors[day.day]};'
        day_key = f'day-{slug(str(day.day))}'
        legend_day_html.append(
            f'<label class="legend-row"><input class="legend-filter" type="checkbox" data-target=".{day_key}" checked>'
            f'<span class="legend-line" style="{line_style}"></span><span>{html_lib.escape(day.label)} 路线/点位/信息</span></label>'
        )
    optional_legend_color = css_rgba(day_colors[days[0].day], 0.45)
    route_data_json = json.dumps(route_data, ensure_ascii=False)

    tiles_html = []
    for x, y, data_uri in tiles:
        tiles_html.append(
            f'<img class="tile" src="{data_uri}" style="left:{(x - tile_x0) * 256}px; top:{(y - tile_y0) * 256}px;" alt="tile">'
        )

    html_doc = f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title_html}</title>
  <style>
    :root {{
      --bg: #ffffff;
      --panel: rgba(255,255,255,0.94);
      --border: #d6dbe1;
      --text: #1f2937;
      --muted: #5b6472;
    }}
    html, body {{ margin: 0; padding: 0; background: #f3f4f6; color: var(--text); overflow: hidden; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Hiragino Sans GB", "PingFang SC", "Microsoft YaHei", sans-serif; }}
    .viewport {{ width: 100vw; height: 100vh; padding: 12px; box-sizing: border-box; overflow: auto; display: grid; place-items: center; }}
    .viewport.is-overflowing {{ place-items: start; }}
    .stage {{ width: calc({canvas_w}px * var(--map-scale, 1)); height: calc({canvas_h}px * var(--map-scale, 1)); position: relative; }}
    .page {{ width: {canvas_w}px; height: {canvas_h}px; background: var(--bg); position: relative; overflow: hidden; transform: scale(var(--map-scale, 1)); transform-origin: top left; }}
    .zoom-controls {{ position: fixed; right: 18px; top: 18px; z-index: 30; display: flex; align-items: center; gap: 8px; background: rgba(255,255,255,0.96); border: 1px solid var(--border); border-radius: 12px; padding: 8px; box-shadow: 0 8px 24px rgba(31,41,55,0.12); }}
    .zoom-controls button {{ min-width: 34px; height: 34px; border: 1px solid #cfd6df; background: #fff; color: var(--text); border-radius: 8px; font-size: 16px; font-weight: 700; cursor: pointer; }}
    .zoom-controls button:hover {{ background: #f8fafc; }}
    .zoom-value {{ min-width: 48px; text-align: center; font-size: 14px; color: var(--muted); }}
    .title-box {{ position: absolute; left: 20px; top: 18px; z-index: 10; background: var(--panel); border: 1px solid var(--border); border-radius: 18px; padding: 14px 18px 12px; max-width: 600px; box-shadow: 0 1px 0 rgba(0,0,0,0.02); }}
    .title-box h1 {{ margin: 0; font-size: 42px; line-height: 1.05; font-weight: 700; letter-spacing: 0; }}
    .title-box .sub {{ margin-top: 4px; font-size: 20px; color: var(--muted); line-height: 1.25; }}
    .map {{ position: absolute; left: 280px; top: 210px; width: {base_w}px; height: {base_h}px; overflow: hidden; border: 2px solid rgba(255,255,255,0.9); box-sizing: border-box; }}
    .tile {{ position: absolute; width: 256px; height: 256px; image-rendering: auto; }}
    svg.overlay {{ position: absolute; left: 0; top: 0; width: {canvas_w}px; height: {canvas_h}px; pointer-events: none; overflow: visible; }}
    .label-box {{ position: absolute; z-index: 9; background: rgba(255,255,255,0.95); border: 3px solid; border-radius: 12px; padding: 10px 12px; box-sizing: border-box; font-size: 18px; line-height: 1.28; color: var(--text); box-shadow: 0 1px 0 rgba(0,0,0,0.02); white-space: normal; }}
    .label-title {{ font-weight: 700; margin-bottom: 2px; white-space: pre-line; }}
    .label-time {{ color: #374151; white-space: pre-line; }}
    .label-note {{ color: #374151; white-space: pre-line; margin-top: 2px; }}
    .legend {{ position: absolute; right: 24px; bottom: 24px; width: 780px; background: var(--panel); border: 1px solid var(--border); border-radius: 18px; padding: 16px 18px 14px; z-index: 10; }}
    .legend-head {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 10px; }}
    .legend-title {{ font-size: 16px; font-weight: 700; }}
    .legend-toggle-label {{ display: inline-flex; align-items: center; gap: 8px; font-size: 15px; color: var(--muted); user-select: none; cursor: pointer; }}
    .legend-toggle-label input {{ width: 16px; height: 16px; accent-color: #1f2937; }}
    .legend-body[hidden] {{ display: none; }}
    .legend-row {{ display: flex; align-items: center; gap: 12px; font-size: 16px; margin-bottom: 10px; cursor: pointer; user-select: none; }}
    .legend-row input {{ width: 16px; height: 16px; accent-color: #1f2937; flex: 0 0 auto; }}
    .legend-line {{ width: 44px; height: 0; border-radius: 999px; display: inline-block; }}
    .legend-dot {{ width: 12px; height: 12px; border-radius: 999px; display: inline-block; border: 2px solid #fff; box-shadow: 0 0 0 1px rgba(0,0,0,0.1); }}
    .legend-note {{ font-size: 15px; color: var(--muted); line-height: 1.35; margin-top: 8px; white-space: pre-line; }}
    .legend-foot {{ font-size: 15px; color: var(--muted); line-height: 1.35; margin-top: 8px; white-space: pre-line; }}
    @media print {{
      .viewport {{ padding: 0; overflow: visible; }}
      .stage {{ width: {canvas_w}px; height: {canvas_h}px; }}
      .page {{ transform: none; }}
      body {{ background: #fff; }}
    }}
  </style>
</head>
<body>
  <div class="zoom-controls" aria-label="地图缩放控件">
    <button type="button" data-zoom="out" aria-label="缩小地图">−</button>
    <span class="zoom-value" aria-live="polite">100%</span>
    <button type="button" data-zoom="in" aria-label="放大地图">+</button>
    <button type="button" data-zoom="fit">适配</button>
  </div>
  <div class="viewport">
  <div class="stage">
  <div class="page" data-width="{canvas_w}" data-height="{canvas_h}">
    <div class="title-box">
      <h1>{title_html}</h1>
      <div class="sub">{subtitle_html}</div>
    </div>
    <div class="map">
      {''.join(tiles_html)}
    </div>
    <svg class="overlay" viewBox="0 0 {canvas_w} {canvas_h}" aria-hidden="true">
      <rect x="280" y="210" width="{base_w}" height="{base_h}" fill="none" stroke="rgba(255,255,255,0.95)" stroke-width="2"></rect>
      {''.join(route_paths)}
      {''.join(marker_elems)}
    </svg>
    {''.join(label_divs)}
    <div class="legend">
      <div class="legend-head">
        <div class="legend-title">图例</div>
        <label class="legend-toggle-label"><input class="legend-toggle" type="checkbox" checked onchange="document.querySelector('.legend-body').hidden = !this.checked">显示图例</label>
      </div>
      <div class="legend-body">
        {''.join(legend_day_html)}
        <label class="legend-row"><input class="legend-filter" type="checkbox" data-target=".optional-item" checked><span class="legend-dot" style="background:{optional_legend_color}"></span><span>机动：同日颜色半透明</span></label>
        <label class="legend-row"><input class="legend-filter" type="checkbox" data-target=".home-item" checked><span class="legend-dot" style="background:{HOME_COLOR}"></span><span>住宿区域代表点</span></label>
        <div class="legend-note">{note_html}</div>
        <div class="legend-foot">{footnote_html}</div>
      </div>
    </div>
  </div>
  </div>
  </div>
  <script>
    (() => {{
      const page = document.querySelector('.page');
      const stage = document.querySelector('.stage');
      const viewport = document.querySelector('.viewport');
      const originalWidth = Number(page.dataset.width);
      const originalHeight = Number(page.dataset.height);
      const zoomValue = document.querySelector('.zoom-value');
      const routeData = {route_data_json};
      let fitScale = 1;
      let userZoom = 1;
      const fit = () => {{
        const styles = getComputedStyle(viewport);
        const padX = parseFloat(styles.paddingLeft) + parseFloat(styles.paddingRight);
        const padY = parseFloat(styles.paddingTop) + parseFloat(styles.paddingBottom);
        const availableWidth = Math.max(320, window.innerWidth - padX);
        const availableHeight = Math.max(320, window.innerHeight - padY);
        fitScale = Math.min(availableWidth / originalWidth, availableHeight / originalHeight, 1);
        const scale = fitScale * userZoom;
        document.documentElement.style.setProperty('--map-scale', String(scale));
        stage.style.width = `${{originalWidth * scale}}px`;
        stage.style.height = `${{originalHeight * scale}}px`;
        viewport.classList.toggle('is-overflowing', originalWidth * scale > availableWidth || originalHeight * scale > availableHeight);
        zoomValue.textContent = `${{Math.round(userZoom * 100)}}%`;
      }};
      fit();
      window.addEventListener('resize', fit, {{ passive: true }});
      document.querySelectorAll('[data-zoom]').forEach((button) => {{
        button.addEventListener('click', () => {{
          const action = button.dataset.zoom;
          if (action === 'in') userZoom = Math.min(3, userZoom + 0.15);
          if (action === 'out') userZoom = Math.max(0.4, userZoom - 0.15);
          if (action === 'fit') userZoom = 1;
          fit();
        }});
      }});
      const updateFilters = () => {{
        document.querySelectorAll('.map-item').forEach((item) => {{ item.style.display = ''; }});
        document.querySelectorAll('.legend-filter').forEach((box) => {{
          if (!box.checked) {{
            document.querySelectorAll(box.dataset.target).forEach((item) => {{ item.style.display = 'none'; }});
          }}
        }});
        const optionalVisible = document.querySelector('.legend-filter[data-target=".optional-item"]')?.checked ?? true;
        const homeVisible = document.querySelector('.legend-filter[data-target=".home-item"]')?.checked ?? true;
        const visibleDayClasses = new Set(
          Array.from(document.querySelectorAll('.legend-filter[data-target^=".day-"]'))
            .filter((box) => box.checked)
            .map((box) => box.dataset.target.slice(1))
        );
        routeData.forEach((route) => {{
          const path = document.querySelector(`.map-route[data-route-day="${{route.dayClass}}"]`);
          if (!path) return;
          if (!visibleDayClasses.has(route.dayClass)) {{
            path.setAttribute('d', '');
            return;
          }}
          const visiblePoints = route.points.filter((point) => {{
            if (point.home && !homeVisible) return false;
            if (point.optional && !optionalVisible) return false;
            return true;
          }});
          if (visiblePoints.length < 2) {{
            path.setAttribute('d', '');
            return;
          }}
          const d = visiblePoints.map((point, index) => `${{index === 0 ? 'M' : 'L'}} ${{point.x}} ${{point.y}}`).join(' ');
          path.setAttribute('d', d);
        }});
      }};
      document.querySelectorAll('.legend-filter').forEach((box) => {{ box.addEventListener('change', updateFilters); }});
      updateFilters();
    }})();
  </script>
</body>
</html>
'''

    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / f'{output_basename}.html'
    html_path.write_text(html_doc, encoding='utf-8')
    return html_path


def main() -> int:
    parser = argparse.ArgumentParser(description='Render a real-map travel itinerary HTML page.')
    parser.add_argument('--input', required=True, help='Path to itinerary JSON file')
    parser.add_argument('--output-dir', default='outputs', help='Directory for HTML output')
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    with input_path.open('r', encoding='utf-8') as f:
        config = json.load(f)
    html_path = build_html(config, output_dir)
    print(html_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
