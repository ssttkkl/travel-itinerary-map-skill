# 旅行行程地图技能

English version: [README.md](README.md)。

这是一个 Codex 技能，用于生成基于真实地图底图的独立旅行行程图。

渲染器会对真实地点进行地理编码，嵌入 OpenStreetMap 底图，按访问顺序标注停靠点，补充时间，绘制每天的路线覆盖层，并输出一个可直接在浏览器打开的独立 HTML 文件。

## 功能

- 真实地图底图与真实地理坐标。
- 带时间的行程停靠点编号。
- 信息框内使用圈号序号，例如 `①`、`②`、`③`。
- 按天使用不同颜色或线型的路线。
- 机动点使用相同当天颜色的半透明样式标记为 `机动`。
- 图例支持按天、机动点、住宿点的复选框切换。
- 过滤机动点或住宿点后，路线会重新连接剩余可见点。
- 内置缩放控件，可放大、缩小并返回适配视图。
- 默认浏览器视图会自动适配整张图，不需要滚动。

## 使用方法

先按 `references/input-format.md` 的格式准备行程 JSON，然后执行：

```bash
python3 scripts/render_itinerary_map_html.py --input itinerary.json --output-dir outputs
```

脚本会把独立 `.html` 文件输出到指定目录。

## 示例

最小输入示例：

```json
{
  "title": "Rome / Vatican itinerary map",
  "subtitle": "2026-10-01 / 2026-10-02",
  "output_basename": "rome_vatican_itinerary_map_2026",
  "zoom": 15,
  "home": {
    "label": "Piazza della Repubblica",
    "query": "Piazza della Repubblica, Rome, Italy",
    "note": "lodging area representative point"
  },
  "days": [
    {
      "day": 1,
      "label": "10/1",
      "points": [
        {
          "seq": 1,
          "name": "Colosseum",
          "query": "Colosseum, Rome, Italy",
          "time": "10:15-11:45"
        }
      ]
    }
  ]
}
```

按天导出截图：

```bash
node scripts/screenshot_itinerary_map_html.mjs \
  --url "file:///path/to/rome_vatican_itinerary_map_2026.html?show=day-1&hide=legend,controls&title=10/1%20罗马&subtitle=仅展示当天行程" \
  --output outputs/rome_day1.png
```

## 截图

罗马 / 梵蒂冈第 1 天：

![罗马 / 梵蒂冈第 1 天](screenshots/rome_vatican_day1.png)

佛罗伦萨第 3 天：

![佛罗伦萨第 3 天](screenshots/florence_day3.png)

维也纳第 5 天：

![维也纳第 5 天](screenshots/vienna_day5.png)

## 依赖

```bash
python3 -m pip install -r requirements.txt
```

渲染器使用 Nominatim 进行地理编码，使用 OpenStreetMap 作为底图。生成地图时请遵守这两个服务的使用政策。
