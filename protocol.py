"""Running protocol primitives extracted from the existing workspace client. No embedded user token or map Key."""
from __future__ import annotations
import argparse
import copy
import getpass
import hashlib
import hmac
import json
import math
import os
import random
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
BASE_URL = 'https://campusrun.mzwu.edu.cn/api'
HMAC_KEY = 'mzy-campus-run-upload-v1-202605'
SIGN_SUFFIX = 'qu_mo_ni_qu_bu_yao_zai_lai_ni_xian_le'
USER_AGENT = 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.10(0x18000a2a) NetType/WIFI Language/zh_CN'
REFERER = 'https://servicewechat.com/wx952e3e81d1b047d4/0/page-frame.html'

def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)

def canonical(value):
    if isinstance(value, dict):
        return '{' + ','.join((compact(k) + ':' + canonical(value[k]) for k in sorted(value))) + '}'
    if isinstance(value, list):
        return '[' + ','.join(map(canonical, value)) + ']'
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return compact(value)

def sha256(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()

def sign(fields):
    source = '|'.join(map(str, fields))
    return hmac.new(HMAC_KEY.encode(), source.encode(), hashlib.sha256).hexdigest()

def rounded(value, places):
    return float(Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))

def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

def now_ms():
    return time.time_ns() // 1000000

def request_json(url, token=None, payload=None, signed=False, timeout=30):
    body_text = compact(payload) if payload is not None else None
    headers = {'Accept': 'application/json', 'User-Agent': USER_AGENT, 'Referer': REFERER}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if body_text is not None:
        headers['Content-Type'] = 'application/json'
    if signed:
        ts = str(now_ms())
        nonce = ''.join((secrets.choice('abcdefghijklmnopqrstuvwxyz0123456789') for _ in range(8)))
        source = f'{body_text}|{ts}|{nonce}|{token}'
        headers.update({'X-Timestamp': ts, 'X-Nonce': nonce, 'X-Signature': hashlib.md5(source.encode()).hexdigest()})
    req = urllib.request.Request(url, data=body_text.encode() if body_text is not None else None, headers=headers)
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'HTTP {exc.code}: {urllib.parse.urlsplit(url).path}') from None

def require_success(response):
    if not isinstance(response, dict) or response.get('code') != 200:
        raise RuntimeError('平台返回失败: ' + str(response.get('msg', '未知响应') if isinstance(response, dict) else '非对象响应'))
    return response

def distance(a, b):
    lon_m = 111320 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot((a[1] - b[1]) * lon_m, (a[0] - b[0]) * 111320)

def valid_point(p):
    return all((math.isfinite(x) for x in p)) and -90 <= p[0] <= 90 and (-180 <= p[1] <= 180)

def dense_points(points):
    result = [points[0]]
    for a, b in zip(points, points[1:]):
        samples = max(1, math.ceil(distance(a, b) / 4.5))
        result.extend((tuple((x + (y - x) * i / samples for x, y in zip(a, b))) for i in range(1, samples + 1)))
    return result

def point_string(p):
    return f"{p['latitude']:.6f},{p['longitude']:.6f},{p['timestamp']}"

def prepare_tasks(ctx, track, km, pace=None, cadence=None):
    if len(track) < 2:
        raise ValueError('轨迹至少包含两个点')
    pace = random.randint(300, 450) if pace is None else pace
    cadence = random.randint(168, 192) if cadence is None else cadence
    duration = int(km * pace)
    duration_ms = duration * 1000
    n = len(track)
    start = ctx['start_ms']
    count = max(1, math.ceil(n / max(1, math.ceil(duration_ms / 30000))))
    record, session, student, salt = (ctx[k] for k in ('record_id', 'run_session_id', 'student_number', 'session_salt'))
    tasks, previous, seq = ([], '', 0)
    for i in range(0, n, count):
        end = min(i + count, n)
        seq += 1
        t0 = start + duration_ms * i // (n - 1)
        t1 = start + duration_ms * (end - 1) // (n - 1)
        if t0 == t1:
            t1 = t0 + 1000
        points = [{'latitude': rounded(track[j][0], 6), 'longitude': rounded(track[j][1], 6), 'timestamp': str(start + duration_ms * j // (n - 1)), 'accuracy': 10.0, 'color': '#00FF00DD'} for j in range(i, end)]
        first, last = (point_string(points[0]), point_string(points[-1]))
        chunk_hash = sha256('|'.join(map(str, [record, session, seq, t0, t1, canonical(points), previous])))
        payload = {'record_id': record, 'run_session_id': session, 'chunk_seq': seq, 'chunk_start_time': iso(t0), 'chunk_end_time': iso(t1), 'prev_chunk_hash': previous, 'sign_version': 'running-chunk-v1', 'points': points, 'point_count': len(points), 'first_point': first, 'last_point': last, 'chunk_hash': chunk_hash}
        payload['sign'] = sign([record, student, session, seq, t0, t1, first, last, previous, chunk_hash, len(points), salt, SIGN_SUFFIX])
        tasks.append((t1 + 3000, '/upload_running_chunk', payload))
        previous = chunk_hash
    end_ms = start + duration_ms
    checkpoint_data = []
    for cp in ctx['checkpoints']:
        item = copy.deepcopy(cp)
        target = (float(cp['latitude']), float(cp['longitude']))
        index = min(range(n), key=lambda j: distance(track[j], target))
        hit_distance = distance(track[index], target)
        reached = hit_distance <= max(1, float(cp.get('radius', 10)))
        item.update({'reached': reached, 'reached_type': 'normal' if reached else 'missed', 'hit_accuracy': 10.0, 'hit_distance_m': rounded(hit_distance, 2), 'fuzzy_confirm_count': 0, 'reached_at': start + duration_ms * index // (n - 1) if reached else end_ms})
        checkpoint_data.append(item)
    seconds_per_km = int(duration / km)
    finish = {'record_id': record, 'run_session_id': session, 'client_end_time': iso(end_ms), 'client_distance': km, 'client_duration': duration, 'client_pace': f'''{seconds_per_km // 60}'{seconds_per_km % 60}"''', 'client_cadence': cadence, 'client_location_signal_summary': {}, 'client_risk_flags': [], 'client_checkpoint_data': checkpoint_data, 'last_chunk_seq': seq, 'last_chunk_hash': previous}
    finish['sign'] = sign([record, student, session, end_ms, f'{km:.3f}', duration, seq, previous, salt, SIGN_SUFFIX])
    tasks.append((end_ms + 10000, '/finish_running_record', finish))
    return tasks
