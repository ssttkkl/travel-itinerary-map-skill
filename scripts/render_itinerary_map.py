#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import time
import textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont


DEFAULT_COLORS = [
    '#d84b4b',
    '#2f6de1',
    '#19a974',
    '#8b5cf6',
    '#f59e0b',
]
HOME_COLOR = '#6b7280'
OPTIONAL_COLOR = '#f59e0b'
TEXT_COLOR = (31, 41, 55, 255)

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
    headers = {'User-Agent': 'CodexTravelItineraryMap/1.0 (real-map-renderer)'}
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


def fetch_tile(z: int, x: int, y: int, session: requests.Session, cache_dir: Path) -> Image.Image:
    tile_path = cache_dir / str(z) / str(x) / f'{y}.png'
    tile_path.parent.mkdir(parents=True, exist_ok=True)
    if tile_path.exists():
        return Image.open(tile_path).convert('RGBA')
    url = f'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
    r = session.get(url, headers={'User-Agent': 'CodexTravelItineraryMap/1.0'}, timeout=30)
    r.raise_for_status()
    tile_path.write_bytes(r.content)
    return Image.open(tile_path).convert('RGBA')


def draw_multiline_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font, fill, outline=(255, 255, 255, 255), width: int = 1, spacing: int = 4):
    draw.multiline_text(xy, text, font=font, fill=outline, stroke_width=width + 1, stroke_fill=outline, spacing=spacing)
    draw.multiline_text(xy, text, font=font, fill=fill, spacing=spacing)


def wrap_text(text: str, width: int) -> str:
    return '\n'.join(textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False))


def label_box(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, font, border_color: str, fill=(255, 255, 255, 236), pad: int = 10):
    bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=4, stroke_width=1)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    box = [x, y, x + w + pad * 2, y + h + pad * 2]
    draw.rounded_rectangle(box, radius=12, fill=fill, outline=border_color, width=3)
    draw_multiline_text(draw, (x + pad, y + pad - 1), text, font=font, fill=TEXT_COLOR, width=1)
    return box


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


def draw_marker(draw: ImageDraw.ImageDraw, center: tuple[int, int], radius: int, fill: str, text: str | None = None, font=None):
    x, y = center
    draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=fill, outline=(255, 255, 255, 255), width=3)
    if text:
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=1)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text((x - tw / 2, y - th / 2 - 1), text, font=font, fill=(0, 0, 0, 255), stroke_width=2, stroke_fill=(0, 0, 0, 255))
        draw.text((x - tw / 2, y - th / 2 - 1), text, font=font, fill=(255, 255, 255, 255))


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


