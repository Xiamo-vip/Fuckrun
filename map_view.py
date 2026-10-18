"""Generate the responsive HTML document shown by the native QtWebEngine view."""
import json


class ResizeGuard:
    """Do not disturb mouse capture by resizing an unchanged WebView HWND."""
    def __init__(self):
        self.previous = None

    def changed(self, width, height):
        size = (max(1, width), max(1, height))
        if size == self.previous:
            return False
        self.previous = size
        return True


def map_html(key, points=None, checkpoints=None):
    from pathlib import Path
    data = json.dumps({'key': key, 'points': points or [], 'checkpoints': checkpoints or []},
                      ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')
    runtime = Path(__file__).with_name('map_runtime.js').read_text(encoding='utf-8')
    return ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="referrer" content="strict-origin-when-cross-origin">'
            '<title>GhostRunner 路线地图</title><style>html,body{width:100%;height:100%;margin:0;overflow:hidden;background:#eef2f7;font-family:Segoe UI,Microsoft YaHei,sans-serif}'
            '#map{position:absolute;inset:0;width:100%;height:100%;min-width:1px;min-height:1px}'
            '#status{position:absolute;top:12px;left:12px;max-width:85%;background:white;padding:10px 14px;border-radius:10px;z-index:5;box-shadow:0 2px 12px #0002;pointer-events:none;user-select:none;font-size:14px;line-height:20px}'
            '</style></head><body><div id="map"></div><div id="status">正在加载腾讯地图 SDK…</div>'
            '<script>window.GHOSTRUNNER_PLAN=' + data + ';\n' + runtime + '</script></body></html>')
