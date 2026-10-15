"""Route preview and cancellable real-time protocol execution."""
import copy
import math
import random
import threading
import time
import uuid
import re
import urllib.error
from datetime import datetime, timedelta, timezone
from core import CampusClient, coordinate, plan_route
from protocol import distance, dense_points, prepare_tasks, request_json, require_success, BASE_URL


def route_length(points):
    return sum(distance(a, b) for a, b in zip(points, points[1:]))


def target_km(value):
    try:
        km = float(value)
    except (ValueError, TypeError):
        raise ValueError('公里数应为 0.1–50 的数字') from None
    if not math.isfinite(km) or not 0.1 <= km <= 50:
        raise ValueError('公里数应为 0.1–50 的数字')
    return round(km, 3)


def extend_to_distance(loop, meters):
    perimeter = route_length(loop)
    if perimeter < 1:
        raise ValueError('腾讯返回的路线过短，请刷新路线')
    if perimeter > meters + 1:
        raise ValueError(f'经过全部打卡点的路线至少 {perimeter/1000:.3f} 公里，请增加公里数或刷新路线')
    result = [loop[0]]
    total = 0.0
    while total < meters - .001:
        for a, b in zip(loop, loop[1:]):
            length = distance(a, b)
            if length < .0001:
                continue
            remaining = meters - total
            if length >= remaining:
                ratio = remaining / length
                result.append(tuple(x + (y-x)*ratio for x, y in zip(a,b)))
                return result
            result.append(b)
            total += length
            if len(result) > 100000:
                raise ValueError('路线点数过多，请更换规划方案')
    return result


def jitter_config(config=None):
    """Validate persisted/UI configuration; disabled by default."""
    config = config or {}
    try:
        amplitude = float(config.get('amplitude_m', 3))
        smooth = float(config.get('smooth_points', 12))
        seed = str(config.get('seed', '')).strip()
        if not math.isfinite(amplitude) or not 0 <= amplitude <= 20:
            raise ValueError()
        if not math.isfinite(smooth) or not smooth.is_integer() or not 2 <= smooth <= 100:
            raise ValueError()
        if seed and (not seed.isdecimal() or not 0 <= int(seed) <= 4294967295):
            raise ValueError()
    except (TypeError, ValueError, OverflowError):
        raise ValueError('抖动幅度须为 0–20 米，平滑点数须为 2–100 的整数，种子留空或填写 0–4294967295 的整数') from None
    return {'enabled': bool(config.get('enabled', False)), 'amplitude_m': amplitude,
            'smooth_points': int(smooth), 'seed': str(int(seed)) if seed else ''}