def render(config: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    home, days = normalize_input(config)
    if not days:
        raise ValueError('No days were supplied')

    zoom = int(config.get('zoom', 15))
    title = config.get('title', 'Travel itinerary map')
    subtitle = config.get('subtitle', '')
    footnote = config.get('footnote', 'Base map: OpenStreetMap contributors; points projected from real coordinates')
    note = config.get('note', 'Blue/red lines show different days; optional points are marked as 机动; lodging area can be represented by a nearby district point')
    output_basename = config.get('output_basename', 'itinerary_map')

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
    base = Image.new('RGBA', (base_w, base_h), (245, 246, 248, 255))

    coords = [(x, y) for x in range(tile_x0, tile_x1 + 1) for y in range(tile_y0, tile_y1 + 1)]
    cache_dir = output_dir / '.tile-cache'
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(fetch_tile, zoom, x, y, session, cache_dir): (x, y) for x, y in coords}
        for fut in as_completed(futures):
            x, y = futures[fut]
            tile = fut.result()
            base.alpha_composite(tile, ((x - tile_x0) * 256, (y - tile_y0) * 256))

    outer_left = int(config.get('outer_left', 280))
    outer_top = int(config.get('outer_top', 210))
    outer_right = int(config.get('outer_right', 260))
    outer_bottom = int(config.get('outer_bottom', 260))

    canvas = Image.new('RGBA', (base_w + outer_left + outer_right, base_h + outer_top + outer_bottom), (255, 255, 255, 255))
    canvas.alpha_composite(base, (outer_left, outer_top))
    draw = ImageDraw.Draw(canvas)

    title_font = pick_font(42)
    subtitle_font = pick_font(20)
    label_font = pick_font(18)
    small_font = pick_font(16)
    marker_font = pick_font(18)
    legend_font = pick_font(16)

    tile_origin = (tile_x0, tile_y0)

    day_colors: dict[int, str] = {}
    for i, day in enumerate(days):
        day_colors[day.day] = day.color or DEFAULT_COLORS[i % len(DEFAULT_COLORS)]

    # Draw routes first.
    for day in days:
        points = [home] if home and day.points else []
        points += day.points
        route = [point_center(p, projected, tile_origin, (outer_left, outer_top)) for p in day.points]
        color = day_colors[day.day]
        if len(route) >= 2:
            if day.line_style == 'dashed':
                for a, b in zip(route, route[1:]):
                    ax, ay = a
                    bx, by = b
                    dist = math.hypot(bx - ax, by - ay)
                    steps = max(1, int(dist // 30))
                    for i in range(steps):
                        if i % 2:
                            continue
                        t0 = i / steps
                        t1 = min(1.0, (i + 0.55) / steps)
                        x0 = ax + (bx - ax) * t0
                        y0 = ay + (by - ay) * t0
                        x1 = ax + (bx - ax) * t1
                        y1 = ay + (by - ay) * t1
                        draw.line([(x0, y0), (x1, y1)], fill=color, width=5)
            else:
                draw.line(route, fill=color, width=6, joint='curve')

    # Home marker.
    if home:
        hx, hy = point_center(home, projected, tile_origin, (outer_left, outer_top))
        draw_marker(draw, (hx, hy), 16, HOME_COLOR, text='S', font=marker_font)
        home_text = f'{home.label or home.name}\n{home.note or ""}'.strip()
        hx_off, hy_off = home.label_offset or (18, -84)
        bbox = draw.multiline_textbbox((0, 0), home_text, font=label_font, spacing=4, stroke_width=1)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        box = [hx + hx_off, hy + hy_off, hx + hx_off + w + 24, hy + hy_off + h + 24]
        if box[0] < 12:
            shift = 12 - box[0]
            box = [box[0] + shift, box[1], box[2] + shift, box[3]]
        if box[1] < 12:
            shift = 12 - box[1]
            box = [box[0], box[1] + shift, box[2], box[3] + shift]
        if box[2] > canvas.width - 12:
            shift = (canvas.width - 12) - box[2]
            box = [box[0] + shift, box[1], box[2] + shift, box[3]]
        if box[3] > canvas.height - 12:
            shift = (canvas.height - 12) - box[3]
            box = [box[0], box[1] + shift, box[2], box[3] + shift]
        draw.rounded_rectangle(box, radius=12, fill=(255, 255, 255, 236), outline=HOME_COLOR, width=3)
        draw_multiline_text(draw, (box[0] + 12, box[1] + 10), home_text, font=label_font, fill=TEXT_COLOR, width=1)

    # Day point markers.
    for day in days:
        for p in day.points:
            x, y = point_center(p, projected, tile_origin, (outer_left, outer_top))
            fill = OPTIONAL_COLOR if p.optional else day_colors[day.day]
            draw_marker(draw, (x, y), 15 if p.optional else 16, fill, text=str(p.seq), font=marker_font)

    # Labels.
    for day in days:
        for p in day.points:
            x, y = point_center(p, projected, tile_origin, (outer_left, outer_top))
            border = OPTIONAL_COLOR if p.optional else day_colors[day.day]
            display = p.label or p.name
            if p.optional:
                display = f'机动·{display}'
            text = f'{day.label} {p.seq} {display}\n{p.time_text}'.strip()
            if p.note:
                text = f'{text}\n{p.note}'
            dx, dy = p.label_offset or default_label_offset(p, (x, y), canvas.size)
            bbox = draw.multiline_textbbox((0, 0), text, font=label_font, spacing=4, stroke_width=1)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            box = [x + dx, y + dy, x + dx + w + 24, y + dy + h + 24]
            if box[0] < 12:
                shift = 12 - box[0]
                box = [box[0] + shift, box[1], box[2] + shift, box[3]]
            if box[1] < 12:
                shift = 12 - box[1]
                box = [box[0], box[1] + shift, box[2], box[3] + shift]
            if box[2] > canvas.width - 12:
                shift = (canvas.width - 12) - box[2]
                box = [box[0] + shift, box[1], box[2] + shift, box[3]]
            if box[3] > canvas.height - 12:
                shift = (canvas.height - 12) - box[3]
                box = [box[0], box[1] + shift, box[2], box[3] + shift]
            draw.rounded_rectangle(box, radius=12, fill=(255, 255, 255, 236), outline=border, width=3)
            draw_multiline_text(draw, (box[0] + 12, box[1] + 10), text, font=label_font, fill=TEXT_COLOR, width=1)

    # Title block.
    title_box = [40, 28, 650, 150]
    draw.rounded_rectangle(title_box, radius=18, fill=(255, 255, 255, 235), outline=(220, 224, 230, 255), width=2)
    draw_multiline_text(draw, (60, 42), title, font=title_font, fill=(17, 24, 39, 255), width=2)
    if subtitle:
        draw_multiline_text(draw, (62, 96), subtitle, font=subtitle_font, fill=(55, 65, 81, 255), width=1)

    # Legend block.
    legend_w = 780
    legend_h = 210
    lx1 = canvas.width - legend_w - 36
    ly1 = canvas.height - legend_h - 28
    legend_box = [lx1, ly1, lx1 + legend_w, ly1 + legend_h]
    draw.rounded_rectangle(legend_box, radius=18, fill=(255, 255, 255, 236), outline=(220, 224, 230, 255), width=2)
    x0 = lx1 + 18
    y0 = ly1 + 18
    draw.text((x0, y0), 'Legend', font=legend_font, fill=TEXT_COLOR)

    row_y = y0 + 28
    col_x = x0
    for day in days[:2]:
        color = day_colors[day.day]
        draw.line([(col_x, row_y + 10), (col_x + 44, row_y + 10)], fill=color, width=6)
        draw.text((col_x + 56, row_y), f'{day.label} route', font=legend_font, fill=TEXT_COLOR)
        col_x += 210
    draw.ellipse([x0, row_y + 34, x0 + 18, row_y + 52], fill=OPTIONAL_COLOR, outline=(255, 255, 255, 255), width=2)
    draw.text((x0 + 28, row_y + 32), '机动', font=legend_font, fill=TEXT_COLOR)
    draw.ellipse([x0 + 220, row_y + 34, x0 + 238, row_y + 52], fill=HOME_COLOR, outline=(255, 255, 255, 255), width=2)
    draw.text((x0 + 248, row_y + 32), 'lodging representative point', font=legend_font, fill=TEXT_COLOR)
    draw_multiline_text(draw, (x0, row_y + 68), wrap_text(note, 70), font=small_font, fill=(75, 85, 99, 255), width=1)
    draw_multiline_text(draw, (x0, row_y + 120), wrap_text(footnote, 70), font=small_font, fill=(75, 85, 99, 255), width=1)

    map_box = [outer_left, outer_top, outer_left + base_w, outer_top + base_h]
    draw.rectangle(map_box, outline=(255, 255, 255, 255), width=2)

    output_dir.mkdir(parents=True, exist_ok=True)
    standard_path = output_dir / f'{output_basename}.png'
    highres_path = output_dir / f'{output_basename}_highres.png'
    canvas.convert('RGB').save(highres_path, quality=95)
    standard = canvas.resize((canvas.width // 2, canvas.height // 2), Image.Resampling.LANCZOS)
    standard.convert('RGB').save(standard_path, quality=95)
    return standard_path, highres_path


def main() -> int:
    parser = argparse.ArgumentParser(description='Render a real-map travel itinerary PNG.')
    parser.add_argument('--input', required=True, help='Path to itinerary JSON file')
    parser.add_argument('--output-dir', default='outputs', help='Directory for PNG outputs')
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    with input_path.open('r', encoding='utf-8') as f:
        config = json.load(f)
    standard_path, highres_path = render(config, output_dir)
    print(standard_path)
    print(highres_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
