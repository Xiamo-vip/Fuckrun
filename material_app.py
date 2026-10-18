"""PySide6/Material Design 3 interface for GhostRunner."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWebEngineQuick import QtWebEngineQuick

from core import (
    APP_VERSION,
    DEFAULT_KEY_NOTICE,
    DEFAULT_TENCENT_KEY,
    STATE,
    AuthExpired,
    CampusClient,
    Settings,
    summarize,
    token_text,
    valid_record,
)
from map_view import map_html
from proxy_capture import Capture, ProxyLease
from running import RunSession, generate_plan, jitter_config, target_km
from updater import latest_release


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


class LocalMapServer:
    """Serve the current map document from a stable loopback origin."""

    def __init__(self):
        self._content = b"<!doctype html><meta charset=utf-8><body></body>"
        self._revision = 0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if urllib.parse.urlsplit(self.path).path != "/map":
                    self.send_error(404)
                    return
                content = owner._content
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, max-age=0")
                self.send_header("Content-Security-Policy", "default-src 'self' https: data: blob: 'unsafe-inline' 'unsafe-eval'")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def update(self, html: str) -> str:
        self._content = html.encode("utf-8")
        self._revision += 1
        return f"http://127.0.0.1:{self.server.server_port}/map?revision={self._revision}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Backend(QObject):
    stateChanged = Signal()
    authRequired = Signal()
    errorRaised = Signal(str, str)
    infoRaised = Signal(str, str)
    updateAvailable = Signal("QVariantMap")

    def __init__(self, demo=False, check_updates=True):
        super().__init__()
        self.demo = bool(demo)
        self.check_updates = bool(check_updates)
        self.settings = Settings(STATE / "demo-config.json") if demo else Settings()
        self.events_queue = queue.Queue()
        self.map_server = LocalMapServer()
        self.capture = None
        self.capture_deadline = None
        self.capture_phase = "idle"
        self.route = None
        self.checkpoints = []
        self.variant = 0
        self.plan_version = 0
        self.generation = 0
        self.busy = False
        self._planning = False
        self.run_state = "idle"
        self.run_session = None
        self.pending_session = None
        self.retry_resume_state = "starting"
        self.retry_path = None
        self._request_rows = {}
        self._successes = self._failures = self._uploads = 0
        self._state = {
            "status": "就绪",
            "identity": "自己的成绩，清楚呈现。",
            "metrics": {"distance": "—", "count": "—", "pace": "—", "valid": "—", "rank": "—"},
            "records": [],
            "rankings": [],
            "routeInfo": "获取打卡点后，将根据目标公里数生成路线、配速、步频与预计时长。",
            "routeReady": False,
            "planning": False,
            "runState": "idle",
            "progress": 0.0,
            "executionState": "等待开始",
            "executionMetrics": {"elapsed": "00:00:00", "remaining": "00:00:00", "uploads": "0", "requests": "0 / 0"},
            "requestLogs": [],
            "captureTitle": "请打开微信电脑版中的小程序",
            "captureStatus": "等待启动",
            "captureRemaining": "准备完成后开始计时",
            "captureActive": False,
            "mapUrl": "",
            "tasktoken": self.settings.data.get("tasktoken", ""),
            "tencentKey": self.settings.data.get("tencent_key", DEFAULT_TENCENT_KEY),
            "tencentJsKey": self.settings.data.get("tencent_js_key", DEFAULT_TENCENT_KEY),
            "runKm": str(self.settings.data.get("run_km", 3.0)),
            "jitter": dict(self.settings.data.get("route_jitter") or {}),
            "defaultKeyNotice": DEFAULT_KEY_NOTICE,
            "settingsPath": str(self.settings.path),
            "version": APP_VERSION,
        }
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._drain_events)
        self.timer.start(100)
        QTimer.singleShot(250, self._first_launch)

    def _get(self, key):
        return self._state[key]

    def _set(self, **values):
        changed = False
        for key, value in values.items():
            if self._state.get(key) != value:
                self._state[key] = value
                changed = True
        if changed:
            self.stateChanged.emit()

    status = Property(str, lambda s: s._get("status"), notify=stateChanged)
    identity = Property(str, lambda s: s._get("identity"), notify=stateChanged)
    metrics = Property("QVariantMap", lambda s: s._get("metrics"), notify=stateChanged)
    records = Property("QVariantList", lambda s: s._get("records"), notify=stateChanged)
    rankings = Property("QVariantList", lambda s: s._get("rankings"), notify=stateChanged)
    routeInfo = Property(str, lambda s: s._get("routeInfo"), notify=stateChanged)
    routeReady = Property(bool, lambda s: s._get("routeReady"), notify=stateChanged)
    planning = Property(bool, lambda s: s._get("planning"), notify=stateChanged)
    runState = Property(str, lambda s: s._get("runState"), notify=stateChanged)
    progress = Property(float, lambda s: s._get("progress"), notify=stateChanged)
    executionState = Property(str, lambda s: s._get("executionState"), notify=stateChanged)
    executionMetrics = Property("QVariantMap", lambda s: s._get("executionMetrics"), notify=stateChanged)
    requestLogs = Property("QVariantList", lambda s: s._get("requestLogs"), notify=stateChanged)
    captureTitle = Property(str, lambda s: s._get("captureTitle"), notify=stateChanged)
    captureStatus = Property(str, lambda s: s._get("captureStatus"), notify=stateChanged)
    captureRemaining = Property(str, lambda s: s._get("captureRemaining"), notify=stateChanged)
    captureActive = Property(bool, lambda s: s._get("captureActive"), notify=stateChanged)
    mapUrl = Property(str, lambda s: s._get("mapUrl"), notify=stateChanged)
    tasktoken = Property(str, lambda s: s._get("tasktoken"), notify=stateChanged)
    tencentKey = Property(str, lambda s: s._get("tencentKey"), notify=stateChanged)
    tencentJsKey = Property(str, lambda s: s._get("tencentJsKey"), notify=stateChanged)
    runKm = Property(str, lambda s: s._get("runKm"), notify=stateChanged)
    jitter = Property("QVariantMap", lambda s: s._get("jitter"), notify=stateChanged)
    defaultKeyNotice = Property(str, lambda s: s._get("defaultKeyNotice"), notify=stateChanged)
    settingsPath = Property(str, lambda s: s._get("settingsPath"), notify=stateChanged)
    version = Property(str, lambda s: s._get("version"), notify=stateChanged)

    def emit(self, name, value):
        self.events_queue.put((name, value))

    def _first_launch(self):
        if self.demo:
            self._show_demo()
        else:
            try:
                ProxyLease().restore()
            except Exception:
                self.errorRaised.emit("代理恢复", "上次代理备份恢复失败，请点击“恢复代理”重试。")
                return
            if self.settings.data.get("tasktoken"):
                self.refresh()
            else:
                self.authRequired.emit()
        if self.check_updates:
            threading.Thread(target=self._check_update_worker, daemon=True).start()

    def _check_update_worker(self):
        release = latest_release(APP_VERSION)
        if release:
            self.emit("update", release)

    @Slot()
    def checkForUpdates(self):
        self._set(status="正在通过 GitHub 检查更新…")

        def work():
            release = latest_release(APP_VERSION)
            self.emit("update", release or {})

        threading.Thread(target=work, daemon=True).start()

    @Slot(str)
    def openUrl(self, url):
        parsed = QUrl(url)
        if parsed.scheme() == "https" and parsed.host().lower() == "github.com":
            QDesktopServices.openUrl(parsed)

    @Slot(str, str, str)
    def saveSettings(self, tasktoken_value, webservice_key, javascript_key):
        if self.run_state in ("starting", "running", "retry_wait", "stopping") or self.pending_session:
            self.infoRaised.emit("会话进行中", "请先停止当前会话，再修改凭据。")
            return
        try:
            token = token_text(tasktoken_value) if tasktoken_value.strip() else ""
            ws = webservice_key.strip() or DEFAULT_TENCENT_KEY
            js = javascript_key.strip() or DEFAULT_TENCENT_KEY
            self.settings.data.update(tasktoken=token, tencent_key=ws, tencent_js_key=js)
            self.settings.save()
        except (OSError, ValueError) as exc:
            self.errorRaised.emit("保存失败", str(exc))
            return
        self.generation += 1
        self.plan_version += 1
        self.route = None
        self.checkpoints = []
        self._set(tasktoken=token, tencentKey=ws, tencentJsKey=js, routeReady=False, status="配置已保存")
        if token:
            self.refresh()

    @Slot()
    def refresh(self):
        if self.demo:
            self._show_demo()
            return
        if self.busy:
            return
        token = self.settings.data.get("tasktoken", "")
        if not token:
            self.authRequired.emit()
            return
        self.busy = True
        generation = self.generation
        self._set(status="正在加载个人信息、每日记录和排名…")

        def work():
            try:
                self.emit("dashboard", (generation, CampusClient(token).dashboard()))
            except AuthExpired:
                self.emit("expired", generation)
            except Exception as exc:
                self.emit("error", ("成绩加载失败", str(exc)))
            finally:
                self.emit("idle", None)

        threading.Thread(target=work, daemon=True).start()

    def _render_dashboard(self, data):
        summary = dict(data.get("summary") or summarize(data.get("records") or []))
        rank = (data.get("ranking") or {}).get("current_user_rank") or {}
        summary["rank"] = str(rank.get("rank") or "—")
        records = []
        for item in sorted(data.get("records") or [], key=lambda row: str(row.get("created_at", "")), reverse=True):
            valid = valid_record(item)
            records.append({
                "date": str(item.get("created_at", "—")),
                "distance": str(item.get("distance", "—")),
                "duration": str(item.get("duration", "—")),
                "pace": str(item.get("pace", "—")),
                "status": "有效" if valid is True else "无效" if valid is False else "待确认",
                "kind": "补跑" if item.get("is_makeup") in (True, 1, "1") else "普通",
            })
        rankings = []
        for item in (data.get("ranking") or {}).get("rank_list", []):
            user = item.get("user") or {}
            rankings.append({
                "rank": str(item.get("rank", "—")),
                "name": str(user.get("student_name") or user.get("wechat_nickname") or "—"),
                "distance": str(user.get("total_distance", "—")),
            })
        info = data.get("info") or {}
        identity = str(info.get("student_name") or info.get("wechat_nickname") or "个人成绩")
        self._set(metrics=summary, records=records, rankings=rankings, identity=identity,
                  status=f"成绩已更新 · 共 {len(records)} 条记录")

    @Slot(float, bool, float, int, str, bool)
    def planRoute(self, km_value, jitter_enabled, amplitude, smooth_points, seed, reload_checkpoints=False):
        if self._planning or self.run_state in ("starting", "running", "retry_wait", "stopping"):
            return
        try:
            km = target_km(km_value)
            jitter = jitter_config({"enabled": jitter_enabled, "amplitude_m": amplitude,
                                    "smooth_points": smooth_points, "seed": seed})
        except ValueError as exc:
            self.errorRaised.emit("规划配置", str(exc))
            return
        key = self.settings.data.get("tencent_key", "")
        if not self.demo and not key:
            self.infoRaised.emit("腾讯路线规划", "请先在设置中填写腾讯 WebService Key。")
            return
        self._planning = True
        self.route = None
        self.plan_version += 1
        self.variant += 1
        version, generation, variant = self.plan_version, self.generation, self.variant
        cached = list(self.checkpoints)
        token = self.settings.data.get("tasktoken", "")
        self._set(planning=True, routeReady=False, status="正在获取打卡点并规划腾讯步行路线…",
                  routeInfo="正在规划，请稍候…", runKm=str(km))

        def work():
            try:
                if self.demo:
                    cps = cached or [
                        {"id": 1, "latitude": 25.050, "longitude": 118.160, "radius": 10},
                        {"id": 2, "latitude": 25.055, "longitude": 118.165, "radius": 10},
                        {"id": 3, "latitude": 25.052, "longitude": 118.171, "radius": 10},
                    ]
                    route = generate_plan(cps, "DEMO", km, variant, leg=lambda a, b: {"points": [a, b]}, jitter=jitter)
                else:
                    cps = CampusClient(token).checkpoints() if reload_checkpoints or not cached else cached
                    route = generate_plan(cps, key, km, variant, jitter=jitter)
                self.emit("planned", (version, generation, route))
            except AuthExpired:
                self.emit("expired", generation)
            except Exception as exc:
                self.emit("plan_error", (version, str(exc)))
            finally:
                self.emit("plan_idle", None)

        threading.Thread(target=work, daemon=True).start()

    @Slot()
    def reloadMap(self):
        if self.route:
            self._publish_map()

    def _publish_map(self):
        key = "" if self.demo else (self.settings.data.get("tencent_js_key") or self.settings.data.get("tencent_key") or "")
        url = self.map_server.update(map_html(key, self.route.get("points", []), self.route.get("checkpoints", [])))
        self._set(mapUrl=url)

    @staticmethod
    def _duration_text(seconds):
        seconds = max(0, int(seconds))
        return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"

    @staticmethod
    def _jitter_summary(plan):
        cfg = plan.get("jitter", {})
        if not cfg.get("enabled") or not cfg.get("amplitude_m"):
            return "抖动关闭"
        return f"抖动 ≤{cfg['amplitude_m']:g}米 / 平滑{cfg['smooth_points']}点 / 种子{cfg['seed']}"

    @Slot()
    def executeRun(self):
        if not self.route or self._planning or self.run_state in ("starting", "running", "retry_wait", "stopping"):
            return
        plan = self.route
        self.run_state = "starting"
        self._request_rows = {}
        self._successes = self._failures = self._uploads = 0
        self._set(runState="starting", progress=0.0, requestLogs=[], executionState="正在准备会话，请稍候…",
                  executionMetrics={"elapsed": "00:00:00", "remaining": self._duration_text(plan["duration_seconds"]),
                                    "uploads": "0", "requests": "0 / 0"}, status="正在创建跑步会话…")
        options = {
            "created_session": self.pending_session,
            "replan": lambda cps: generate_plan(
                cps, self.settings.data.get("tencent_key", ""), plan.get("requested_km", plan["km"]),
                plan.get("variant", 0) + 1, leg=(lambda a, b: {"points": [a, b]}) if self.demo else None,
                jitter=plan.get("jitter"),
            ),
        }
        if self.demo:
            started = time.monotonic()
            initial = time.time_ns() // 1_000_000
            scale = max(1, plan["duration_seconds"] / 5)

            def transport(path, payload=None):
                if path == "/login/wechat/info":
                    return {"data": {"student_number": "DEMO"}}
                if path == "/create_running_record":
                    return {"data": {"record_id": "DEMO", "run_session_id": "DEMO", "session_salt": "DEMO",
                                     "checkpoints": plan["checkpoints"]}}
                return {"code": 200}

            options.update(transport=transport, clock=lambda: initial + int((time.monotonic() - started) * 1000 * scale))
        self.run_session = RunSession(self.settings.data.get("tasktoken", ""), plan, self.emit, **options)
        self.run_session.start()

    @Slot()
    def retryRun(self):
        if self.run_state == "retry_wait" and self.run_session:
            self.run_session.retry_now()

    @Slot()
    def stopRun(self):
        if self.pending_session and self.run_state == "ready":
            record = self.pending_session.get("record_id")
            self.pending_session = None
            self.run_state = "stopped"
            self._set(runState="stopped", status=f"已停止本地待确认会话；服务端记录保留，record_id={record}")
        elif self.run_session:
            self.run_state = "stopping"
            self.run_session.stop()
            self._set(runState="stopping", status="正在停止，已发送的请求不会自动撤销…")

    @Slot()
    def startCapture(self):
        if self.demo:
            self._set(status="离线预览不修改系统代理；正式启动后可抓取")
            return
        if self.capture and self.capture.thread and self.capture.thread.is_alive():
            return
        self.capture_phase = "preparing"
        self.capture_deadline = None
        self._set(captureActive=True, captureTitle="正在准备安全抓取环境",
                  captureStatus="正在检查证书、启动代理；请按页面提示操作。",
                  captureRemaining="尚未修改系统代理", status="正在启动抓取…")
        self.capture = Capture(self.emit)
        self.capture.start()

    @Slot()
    def stopCapture(self):
        if self.capture and self.capture.thread and self.capture.thread.is_alive():
            self.capture_phase = "stopping"
            self.capture.stop()
            self._set(captureStatus="正在停止并恢复原有系统代理…", captureRemaining="请稍候")

    @Slot()
    def restoreProxy(self):
        try:
            if self.capture and self.capture.thread and self.capture.thread.is_alive():
                self.stopCapture()
            else:
                ProxyLease().restore()
                self._set(status="原有代理配置已恢复")
        except Exception as exc:
            self.errorRaised.emit("恢复失败", f"{exc}\n备份日志仍保留在 {STATE}")

    def _append_request_log(self, data):
        request_id = data["request_id"]
        phase = data["phase"]
        states = {"sending": "发送中", "success": f"成功 {data.get('code', 200)}",
                  "error": "失败 " + (str(data.get("code")) if data.get("code") is not None else data.get("error_type", "请求错误"))}
        row = {"time": data["time"], "method": data["method"], "path": data["path"],
               "chunk": str(data.get("chunk_seq") if data.get("chunk_seq") is not None else "—"),
               "points": str(data.get("point_count") if data.get("point_count") is not None else "—"),
               "status": states[phase], "duration": str(data.get("duration_ms") if data.get("duration_ms") is not None else "—")}
        self._request_rows[request_id] = row
        if phase == "success":
            self._successes += 1
            if data["path"] == "/upload_running_chunk":
                self._uploads += 1
        elif phase == "error":
            self._failures += 1
        metrics = dict(self._state["executionMetrics"])
        metrics.update(uploads=str(self._uploads), requests=f"{self._successes} / {self._failures}")
        self._set(requestLogs=list(self._request_rows.values()), executionMetrics=metrics)

    def _drain_events(self):
        if self.capture_phase == "waiting" and self.capture_deadline:
            remaining = max(0, int(self.capture_deadline - time.monotonic() + .999))
            self._set(captureRemaining=f"剩余 {remaining} 秒 · 请打开小程序并进入成绩页" if remaining else "等待抓取结束并恢复代理…")
        try:
            while True:
                event, value = self.events_queue.get_nowait()
                if event == "update":
                    if value:
                        self.updateAvailable.emit(value)
                        self._set(status=f"发现新版本 {value['version']}")
                    else:
                        self._set(status="当前已是最新版本")
                elif event in ("status", "capture_end"):
                    values = {"status": value}
                    if event == "status" and self._state["captureActive"]:
                        values["captureStatus"] = value
                    if event == "capture_end":
                        values.update(captureActive=False, captureRemaining="抓取已结束 · 原有系统代理已恢复")
                    self._set(**values)
                elif event == "certificate_ready":
                    self._set(captureTitle="证书已验证，准备连接微信", captureStatus=value,
                              captureRemaining="系统代理尚未启用" if self.capture_phase == "preparing" else self._state["captureRemaining"])
                elif event == "capture_waiting":
                    self.capture_phase = "waiting"
                    self.capture_deadline = time.monotonic() + value["timeout"]
                    self._set(captureTitle="抓取已开始，请立即打开小程序！",
                              captureStatus="请打开 Windows 微信电脑版校园跑步小程序，进入成绩页或刷新页面。",
                              captureRemaining=f"剩余 {value['timeout']} 秒 · 等待小程序请求")
                elif event == "token":
                    self.settings.data["tasktoken"] = value
                    self.settings.save()
                    self.generation += 1
                    self.capture_phase = "success"
                    self._set(tasktoken=value, captureTitle="抓取成功，tasktoken 已保存",
                              captureStatus="正在读取成绩，下次启动将直接读取配置。", status="tasktoken 已保存，正在读取成绩…")
                    self.refresh()
                elif event == "dashboard" and value[0] == self.generation:
                    self._render_dashboard(value[1])
                elif event == "idle":
                    self.busy = False
                elif event == "expired" and value == self.generation:
                    self.authRequired.emit()
                elif event == "error":
                    title, message = value if isinstance(value, tuple) else ("GhostRunner", str(value))
                    self._set(status=message, captureTitle="抓取遇到问题" if self._state["captureActive"] else self._state["captureTitle"],
                              captureStatus=message if self._state["captureActive"] else self._state["captureStatus"])
                    self.errorRaised.emit(title, message)
                elif event == "planned":
                    version, generation, route = value
                    if version == self.plan_version and generation == self.generation:
                        self.route, self.checkpoints = route, route["checkpoints"]
                        self.run_state = "ready"
                        cfg = route.get("jitter", {})
                        info = (f"{len(self.checkpoints)} 个打卡点 · {route['km']:.3f} 公里 · 建议配速 {route['pace']} /km · "
                                f"步频 {route['cadence']} · 预计 {route['duration']:.1f} 分钟 · {self._jitter_summary(route)}")
                        if not self.demo:
                            self.settings.data["run_km"] = route.get("requested_km", route["km"])
                            self.settings.data["route_jitter"] = cfg
                            self.settings.save()
                        self._set(routeInfo=info, routeReady=True, runState="ready", jitter=cfg,
                                  status="路线已生成，可刷新选择方案，满意后确认运行。")
                        self._publish_map()
                elif event == "plan_error" and value[0] == self.plan_version:
                    self._set(routeInfo=value[1], status="路线规划失败：" + value[1])
                    self.errorRaised.emit("路线规划", value[1])
                elif event == "plan_idle":
                    self._planning = False
                    self._set(planning=False)
                elif event == "request_log":
                    self._append_request_log(value)
                elif event == "run_started":
                    self.pending_session = None
                    self.run_state = "running"
                    self._set(runState="running", executionState=f"执行中 · 会话 {value['record_id']} · 按计划上传分片",
                              status=f"会话已创建，正在执行；record_id={value['record_id']}")
                elif event == "run_retry_wait":
                    if self.run_state != "stopping":
                        if self.run_state != "retry_wait":
                            self.retry_resume_state = self.run_state
                        self.run_state, self.retry_path = "retry_wait", value["path"]
                        detail = f"{value['remaining']} 秒后自动重试" if value["automatic"] else "等待手动重试或停止"
                        code = str(value["code"]) if value["code"] is not None else value["error_type"]
                        text = f"请求失败（{code}）· {value['path']} · {detail}"
                        self._set(runState="retry_wait", executionState=text, status=text)
                elif event == "run_retrying":
                    self.run_state = self.retry_resume_state
                    self._set(runState=self.run_state, executionState=f"正在重试 {value['path']} · 第 {value['attempt']} 次")
                elif event == "run_plan_updated":
                    self.route, self.checkpoints = value["plan"], value["plan"]["checkpoints"]
                    self._publish_map()
                    self._set(executionState="本次会话路线已同步，自动继续执行。")
                elif event == "run_replanned":
                    self.pending_session = value["session"]
                    self.route = value.get("plan")
                    self.checkpoints = self.pending_session["checkpoints"]
                    self.run_state = "ready"
                    if self.route:
                        self._publish_map()
                        self._set(routeReady=True, runState="ready", routeInfo=f"已同步实际打卡点 · {self.route['km']:.3f} 公里",
                                  status=f"请再次确认；将复用 record_id={value['record_id']}")
                    else:
                        self._set(routeReady=False, runState="ready", routeInfo="实际打卡点已同步，请调整公里数并刷新路线。")
                elif event == "run_progress":
                    percent = min(.99, value["elapsed"] / max(1, value["duration"]))
                    metrics = dict(self._state["executionMetrics"])
                    metrics.update(elapsed=self._duration_text(value["elapsed"]),
                                   remaining=self._duration_text(max(0, value["duration"] - value["elapsed"])))
                    self._set(progress=percent, executionMetrics=metrics,
                              executionState="执行中 · 等待下一次上传" if value["elapsed"] < value["duration"] else "运动计划时间已到 · 等待结束确认")
                elif event == "run_upload":
                    self._set(status=f"已发送 {value['sent']}/{value['total']} 个请求")
                elif event in ("run_finished", "run_stopped", "run_error"):
                    self.pending_session = None
                    self.run_state = "finished" if event == "run_finished" else "stopped"
                    if event == "run_finished":
                        metrics = dict(self._state["executionMetrics"])
                        metrics["remaining"] = "00:00:00"
                        self._set(runState="finished", progress=1.0, executionMetrics=metrics,
                                  executionState="任务完成 · 结束请求成功。" if not self.demo else "离线演示完成 · 全部模拟请求成功。",
                                  status="结束接口返回成功，正在刷新成绩。" if not self.demo else "离线演示运行完成")
                        if not self.demo:
                            self.refresh()
                    elif event == "run_stopped":
                        self._set(runState="stopped", executionState="已停止 · 已发送的请求保留，未自动发送结束请求。",
                                  status="运行已停止；已提交记录保留。")
                    else:
                        message = value["message"]
                        self._set(runState="stopped", executionState="执行失败 · " + message, status="运行失败：" + message)
                        self.errorRaised.emit("运行失败", message)
        except queue.Empty:
            pass

    def _show_demo(self):
        records = [{"id": i, "created_at": f"2026-10-{i + 1:02d} 17:30", "distance": 3.2,
                    "duration": 1152, "pace": "6′00″", "is_completed": True, "has_cheating": i == 2} for i in range(8)]
        self._render_dashboard({"info": {"student_name": "演示用户 · 离线预览"}, "records": records,
                                "summary": summarize(records), "ranking": {"current_user_rank": {"rank": 12},
                                "rank_list": [{"rank": i + 1, "user": {"student_name": f"演示同学 {i + 1}",
                                "total_distance": 80 - i * 3}} for i in range(15)]}})
        self._set(status="离线演示数据 · 未读取真实账号 · 未修改系统代理")

    def close(self):
        if self.run_session:
            self.run_session.stop()
        if self.capture and self.capture.thread and self.capture.thread.is_alive():
            self.capture.stop()
        if not self.demo:
            try:
                ProxyLease().restore()
            except Exception:
                pass
        self.map_server.close()


def run(demo=False, smoke_test=False, check_updates=True) -> int:
    QtWebEngineQuick.initialize()
    app = QGuiApplication(sys.argv[:1])
    app.setApplicationName("GhostRunner")
    app.setApplicationVersion(APP_VERSION)
    root = resource_root()
    material_root = root / "third_party" / "material-components-pyside"
    if str(material_root) not in sys.path:
        sys.path.insert(0, str(material_root))
    from stylemanager import StyleManager

    engine = QQmlApplicationEngine()
    engine.warnings.connect(lambda warnings: [print(str(item), file=sys.stderr, flush=True) for item in warnings])
    engine.addImportPath(str(material_root / "src"))
    backend = Backend(demo=demo or smoke_test, check_updates=check_updates and not smoke_test)
    style = StyleManager()
    style.setSeedColor("#2864DC")
    engine.rootContext().setContextProperty("Backend", backend)
    engine.rootContext().setContextProperty("StyleManager", style)
    engine.load(QUrl.fromLocalFile(str(root / "ui" / "Main.qml")))
    if not engine.rootObjects():
        print("Material QML root failed to load: " + str(root / "ui" / "Main.qml"), file=sys.stderr, flush=True)
        backend.close()
        return 1
    app.aboutToQuit.connect(backend.close)
    screenshot = os.environ.get("GHOSTRUNNER_SCREENSHOT")
    if screenshot:
        screenshot_page = int(os.environ.get("GHOSTRUNNER_SCREENSHOT_PAGE", "0"))
        engine.rootObjects()[0].setProperty("pageIndex", screenshot_page)
        if screenshot_page == 3:
            backend.planRoute(3.0, True, 3.0, 12, "42", True)
        elif screenshot_page == 4:
            backend.planRoute(3.0, True, 3.0, 12, "42", True)

            def start_demo_run():
                if backend.routeReady and not backend.planning:
                    backend.executeRun()
                else:
                    QTimer.singleShot(120, start_demo_run)

            QTimer.singleShot(120, start_demo_run)
        def capture():
            from PySide6.QtQuick import QQuickWindow
            window = engine.rootObjects()[0]
            image = QQuickWindow.grabWindow(window)
            Path(screenshot).parent.mkdir(parents=True, exist_ok=True)
            if not image.save(screenshot):
                app.exit(2)
                return
            app.quit()
        QTimer.singleShot(3200 if screenshot_page == 4 else (2600 if screenshot_page == 3 else 1800), capture)
    elif smoke_test:
        QTimer.singleShot(1800, app.quit)
    return app.exec()