def jitter_points(points, checkpoints, config):
    """Bounded smooth synthetic offsets. Preserve endpoints and CP passages."""
    cfg = jitter_config(config)
    result = list(points)
    if not cfg['enabled'] or cfg['amplitude_m'] == 0 or len(points) < 3:
        return result, cfg
    if not cfg['seed']:
        cfg['seed'] = str(random.SystemRandom().randrange(2**32))
    rng = random.Random(int(cfg['seed']))
    span = cfg['smooth_points']
    anchors = {0, len(points)-1}
    for cp in checkpoints:
        center = (cp['latitude'], cp['longitude'])
        anchors.add(min(range(len(points)), key=lambda i: distance(center, points[i])))
    def noise():
        theta = rng.uniform(0, 2*math.pi)
        radius = cfg['amplitude_m'] * math.sqrt(rng.random())
        return radius*math.cos(theta), radius*math.sin(theta)
    knots = [noise() for _ in range((len(points)-1)//span+2)]
    for i, (lat, lon) in enumerate(points):
        if i in anchors:
            continue
        t = (i % span)/span
        t = t*t*(3-2*t)  # continuous velocity at the noise knots
        a, b = knots[i//span:i//span+2]
        fade = min(1., min(abs(i-j) for j in anchors)/span)
        east, north = [(x+(y-x)*t)*fade for x,y in zip(a,b)]
        radius = math.hypot(east,north)/6371000
        bearing = math.atan2(east,north)
        phi, lam = math.radians(lat), math.radians(lon)
        phi2 = math.asin(max(-1.,min(1.,math.sin(phi)*math.cos(radius)+math.cos(phi)*math.sin(radius)*math.cos(bearing))))
        lam2 = lam + math.atan2(math.sin(bearing)*math.sin(radius)*math.cos(phi), math.cos(radius)-math.sin(phi)*math.sin(phi2))
        shifted = (math.degrees(phi2), (math.degrees(lam2)+180)%360-180)
        # Use the same distance metric as planning/execution for the hard cap.
        displacement = distance((lat,lon),shifted)
        if displacement > cfg['amplitude_m']:
            scale = cfg['amplitude_m']/displacement * .999999
            shifted = (lat+(shifted[0]-lat)*scale,lon+(shifted[1]-lon)*scale)
        result[i] = shifted
    return result, cfg


def generate_plan(checkpoints, key, km, variant=0, leg=None, jitter=None):
    km = target_km(km)
    if not checkpoints:
        raise ValueError('请先获取打卡点')
    rng = random.Random(variant)
    coordinates = [coordinate(f"{c['latitude']},{c['longitude']}") for c in checkpoints]
    coordinates = list(dict.fromkeys(coordinates))
    start = coordinates[variant % len(coordinates)]
    others = [p for p in coordinates if p != start]
    rng.shuffle(others)
    # Different intermediate waypoints produce actual Tencent route alternatives,
    # rather than changing the point order without requesting a new route.
    bearing = (variant * 137.5 + 45) * math.pi / 180
    offset = 65 + variant % 4 * 18
    midpoint = (start[0] + math.sin(bearing)*offset/111320,
                start[1] + math.cos(bearing)*offset/(111320*max(.1,math.cos(math.radians(start[0])))))
    visits = [start, midpoint] + others + [start]
    leg = leg or (lambda a,b: plan_route(key, f'{a[0]},{a[1]}', f'{b[0]},{b[1]}'))
    loop = [start]
    for a,b in zip(visits, visits[1:]):
        result = leg(a,b)
        path = result.get('points')
        if not path or len(path)<2:
            raise ValueError('腾讯未返回有效的步行路线')
        if distance(a,path[0]) > 100 or distance(b,path[-1]) > 100:
            raise ValueError('规划路线未靠近打卡点，请刷新路线')
        loop.extend(path)
        loop.append(b)
    base_points = dense_points(extend_to_distance(loop,km*1000))
    points, jitter = jitter_points(base_points, checkpoints, jitter)
    requested_km = km
    if jitter['enabled'] and jitter['amplitude_m'] > 0:
        km = route_length(points)/1000
    # Advisory values are visible before the user starts execution.
    pace = rng.randint(330,390) + round(min(km,20)*2)
    cadence = rng.randint(172,184)
    return {'points':points,'checkpoints':copy.deepcopy(checkpoints),'distance':round(route_length(points)),
            'km':km,'pace_seconds':pace,'pace':f'{pace//60}′{pace%60:02d}″',
            'cadence':cadence,'duration_seconds':int(km*pace),'duration':round(km*pace/60,1),
            'variant':variant, 'requested_km':requested_km,
            'base_points':base_points, 'jitter':jitter}


class RunCancelled(Exception):
    pass


class RequestFailure(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__('平台请求返回失败 code='+str(code))


class RunSession:
    def __init__(self, token, plan, emit, transport=None, clock=None, wait=None,
                 created_session=None, replan=None, retry_delay=10, retry_max_delay=60):
        self.token, self.plan, self.emit = token, copy.deepcopy(plan), emit
        self.transport = transport or self._request
        self.clock = clock or (lambda: time.time_ns()//1000000)
        self.cancel = threading.Event()
        self.wait = wait or self.cancel.wait
        self.thread = None
        self.created_session = copy.deepcopy(created_session)
        self.replan = replan
        self.record_id = (created_session or {}).get('record_id')
        if not math.isfinite(retry_delay) or not 0 < retry_delay <= retry_max_delay <= 3600:
            raise ValueError('重试间隔无效')
        self.retry_delay, self.retry_max_delay = retry_delay, retry_max_delay
        self.retry_requested = threading.Event()

    def _request(self, path, payload=None):
        result = request_json(BASE_URL+path,self.token,payload,
                              signed=path in ('/upload_running_chunk','/finish_running_record'))
        if not isinstance(result,dict) or result.get('code') != 200:
            raise RequestFailure(result.get('code') if isinstance(result,dict) else None)
        return result

    @staticmethod
    def failure_code(exc):
        match = re.search(r'\bHTTP\s+(\d{3})\b',str(exc))
        return int(match.group(1)) if match else getattr(exc,'code',None)

    def retry_now(self):
        self.retry_requested.set()

    def _retry_pause(self, path, exc, attempt):
        code = self.failure_code(exc)
        transient = code in (408,425,429,500,502,503,504) or (code is None and isinstance(exc,(TimeoutError,ConnectionError,urllib.error.URLError,OSError)))
        # Creation has no verified idempotency key. An ambiguous failure must
        # wait for an explicit retry rather than create duplicate records.
        automatic = transient and path != '/create_running_record'
        delay = min(self.retry_max_delay,self.retry_delay*2**min(attempt-1,20))
        self.retry_requested.clear()
        deadline = self.clock()+round(delay*1000) if automatic else None
        previous = object()
        while not self.cancel.is_set():
            remaining = max(0,math.ceil((deadline-self.clock())/1000)) if automatic else None
            if remaining != previous:
                self.emit('run_retry_wait',{'path':path,'attempt':attempt+1,'remaining':remaining,
                          'automatic':automatic,'code':code,'error_type':type(exc).__name__,
                          'record_id':self.record_id})
                previous = remaining
            if self.retry_requested.is_set() or (automatic and self.clock()>=deadline):
                self.retry_requested.clear()
                self.emit('run_retrying',{'path':path,'attempt':attempt+1})
                return
            self.wait(.2)
        raise RunCancelled()

    def _send(self,path,payload=None):
        original = copy.deepcopy(payload)
        attempt = 1
        while not self.cancel.is_set():
            try:
                return self._send_once(path,copy.deepcopy(original))
            except Exception as exc:
                self._retry_pause(path,exc,attempt)
                attempt += 1
        raise RunCancelled()

    def _send_once(self,path,payload=None):
        """Log only whitelisted metadata, never headers, salt, signatures or points."""
        meta={'request_id':uuid.uuid4().hex,'time':datetime.fromtimestamp(self.clock()/1000,
                 timezone(timedelta(hours=8))).strftime('%H:%M:%S'),
              'method':'POST' if payload is not None else 'GET','path':path,
              'chunk_seq':(payload or {}).get('chunk_seq'),
              'point_count':(payload or {}).get('point_count')}
        self.emit('request_log',dict(meta,phase='sending',duration_ms=None,code=None))
        start=time.perf_counter()
        code=None
        try:
            result=self.transport(path,payload)
            code=result.get('code',200) if isinstance(result,dict) else None
            if code!=200:
                raise RequestFailure(code)
            self.emit('request_log',dict(meta,phase='success',duration_ms=round((time.perf_counter()-start)*1000),code=code))
            return result
        except Exception as exc:
            # Exception text can contain echoed credentials or URLs. Keep the
            # request log to the exception class; the UI receives no raw body.
            failure_code = self.failure_code(exc)
            if failure_code is not None:code=failure_code
            self.emit('request_log',dict(meta,phase='error',duration_ms=round((time.perf_counter()-start)*1000),
                                       code=code,error_type=type(exc).__name__))
            raise

    def start(self):
        if self.thread and self.thread.is_alive():
            raise RuntimeError('已有运行任务')
        self.thread = threading.Thread(target=self.run,daemon=True)
        self.thread.start()

    def stop(self):
        self.cancel.set()

    def run(self):
        try:
            if self.cancel.is_set():
                self.emit('run_stopped',{'record_id':None})
                return
            created = self.created_session
            if created:
                student = created.get('student_number')
            else:
                info = self._send('/login/wechat/info').get('data') or {}
                student = info.get('student_number')
            if not student:
                raise ValueError('当前账号尚未绑定学生身份')
            if self.cancel.is_set():
                self.emit('run_stopped',{'record_id':None})
                return
            if not created:
                created = self._send('/create_running_record',{'record_type':'normal'}).get('data') or {}
            created = dict(created,student_number=str(student))
            self.record_id = created.get('record_id')
            for field in ('record_id','run_session_id','session_salt','checkpoints'):
                if not created.get(field):
                    raise ValueError('创建响应缺少 '+field)
            # Preview checkpoints are provisional. The create response is the
            # authoritative selection; synchronize it within this first run.
            def covers(plan):
                if not plan.get('points'):
                    return False
                for cp in created['checkpoints']:
                    point = coordinate(f"{cp['latitude']},{cp['longitude']}")
                    radius = float(cp.get('radius',10))
                    if not math.isfinite(radius):
                        raise ValueError('会话打卡点半径无效')
                    if min(distance(point,p) for p in plan['points']) > max(1,radius):
                        return False
                return True
            if not covers(self.plan):
                if not self.replan:
                    raise ValueError('本次会话打卡点发生变化，请重新获取打卡点并规划路线；本次未提交轨迹')
                self.emit('status','正在同步本次会话打卡点并重新规划，完成后自动继续；record_id='+str(self.record_id))
                try:
                    plan = self.replan(copy.deepcopy(created['checkpoints']))
                    if not covers(plan):
                        raise ValueError('重新规划的路线未覆盖本次会话打卡点，请调整公里数后刷新路线')
                    plan = copy.deepcopy(plan)
                    plan['checkpoints'] = copy.deepcopy(created['checkpoints'])
                    message = ''
                except Exception as exc:
                    plan = None
                    message = str(exc).replace(self.token,'[已隐藏]') if self.token else str(exc)
                if self.cancel.is_set():
                    self.emit('run_stopped',{'record_id':self.record_id})
                    return
                if plan is None:
                    # A genuine planning failure remains editable and retains
                    # the original record instead of creating another on retry.
                    self.emit('run_replanned',{'plan':None,'session':created,
                              'record_id':self.record_id,'message':message})
                    return
                self.plan = plan
                self.created_session = copy.deepcopy(created)
                self.emit('run_plan_updated',{'plan':copy.deepcopy(plan),'record_id':self.record_id})
            ctx = dict(created,student_number=str(student),start_ms=self.clock())
            tasks = prepare_tasks(ctx,self.plan['points'],self.plan['km'],
                                  pace=self.plan['pace_seconds'],cadence=self.plan['cadence'])
            self.emit('run_started',{'record_id':self.record_id,'total':len(tasks)})
            for index,(due,path,payload) in enumerate(tasks,1):
                while self.clock()<due:
                    if self.cancel.is_set():
                        self.emit('run_stopped',{'record_id':self.record_id})
                        return
                    elapsed = max(0,(self.clock()-ctx['start_ms'])/1000)
                    self.emit('run_progress',{'elapsed':elapsed,'duration':self.plan['duration_seconds'],
                                              'sent':index-1,'total':len(tasks)})
                    self.wait(min(1,(due-self.clock())/1000))
                if self.cancel.is_set():
                    self.emit('run_stopped',{'record_id':self.record_id})
                    return
                self._send(path,payload)
                self.emit('run_upload',{'sent':index,'total':len(tasks)})
            self.emit('run_finished',{'record_id':self.record_id})
        except RunCancelled:
            self.emit('run_stopped',{'record_id':self.record_id})
        except Exception as exc:
            message=str(exc).replace(self.token,'[已隐藏]') if self.token else str(exc)
            self.emit('run_error',{'message':message,'record_id':self.record_id})
