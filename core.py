"""Read-only campus results, local settings and Tencent walking directions."""
import json
import math
import os
from pathlib import Path
import urllib.request
import urllib.parse
import urllib.error

HOST = 'campusrun.mzwu.edu.cn'
BASE = 'https://' + HOST + '/api'
CONFIG = Path.home() / 'config.json'
APP_VERSION = '1.0.2'
DEFAULT_TENCENT_KEY = 'JXIBZ-7IQ6I-AJPGJ-UZFYM-NSBRO-YQFPT'
DEFAULT_KEY_NOTICE = '内置腾讯 Key 未来可能无法使用，建议自行申请并在“设置”中替换。'
STATE = Path(os.environ.get('GHOSTRUNNER_STATE_DIR') or (Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'GhostRunner'))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def token_text(value):
    value = value.strip()
    if value.lower() == 'bearer':
        raise ValueError('请输入有效的 tasktoken')
    if value.lower().startswith('bearer '):
        value = value[7:].strip()
    if not value or any(c.isspace() for c in value):
        raise ValueError('请输入有效的 tasktoken')
    return value


class Settings:
    def __init__(self, path=CONFIG):
        self.path = Path(path)
        self.data = {'tasktoken': '', 'tencent_key': DEFAULT_TENCENT_KEY, 'tencent_js_key': DEFAULT_TENCENT_KEY}
        if self.path.exists():
            value = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(value, dict):
                raise ValueError('config.json 必须是 JSON 对象')
            self.data.update(value)
        for field in ('tencent_key','tencent_js_key'):
            if not self.data.get(field):
                self.data[field] = DEFAULT_TENCENT_KEY

    def save(self):
        atomic_json(self.path, self.data)


class AuthExpired(Exception):
    pass


def get_json(url, token=None):
    headers = {'Accept': 'application/json', 'User-Agent': 'GhostRunnerDesktop/1.0.2'}
    if token:
        headers['Authorization'] = 'Bearer ' + token_text(token)
    # Explicitly bypass system proxy for application API calls.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(urllib.request.Request(url, headers=headers), timeout=20) as r:
            result = json.loads(r.read(16 * 1024 * 1024).decode('utf-8'))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise AuthExpired('登录已过期，请重新抓取或手动填写') from None
        raise RuntimeError('接口 HTTP ' + str(exc.code)) from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError('网络请求失败，请检查网络后重试') from None
    if not isinstance(result, dict):
        raise ValueError('接口返回格式异常')
    if result.get('code') in (401, 403):
        raise AuthExpired('登录已过期，请重新抓取或手动填写')
    return result


class CampusClient:
    def __init__(self, token, fetch=get_json):
        self.token, self.fetch = token_text(token), fetch

    def get(self, path, **query):
        url = BASE + path
        if query:
            url += '?' + urllib.parse.urlencode(query)
        result = self.fetch(url, self.token)
        if result.get('code', 200) != 200:
            raise RuntimeError('成绩接口返回失败（code=' + str(result.get('code')) + '）')
        return result

    def checkpoints(self):
        result = self.get('/get_checkpoints')
        points = result.get('data')
        if isinstance(points, dict):
            points = points.get('checkpoints')
        if not isinstance(points, list) or not points:
            raise ValueError('平台未返回打卡点，请先确认当前账号已绑定并开放跑步')
        normalized = []
        for index, item in enumerate(points):
            lat, lng = coordinate(f"{item.get('latitude')},{item.get('longitude')}")
            normalized.append(dict(item, id=item.get('id', index), latitude=lat, longitude=lng,
                                   radius=number(item.get('radius')) or 10))
        return normalized

    def dashboard(self):
        info = self.get('/login/wechat/info').get('data') or {}
        records, seen = [], set()
        for kind in ('normal', 'makeup'):
            for page in range(1, 501):
                response = self.get('/get_student_running_record', page=page,
                                    page_size=50, record_type=kind)
                batch = response.get('records', (response.get('data') or {}).get('records', []))
                if not isinstance(batch, list):
                    raise ValueError('每日记录格式异常')
                new = 0
                for item in batch:
                    record = item.get('running_record', item)
                    identity = str(record.get('id', json.dumps(record, sort_keys=True)))
                    if identity not in seen:
                        seen.add(identity)
                        records.append(record)
                        new += 1
                if len(batch) < 50 or not new:
                    break
            else:
                raise RuntimeError('记录页数超过 500，请缩小查询范围')
        ranking = self.get('/get_student_running_record_detail', page=1,
                           page_size=50, rank_type='class')
        return {'info': info, 'records': records, 'ranking': ranking,
                'summary': summarize(records)}


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else 0
    except (ValueError, TypeError):
        return 0


def valid_record(record):
    if record.get('has_cheating') in (True, 1, '1', 'true'):
        return False
    completed = record.get('is_completed')
    if completed in (True, 1, '1', 'true'):
        return True
    if completed in (False, 0, '0', 'false'):
        return False
    return None


def summarize(records):
    km = sum(number(r.get('distance')) for r in records)
    sec = sum(number(r.get('duration')) for r in records)
    pace = round(sec / km) if km else 0
    return {'distance': f'{km:.2f} km', 'count': str(len(records)),
            'pace': f'{pace // 60}′{pace % 60:02d}″ /km' if pace else '—',
            'valid': str(sum(valid_record(r) is True for r in records))}


def coordinate(text):
    try:
        lat, lng = map(float, text.split(','))
    except (ValueError, TypeError):
        raise ValueError('坐标格式：纬度,经度') from None
    if not math.isfinite(lat) or not math.isfinite(lng) or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValueError('坐标超出范围')
    return lat, lng


def plan_route(key, start, end, fetch=get_json):
    if not key.strip():
        raise ValueError('请先配置腾讯 WebService Key')
    a, b = coordinate(start), coordinate(end)
    query = urllib.parse.urlencode({'key': key.strip(), 'from': f'{a[0]},{a[1]}', 'to': f'{b[0]},{b[1]}'})
    result = fetch('https://apis.map.qq.com/ws/direction/v1/walking/?' + query)
    if result.get('status') != 0:
        raise RuntimeError('腾讯路线规划失败，status=' + str(result.get('status')))
    routes = result.get('result', {}).get('routes', [])
    if not routes:
        raise ValueError('未找到步行路线')
    route = routes[0]
    coords = list(map(float, route.get('polyline', [])))
    if len(coords) < 4 or len(coords) % 2:
        raise ValueError('路线坐标格式异常')
    for i in range(2, len(coords)):
        coords[i] = coords[i-2] + coords[i] / 1000000
    points = [coordinate(f'{coords[i]},{coords[i+1]}') for i in range(0, len(coords), 2)]
    return dict(route, points=points)
