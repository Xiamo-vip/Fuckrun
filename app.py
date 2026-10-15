"""GhostRunner Windows/Tkinter desktop. Run --demo for an offline preview."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

# Local build dependencies, not needed by the packaged executable.
vendor = Path(__file__).parent / '.vendor'
if vendor.exists():
    sys.path.insert(0, str(vendor))

from core import APP_VERSION, DEFAULT_TENCENT_KEY, DEFAULT_KEY_NOTICE, Settings, CampusClient, AuthExpired, STATE, token_text, valid_record, summarize, plan_route
from proxy_capture import Capture, ProxyLease, command, guardian
from map_view import map_html, run_embedded
from running import generate_plan, RunSession, target_km, jitter_config


class Application:
    def __init__(self, demo=False):
        import tkinter as tk
        from tkinter import ttk, messagebox
        self.tk, self.ttk, self.dialog = tk, ttk, messagebox
        self.root = tk.Tk()
        self.root.title('GhostRunner '+APP_VERSION+' · 免安装版')
        self.root.geometry(f'1120x{min(900,max(650,self.root.winfo_screenheight()-90))}')
        self.root.minsize(940, 650)
        self.root.configure(bg='#f3f6fb')
        self.queue = queue.Queue()
        self.demo = demo
        self.capture = None
        self.capture_phase = 'idle'
        self.capture_deadline = None
        self.capture_ui_active = False
        self.map_process = None
        self.map_embedded = False
        self.map_deadline = 0
        self.busy = False
        self.pending_refresh = False
        self.closing = False
        self.records = []
        self.route = None
        self.checkpoints = []
        self.variant = 0
        self.planning = False
        self.plan_version = 0
        self.run_session = None
        self.pending_session = None
        self.request_rows = {}
        self.request_successes = 0
        self.request_failures = 0
        self.upload_successes = 0
        self.run_state = 'idle'
        self.retry_resume_state = 'starting'
        self.retry_path = None
        self.generation = 0
        self.settings = Settings(STATE / 'demo-config.json') if demo else Settings()
        self.style()
        self.build()
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(100, self.events)
        self.root.after(300, self.first_launch)

    def style(self):
        style = self.ttk.Style()
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 10))
        style.configure('TFrame', background='#f3f6fb')
        style.configure('TLabel', background='#f3f6fb', foreground='#23334b')
        style.configure('Title.TLabel', font=('Microsoft YaHei UI', 24, 'bold'))
        style.configure('Sub.TLabel', foreground='#718096')
        style.configure('Card.TFrame', background='white')
        style.configure('Card.TLabel', background='white', foreground='#6d7a8d')
        style.configure('Value.TLabel', background='white', foreground='#2673de', font=('Microsoft YaHei UI', 21, 'bold'))
        style.configure('TButton', padding=(14, 8), background='white')
        style.configure('Accent.TButton', background='#2673de', foreground='white')
        style.map('Accent.TButton', background=[('active', '#185cbc')])
        style.configure('Treeview', rowheight=31, borderwidth=0, background='white', fieldbackground='white')
        style.configure('Treeview.Heading', padding=8, background='#e8eef7')
        style.configure('TNotebook.Tab', padding=(22, 10))

    def build(self):
        ttk, tk = self.ttk, self.tk
        outer = ttk.Frame(self.root, padding=24)
        outer.pack(fill='both', expand=True)
        head = ttk.Frame(outer)
        head.pack(fill='x')
        ttk.Label(head, text='GhostRunner '+APP_VERSION, style='Title.TLabel').pack(side='left')
        ttk.Button(head, text='设置', command=self.configure).pack(side='right', padx=(8,0))
        self.refresh_button = ttk.Button(head, text='刷新成绩', command=self.refresh, style='Accent.TButton')
        self.refresh_button.pack(side='right')
        self.start_button = ttk.Button(head, text='开始跑步', command=self.enter_running, style='Accent.TButton')
        self.start_button.pack(side='right', padx=8)
        self.identity = tk.StringVar(value='自己的成绩，清楚呈现。')
        ttk.Label(outer, textvariable=self.identity, style='Sub.TLabel').pack(anchor='w', pady=(5,18))
        ttk.Label(outer,text=DEFAULT_KEY_NOTICE,style='Sub.TLabel',wraplength=1000).pack(anchor='w',pady=(0,12))
        cards = self.cards = ttk.Frame(outer)
        cards.pack(fill='x', pady=(0,20))
        self.metrics = {}
        for i, (field, label) in enumerate([('distance','总里程'),('count','跑步次数'),('pace','平均配速'),('valid','有效成绩'),('rank','班级排名')]):
            cards.columnconfigure(i, weight=1)
            card = ttk.Frame(cards, style='Card.TFrame', padding=16)
            card.grid(row=0, column=i, sticky='nsew', padx=(0,10 if i<4 else 0))
            value = tk.StringVar(value='—')
            self.metrics[field] = value
            ttk.Label(card, text=label, style='Card.TLabel').pack(anchor='w')
            ttk.Label(card, textvariable=value, style='Value.TLabel').pack(anchor='w', pady=(10,0))
        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill='both', expand=True)
        records = ttk.Frame(self.tabs, padding=12)
        ranks = ttk.Frame(self.tabs, padding=12)
        map_tab = self.map_tab = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(records, text='每日记录')
        self.tabs.add(ranks, text='班级排名')
        self.record_tree = self.table(records, ('日期','里程 / km','时长 / 秒','配速','状态','类型'))
        ttk.Label(records, text='有效成绩依据平台 is_completed / has_cheating；缺失状态显示“待确认”。总里程含已加载的普通及补跑记录。', style='Sub.TLabel').pack(anchor='w', pady=(10,0))
        self.rank_tree = self.table(ranks, ('排名','姓名','累计里程 / km'))
        ttk.Label(ranks, text='显示班级前 50 名，个人名次以平台返回值为准。', style='Sub.TLabel').pack(anchor='w', pady=(10,0))
        controls = ttk.Frame(map_tab)
        controls.pack(fill='x', pady=(0,10))
        self.km_var = tk.StringVar(value=str(self.settings.data.get('run_km',3.0)))
        ttk.Label(controls, text='目标公里数').pack(side='left',padx=(0,8))
        self.km_entry = ttk.Spinbox(controls, textvariable=self.km_var, from_=0.1,to=50,increment=.1,width=7)
        self.km_entry.pack(side='left',padx=(0,12))
        self.replan_button = ttk.Button(controls, text='刷新路线', command=self.plan)
        self.replan_button.pack(side='left',padx=(0,8))
        self.checkpoint_button = ttk.Button(controls, text='重新获取打卡点', command=lambda:self.plan(reload_checkpoints=True))
        self.checkpoint_button.pack(side='left')
        self.execute_button = ttk.Button(controls, text='确认运行', command=self.execute_run, state='disabled',style='Accent.TButton')
        self.execute_button.pack(side='right')
        self.cancel_run_button = ttk.Button(controls,text='停止运行',command=self.stop_run,state='disabled')
        self.cancel_run_button.pack(side='right',padx=8)
        ttk.Button(controls, text='重载地图', command=self.reload_map).pack(side='right')
        jitter_bar = ttk.Frame(map_tab)
        jitter_bar.pack(fill='x',pady=(0,10))
        saved = self.settings.data.get('route_jitter',{})
        if not isinstance(saved,dict): saved = {}
        self.jitter_enabled = tk.BooleanVar(value=bool(saved.get('enabled',False)))
        self.jitter_amplitude = tk.StringVar(value=str(saved.get('amplitude_m',3)))
        self.jitter_smooth = tk.StringVar(value=str(saved.get('smooth_points',12)))
        self.jitter_seed = tk.StringVar(value=str(saved.get('seed','')))
        toggle = ttk.Checkbutton(jitter_bar,text='模拟路径抖动',variable=self.jitter_enabled)
        toggle.pack(side='left',padx=(0,12))
        self.jitter_controls = [toggle]
        for label,var,limits in [('幅度 / 米',self.jitter_amplitude,(0,20)),
                                 ('平滑点数',self.jitter_smooth,(2,100)),
                                 ('随机种子',self.jitter_seed,None)]:
            ttk.Label(jitter_bar,text=label).pack(side='left',padx=(0,5))
            widget = ttk.Spinbox(jitter_bar,textvariable=var,from_=limits[0],to=limits[1],width=6) if limits else ttk.Entry(jitter_bar,textvariable=var,width=11)
            widget.pack(side='left',padx=(0,12))
            self.jitter_controls.append(widget)
        ttk.Label(jitter_bar,text='种子留空每次随机；修改后刷新路线',style='Sub.TLabel').pack(side='left')
        self.run_info = tk.StringVar(value='获取打卡点后，将根据目标公里数生成路线、配速、步频与预计时长。')
        ttk.Label(map_tab,textvariable=self.run_info,style='Sub.TLabel').pack(anchor='w',pady=(0,10))
        self.progress_value = tk.DoubleVar(value=0)
        self.progress = ttk.Progressbar(map_tab,maximum=100,variable=self.progress_value)
        self.progress.pack(fill='x',pady=(0,10))
        self.map_frame = tk.Frame(map_tab, bg='#e6edf7', highlightthickness=0)
        self.map_frame.pack(fill='both', expand=True)
        self.map_hint = tk.Label(self.map_frame, text='正在获取打卡点并规划腾讯步行路线…', bg='#e6edf7', fg='#60728a', font=('Microsoft YaHei UI',14))
        self.map_hint.place(relx=.5, rely=.5, anchor='center')
        self.status = tk.StringVar(value='就绪')
        footer = ttk.Frame(outer)
        footer.pack(side='bottom',fill='x',pady=(14,0),before=self.tabs)
        ttk.Label(footer, textvariable=self.status, style='Sub.TLabel').pack(side='left')
        ttk.Button(footer, text='恢复代理', command=self.restore_proxy).pack(side='right')
        self.stop_button = ttk.Button(footer, text='停止抓取', command=self.stop_capture, state='disabled')
        self.stop_button.pack(side='right', padx=8)
        self.km_var.trace_add('write',self.distance_changed)
        for var in (self.jitter_enabled,self.jitter_amplitude,self.jitter_smooth,self.jitter_seed):
            var.trace_add('write',self.distance_changed)
        self.build_execution_page()
        self.build_capture_page()
        self.tabs.bind('<<NotebookTabChanged>>',self.on_tab_changed)

    def on_tab_changed(self,event=None):
        # Give workflow pages room for instructions, map and request logs.
        if self.tabs.select() in (str(self.map_tab),str(self.execution_tab),str(self.capture_tab)):
            self.cards.pack_forget()
        elif not self.cards.winfo_manager():
            self.cards.pack(fill='x',pady=(0,20),before=self.tabs)

    def build_capture_page(self):
        ttk = self.ttk
        self.capture_tab = ttk.Frame(self.tabs,padding=30)
        ttk.Label(self.capture_tab,text='抓取 tasktoken',font=('Microsoft YaHei UI',22,'bold')).pack(anchor='w')
        self.capture_title = self.tk.StringVar(value='请打开微信电脑版中的小程序')
        ttk.Label(self.capture_tab,textvariable=self.capture_title,font=('Microsoft YaHei UI',18,'bold'),
                  foreground='#2673de').pack(anchor='w',pady=(24,20))
        for instruction in ('1. 打开 Windows 微信电脑版。',
                            '2. 打开对应的校园跑步小程序。',
                            '3. 进入成绩 / 跑步记录页面；如果已打开，请刷新或重新进入。',
                            '4. 抓取到 token 后会自动保存，并恢复原有系统代理。'):
            ttk.Label(self.capture_tab,text=instruction,wraplength=780).pack(anchor='w',pady=8)
        self.capture_status = self.tk.StringVar(value='等待启动')
        self.capture_remaining = self.tk.StringVar(value='准备完成后开始计时')
        ttk.Label(self.capture_tab,textvariable=self.capture_status,wraplength=780).pack(anchor='w',pady=(24,12))
        self.capture_progress = ttk.Progressbar(self.capture_tab,mode='indeterminate')
        self.capture_progress.pack(fill='x',pady=10)
        ttk.Label(self.capture_tab,textvariable=self.capture_remaining,style='Sub.TLabel').pack(anchor='w')
        actions = ttk.Frame(self.capture_tab)
        actions.pack(fill='x',pady=24)
        self.capture_cancel = ttk.Button(actions,text='取消抓取',command=self.stop_capture,state='disabled')
        self.capture_cancel.pack(side='left')
        self.capture_retry = ttk.Button(actions,text='重新抓取',command=self.start_capture,state='disabled')
        self.capture_retry.pack(side='left',padx=12)
        self.capture_results = ttk.Button(actions,text='查看成绩',command=lambda:self.tabs.select(self.tabs.tabs()[0]),state='disabled')
        self.capture_results.pack(side='left')
        self.root.after(500,self.capture_tick)

    def show_capture_page(self):
        if str(self.capture_tab) not in self.tabs.tabs():
            self.tabs.add(self.capture_tab,text='抓取引导')
        self.tabs.select(self.capture_tab)

    def capture_tick(self):
        if self.closing:
            return
        if self.capture_ui_active and self.capture_phase=='waiting' and self.capture_deadline is not None:
            remaining = max(0,int(self.capture_deadline-time.monotonic()+.999))
            self.capture_remaining.set(f'剩余 {remaining} 秒 · 请打开小程序并进入成绩页' if remaining else '等待抓取结束并恢复代理…')
        self.root.after(500,self.capture_tick)

    def build_execution_page(self):
        tk,ttk = self.tk,self.ttk
        self.execution_tab = ttk.Frame(self.tabs,padding=22)
        ttk.Label(self.execution_tab,text='任务执行',font=('Microsoft YaHei UI',22,'bold')).pack(anchor='w')
        self.execution_state = tk.StringVar(value='等待开始')
        ttk.Label(self.execution_tab,textvariable=self.execution_state,style='Sub.TLabel').pack(anchor='w',pady=(6,16))
        summary = ttk.Frame(self.execution_tab)
        summary.pack(fill='x')
        self.execution_percent = tk.StringVar(value='0%')
        ttk.Label(summary,textvariable=self.execution_percent,font=('Segoe UI',32,'bold'),foreground='#2673de').pack(side='left')
        ttk.Button(summary,text='返回路线',command=lambda:self.tabs.select(self.map_tab)).pack(side='right')
        self.execution_stop = ttk.Button(summary,text='停止任务',command=self.stop_run,state='disabled')
        self.execution_stop.pack(side='right',padx=10)
        self.execution_retry = ttk.Button(summary,text='立即重试',command=self.retry_run,state='disabled')
        self.execution_retry.pack(side='right')
        style=ttk.Style();style.configure('Execution.Horizontal.TProgressbar',thickness=24)
        self.execution_progress = ttk.Progressbar(self.execution_tab,maximum=100,
            variable=self.progress_value,style='Execution.Horizontal.TProgressbar')
        self.execution_progress.pack(fill='x',pady=(8,18))
        stats = ttk.Frame(self.execution_tab)
        stats.pack(fill='x',pady=(0,20))
        self.execution_metrics={}
        for i,(key,label) in enumerate([('elapsed','已执行时间'),('remaining','预计剩余'),('uploads','已上传分片'),('requests','请求成功 / 失败')]):
            stats.columnconfigure(i,weight=1)
            card=ttk.Frame(stats,style='Card.TFrame',padding=14)
            card.grid(row=0,column=i,sticky='nsew',padx=(0,10 if i<3 else 0))
            ttk.Label(card,text=label,style='Card.TLabel').pack(anchor='w')
            var=tk.StringVar(value='—');self.execution_metrics[key]=var
            ttk.Label(card,textvariable=var,style='Value.TLabel').pack(anchor='w',pady=(8,0))
        ttk.Label(self.execution_tab,text='上传请求日志',font=('Microsoft YaHei UI',13,'bold')).pack(anchor='w',pady=(0,8))
        self.request_tree=self.table(self.execution_tab,('时间','方法','接口','分片','点数','状态','耗时 / ms'))
        for col,width in [('时间',85),('方法',60),('接口',300),('分片',55),('点数',60),('状态',160),('耗时 / ms',90)]:
            self.request_tree.column(col,width=width,minwidth=45)
        self.request_tree.tag_configure('success',foreground='#16804a')
        self.request_tree.tag_configure('error',foreground='#c53030')
        ttk.Label(self.execution_tab,text='日志仅显示接口、序号、点数、结果与耗时，不记录 token、签名、salt 或轨迹正文。',
                  style='Sub.TLabel').pack(anchor='w',pady=(10,0))

    @staticmethod
    def duration_text(seconds):
        seconds=max(0,int(seconds))
        return f'{seconds//3600:02d}:{seconds//60%60:02d}:{seconds%60:02d}'

    def show_execution_page(self,reset=False):
        if str(self.execution_tab) not in self.tabs.tabs():
            self.tabs.add(self.execution_tab,text='任务执行')
        if reset:
            self.request_tree.delete(*self.request_tree.get_children())
            self.request_rows.clear()
            self.request_successes=self.request_failures=self.upload_successes=0
            self.execution_metrics['requests'].set('0 / 0')
            self.execution_metrics['uploads'].set('0')
            self.execution_metrics['elapsed'].set('00:00:00')
            self.execution_metrics['remaining'].set(self.duration_text((self.route or {}).get('duration_seconds',0)))
            self.execution_percent.set('0%')
            self.progress_value.set(0)
        self.execution_state.set('正在准备会话，请稍候…')
        self.tabs.select(self.execution_tab)

    def append_request_log(self,data):
        key=data['request_id'];phase=data['phase']
        states={'sending':'发送中','success':'成功 '+str(data.get('code',200)),
                'error':'失败 '+(str(data['code'])+' ' if data.get('code') is not None else '')+data.get('error_type','请求错误')}
        values=(data['time'],data['method'],data['path'],
                data.get('chunk_seq') if data.get('chunk_seq') is not None else '—',
                data.get('point_count') if data.get('point_count') is not None else '—',states[phase],
                data.get('duration_ms') if data.get('duration_ms') is not None else '—')
        row=self.request_rows.get(key)
        if row and self.request_tree.exists(row):
            self.request_tree.item(row,values=values,tags=(phase,))
        else:
            row=self.request_tree.insert('','end',values=values,tags=(phase,));self.request_rows[key]=row
        self.request_tree.see(row)
        if phase=='success':
            self.request_successes+=1
            if data['path']=='/upload_running_chunk':self.upload_successes+=1
        elif phase=='error':self.request_failures+=1
        self.execution_metrics['requests'].set(f'{self.request_successes} / {self.request_failures}')
        self.execution_metrics['uploads'].set(str(self.upload_successes))

    @staticmethod
    def jitter_summary(plan):
        cfg = plan.get('jitter',{})
        if not cfg.get('enabled') or not cfg.get('amplitude_m'):
            return '抖动关闭'
        return f"抖动 ≤{cfg['amplitude_m']:g}米 / 平滑{cfg['smooth_points']}点 / 种子{cfg['seed']} / 目标{plan.get('requested_km',plan['km']):.3f}km"

    def distance_changed(self,*args):
        self.plan_version += 1
        self.route = None
        if hasattr(self,'execute_button'):
            self.execute_button.configure(state='disabled')
            self.run_info.set('公里数或抖动配置已修改，请点击“刷新路线”重新生成，确认后再运行。')

    def set_run_controls(self):
        active = self.run_state in ('starting','running','retry_wait','stopping')
        locked = active or self.planning
        for button in (self.replan_button,self.checkpoint_button):
            button.configure(state='disabled' if locked else 'normal')
        self.km_entry.configure(state='disabled' if active else 'normal')
        for widget in self.jitter_controls:
            widget.configure(state='disabled' if active else 'normal')
        self.execute_button.configure(state='normal' if self.route and not locked else 'disabled')
        self.cancel_run_button.configure(state='normal' if active or self.pending_session else 'disabled')
        if hasattr(self,'execution_retry'):
            self.execution_retry.configure(state='normal' if self.run_state=='retry_wait' else 'disabled')
        if hasattr(self,'execution_stop'):
            self.execution_stop.configure(state='normal' if active or self.pending_session else 'disabled')

    def table(self, parent, columns):
        frame = self.ttk.Frame(parent)
        frame.pack(fill='both', expand=True)
        tree = self.ttk.Treeview(frame, columns=columns, show='headings', selectmode='browse')
        scroll = self.ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        for column in columns:
            tree.heading(column, text=column)
            tree.column(column, width=130, anchor='center', stretch=True)
        tree.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        return tree

    def first_launch(self):
        if self.demo:
            self.show_demo()
            return
        try:
            ProxyLease().restore()
        except Exception:
            self.dialog.showerror('代理恢复', '上次代理备份恢复失败，请点击“恢复代理”重试。')
            return
        if self.settings.data.get('tasktoken'):
            self.refresh()
        else:
            self.choose_token()

    def configure(self):
        if self.closing:
            return
        if self.run_state in ('starting','running','retry_wait','stopping') or self.pending_session:
            self.dialog.showinfo('会话进行中','请先停止当前会话，再修改凭据。')
            return
        win = self.tk.Toplevel(self.root)
        win.title('GhostRunner 设置')
        win.geometry('660x430')
        win.transient(self.root)
        win.grab_set()
        frame = self.ttk.Frame(win, padding=24)
        frame.pack(fill='both', expand=True)
        values = {}
        for row, (field,label) in enumerate([('tasktoken','tasktoken'),('tencent_key','腾讯 WebService Key'),('tencent_js_key','腾讯 JavaScript GL Key（可与上项相同）')]):
            self.ttk.Label(frame, text=label).grid(row=row*2, column=0, sticky='w', pady=(0,5))
            var = self.tk.StringVar(value=self.settings.data.get(field,''))
            self.ttk.Entry(frame, textvariable=var, width=65, show='•').grid(row=row*2+1, column=0, sticky='ew', pady=(0,12))
            values[field] = var
        self.ttk.Label(frame, text='配置保存在 '+str(self.settings.path), style='Sub.TLabel').grid(row=6,column=0,sticky='w')
        self.ttk.Label(frame,text=DEFAULT_KEY_NOTICE,wraplength=590,style='Sub.TLabel').grid(row=7,column=0,sticky='w',pady=(10,0))
        buttons = self.ttk.Frame(frame)
        buttons.grid(row=8,column=0,sticky='e',pady=(16,0))
        def save():
            try:
                if self.run_state in ('starting','running','retry_wait','stopping'):
                    self.dialog.showinfo('运行中','请先停止运行再修改凭据。',parent=win)
                    return
                token = token_text(values['tasktoken'].get()) if values['tasktoken'].get().strip() else ''
                self.generation += 1
                self.plan_version += 1
                self.route = None
                self.checkpoints = []
                self.set_run_controls()
                self.settings.data.update({k:v.get().strip() for k,v in values.items()})
                self.settings.data['tasktoken'] = token
                for field in ('tencent_key','tencent_js_key'):
                    if not self.settings.data[field]:self.settings.data[field]=DEFAULT_TENCENT_KEY
                self.settings.save()
            except (ValueError, OSError) as exc:
                self.dialog.showerror('保存失败',str(exc),parent=win)
                return
            win.destroy()
            self.status.set('配置已保存')
            if token:
                self.refresh()
        self.ttk.Button(buttons,text='重新抓取',command=lambda:(win.destroy(),self.start_capture())).pack(side='left',padx=8)
        self.ttk.Button(buttons,text='保存',command=save,style='Accent.TButton').pack(side='left')

    def choose_token(self):
        win = self.tk.Toplevel(self.root)
        win.title('配置 tasktoken')
        win.geometry('440x210')
        win.transient(self.root)
        win.grab_set()
        frame = self.ttk.Frame(win,padding=24)
        frame.pack(fill='both',expand=True)
        self.ttk.Label(frame,text='请选择登录方式',font=('Microsoft YaHei UI',16,'bold')).pack(anchor='w')
        self.ttk.Label(frame,text='自动抓取时，请在 Windows 微信电脑版打开小程序。',wraplength=390).pack(anchor='w',pady=18)
        bar = self.ttk.Frame(frame)
        bar.pack(fill='x')
        self.ttk.Button(bar,text='重新抓取',command=lambda:(win.destroy(),self.start_capture()),style='Accent.TButton').pack(side='left')
        self.ttk.Button(bar,text='手动填写',command=lambda:(win.destroy(),self.configure())).pack(side='right')

    def emit(self, event, value):
        self.queue.put((event,value))

    def start_capture(self):
        if self.demo:
            self.status.set('离线预览不修改系统代理；正式启动后可抓取')
            return
        if self.capture and self.capture.thread.is_alive():
            self.show_capture_page()
            return
        if not self.dialog.askokcancel('首次抓取', '即将临时开启本机 8080 代理，并请求安装 mitmproxy 根证书。\n仅提取 campusrun.mzwu.edu.cn 的 Bearer token。\n成功、停止、超时和退出时恢复原有代理。\n\n继续后请在微信电脑版打开小程序。'):
            return
        self.capture_phase = 'preparing'
        self.capture_ui_active = True
        self.capture_deadline = None
        self.show_capture_page()
        self.capture_title.set('请打开微信电脑版中的小程序')
        self.capture_status.set('正在启动代理和准备证书，请处理 Windows 证书安装提示。')
        self.capture_remaining.set('准备完成后开始计时；先打开微信电脑版。')
        self.capture_cancel.configure(state='normal')
        self.capture_retry.configure(state='disabled')
        self.capture_results.configure(state='disabled')
        self.capture_progress.start(15)
        self.capture = Capture(self.emit)
        self.stop_button.configure(state='normal')
        self.status.set('正在启动抓取…')
        self.capture.start()

    def stop_capture(self):
        if self.capture:
            self.capture.stop()
            self.capture_phase = 'stopping'
            self.capture_title.set('正在取消抓取')
            self.capture_status.set('正在停止抓取并恢复原有系统代理…')
            self.capture_cancel.configure(state='disabled')
            self.status.set('正在停止抓取并恢复代理…')

    def restore_proxy(self):
        if self.demo:
            self.status.set('离线预览未修改系统代理')
            return
        if self.capture and self.capture.thread.is_alive():
            self.stop_capture()
            return
        try:
            ProxyLease().restore()
            self.status.set('原有代理配置已恢复')
        except Exception:
            self.dialog.showerror('恢复失败','恢复失败，备份日志仍保留在 '+str(STATE))

    def refresh(self):
        if self.demo:
            self.show_demo()
            return
        if self.busy:
            self.pending_refresh = True
            return
        if not self.settings.data.get('tasktoken'):
            self.choose_token()
            return
        self.busy = True
        self.refresh_button.configure(state='disabled')
        self.status.set('正在加载个人信息、每日记录和排名…')
        token = self.settings.data['tasktoken']
        generation = self.generation
        def work():
            try:
                result = CampusClient(token).dashboard()
                self.emit('dashboard',(generation,result))
            except AuthExpired:
                self.emit('expired',generation)
            except Exception as exc:
                self.emit('error','成绩加载失败：'+str(exc))
            finally:
                self.emit('idle',None)
        threading.Thread(target=work,daemon=True).start()

    def render(self, data):
        self.records = data['records']
        for key,value in data['summary'].items():
            self.metrics[key].set(value)
        rank = data['ranking'].get('current_user_rank') or {}
        self.metrics['rank'].set(str(rank.get('rank') or '—'))
        info = data.get('info') or {}
        self.identity.set(info.get('student_name') or info.get('wechat_nickname') or '个人成绩')
        self.record_tree.delete(*self.record_tree.get_children())
        for r in sorted(self.records,key=lambda r:str(r.get('created_at','')),reverse=True):
            valid = valid_record(r)
            self.record_tree.insert('', 'end', values=(r.get('created_at','—'), r.get('distance','—'),
                r.get('duration','—'),r.get('pace','—'), '有效' if valid is True else '无效' if valid is False else '待确认',
                '补跑' if r.get('is_makeup') in (True,1,'1') else '普通'))
        self.rank_tree.delete(*self.rank_tree.get_children())
        for r in data['ranking'].get('rank_list',[]):
            user = r.get('user') or {}
            self.rank_tree.insert('','end',values=(r.get('rank','—'),user.get('student_name') or user.get('wechat_nickname','—'), user.get('total_distance','—')))
        self.status.set('成绩已更新 · 共 '+str(len(self.records))+' 条记录')

    def enter_running(self):
        if self.run_state in ('starting','running','retry_wait','stopping'):
            self.tabs.select(self.execution_tab)
            return
        if not self.demo and not self.settings.data.get('tasktoken'):
            self.choose_token()
            return
        if str(self.map_tab) not in self.tabs.tabs():
            self.tabs.add(self.map_tab,text='跑步规划')
        self.tabs.select(self.map_tab)
        self.plan(reload_checkpoints=True)

    def plan(self,reload_checkpoints=False):
        if self.planning or self.run_state in ('starting','running','retry_wait','stopping'):
            return
        try:
            km = target_km(self.km_var.get())
            jitter = jitter_config({'enabled':self.jitter_enabled.get(),
                'amplitude_m':self.jitter_amplitude.get(),'smooth_points':self.jitter_smooth.get(),
                'seed':self.jitter_seed.get()})
        except ValueError as exc:
            self.dialog.showerror('规划配置',str(exc))
            return
        key = self.settings.data.get('tencent_key','')
        if not self.demo and not key:
            self.dialog.showinfo('腾讯路线规划','请先在设置中填写自己的腾讯 WebService Key。')
            return
        self.planning = True
        self.route = None
        self.plan_version += 1
        version = self.plan_version
        generation = self.generation
        token = self.settings.data.get('tasktoken','')
        cached = list(self.checkpoints)
        self.variant += 1
        variant = self.variant
        self.set_run_controls()
        self.status.set('正在获取打卡点并请求腾讯步行规划…' if reload_checkpoints or not cached else '正在请求新的腾讯步行路线…')
        self.run_info.set('规划中，预览阶段不会创建跑步记录或上传轨迹。')
        def work():
            try:
                if self.pending_session:
                    cps = self.pending_session['checkpoints']
                    route = generate_plan(cps,key,km,variant,
                        leg=(lambda a,b:{'points':[a,b]}) if self.demo else None, jitter=jitter)
                elif self.demo:
                    cps = [{'id':1,'latitude':25.0,'longitude':118.0,'radius':15},
                           {'id':2,'latitude':25.001,'longitude':118.001,'radius':15}]
                    route = generate_plan(cps,'DEMO',km,variant,leg=lambda a,b:{'points':[a,b]},jitter=jitter)
                else:
                    cps = CampusClient(token).checkpoints() if reload_checkpoints or not cached else cached
                    route = generate_plan(cps,key,km,variant,jitter=jitter)
                self.emit('planned',(version,generation,route))
            except AuthExpired:
                self.emit('expired',generation)
            except Exception as exc:
                self.emit('plan_error',(version,str(exc)))
            finally:
                self.emit('plan_idle',None)
        threading.Thread(target=work,daemon=True).start()

    def reload_map(self):
        if self.map_process and self.map_process.poll() is None:
            self.map_process.terminate()
            self.map_process.wait(timeout=5)
        self.map_process = None
        self.map_embedded = False
        if hasattr(self,'map_log') and not self.map_log.closed:
            self.map_log.close()
        self.load_map()

    def load_map(self):
        key = self.settings.data.get('tencent_js_key') or self.settings.data.get('tencent_key')
        if self.demo:
            key = ''  # Never consume the supplied Key during offline demos/tests.
        if not self.route:
            return
        path = STATE / 'map.html'
        path.parent.mkdir(parents=True,exist_ok=True)
        html = map_html(key or '',self.route['points'],self.route.get('checkpoints',[]))
        temp = path.with_suffix('.tmp')
        temp.write_text(html,encoding='utf-8')
        os.replace(temp,path)
        if self.map_process and self.map_process.poll() is None:
            return
        path.with_suffix('.ready').unlink(missing_ok=True)
        self.map_embedded = False
        self.map_deadline = time.monotonic()+40
        self.map_hint.place(relx=.5,rely=.5,anchor='center')
        self.root.update_idletasks()
        self.map_log = (STATE / 'map-error.log').open('w',encoding='utf-8')
        self.map_process = subprocess.Popen(command('--map',self.map_frame.winfo_id(),path),
                                            stdout=self.map_log,stderr=self.map_log,creationflags=0x08000000)
        self.map_hint.configure(text='正在启动内嵌 WebView2 地图…')

    def poll_map_ready(self):
        if not self.map_process or self.map_process.poll() is not None or self.map_embedded:
            return
        try:
            state = json.loads((STATE/'map.ready').read_text(encoding='utf-8'))
            if state.get('pid') != self.map_process.pid or state.get('parent') != self.map_frame.winfo_id():
                return
            if state.get('embedded'):
                self.map_embedded = True
                self.map_hint.place_forget()
            elif state.get('state')=='error':
                self.map_hint.configure(text=state.get('message','地图启动失败，请重载地图'))
        except (OSError,ValueError):
            if time.monotonic()>self.map_deadline:
                self.map_hint.configure(text='地图启动超时，请点击“重载地图”重试。')

    def execute_run(self):
        if not self.route or self.planning or self.run_state in ('starting','running','retry_wait','stopping'):
            return
        p = self.route
        session_note = ('复用已创建会话 '+str(self.pending_session['record_id'])+'，不重复创建记录。') if self.pending_session else '确认后创建跑步会话，并按实际等待时间执行。'
        if not self.dialog.askokcancel('确认运行',f"目标：{p['km']:.3f} 公里\n配速：{p['pace']} /km\n步频：{p['cadence']} 步/分钟\n预计用时：{p['duration']:.1f} 分钟\n抖动：{self.jitter_summary(p)}\n\n{session_note}" if not self.demo else '离线演示将在几秒内完成，不创建或提交真实记录。'):
            return
        self.run_state = 'starting'
        self.show_execution_page(reset=self.pending_session is None)
        self.set_run_controls()
        self.progress_value.set(0)
        self.status.set('正在使用已创建会话执行…' if self.pending_session else '正在创建跑步会话…')
        options = {'created_session':self.pending_session,
                   'replan':lambda cps:generate_plan(cps,self.settings.data.get('tencent_key',''),
                              p.get('requested_km',p['km']),p.get('variant',0)+1,
                              leg=(lambda a,b:{'points':[a,b]}) if self.demo else None,jitter=p.get('jitter'))}
        if self.demo:
            import time
            started = time.monotonic()
            initial = time.time_ns()//1000000
            scale = max(1,p['duration_seconds']/5)
            def transport(path,payload=None):
                if path=='/login/wechat/info':
                    return {'data':{'student_number':'DEMO'}}
                if path=='/create_running_record':
                    return {'data':{'record_id':'DEMO','run_session_id':'DEMO','session_salt':'DEMO',
                                    'checkpoints':p['checkpoints']}}
                return {'code':200}
            options.update({'transport':transport,'clock':lambda:initial+int((time.monotonic()-started)*1000*scale)})
        self.run_session = RunSession(self.settings.data.get('tasktoken',''),p,self.emit,**options)
        self.run_session.start()

    def retry_run(self):
        if self.run_state != 'retry_wait' or not self.run_session:
            return
        if self.retry_path == '/create_running_record' and not self.dialog.askokcancel(
                '确认重试创建','创建请求的响应未确认，重试可能创建新记录。确认重试？'):
            return
        self.execution_retry.configure(state='disabled')
        self.run_session.retry_now()

    def stop_run(self):
        if self.pending_session and self.run_state=='ready':
            if self.run_session:
                self.run_session.stop()
            record = self.pending_session.get('record_id')
            self.pending_session = None
            self.run_state = 'stopped'
            self.set_run_controls()
            self.status.set('已停止本地待确认会话；服务端记录保留，record_id='+str(record))
            return
        if self.run_session:
            self.run_state = 'stopping'
            self.run_session.stop()
            self.status.set('正在停止，已发送的请求不会自动撤销…')
            self.set_run_controls()

    def events(self):
        try:
            while True:
                event,value = self.queue.get_nowait()
                if event == 'status' or event == 'capture_end':
                    self.status.set(value)
                    if self.capture_ui_active and event=='status':
                        self.capture_status.set(value)
                        if '抓取超时' in value:
                            self.capture_phase = 'timeout'
                            self.capture_title.set('抓取超时，请重新抓取或手动填写')
                    if event == 'capture_end':
                        self.stop_button.configure(state='disabled')
                        self.capture_ui_active = False
                        self.capture_progress.stop()
                        self.capture_cancel.configure(state='disabled')
                        self.capture_retry.configure(state='normal')
                        self.capture_remaining.set('抓取已结束 · 原有系统代理已恢复')
                        if self.capture_phase not in ('success','timeout','error'):
                            self.capture_phase = 'ended'
                            self.capture_title.set('抓取已取消或结束')
                            self.capture_status.set(value)
                elif event == 'capture_waiting':
                    if self.capture_ui_active and self.capture_phase!='stopping':
                        self.capture_phase = 'waiting'
                        self.capture_deadline = time.monotonic()+value['timeout']
                        self.capture_title.set('抓取已开始，请立即打开小程序！')
                        self.capture_status.set('请在 Windows 微信电脑版打开校园跑步小程序，进入成绩页或刷新页面。')
                        self.capture_remaining.set(f"剩余 {value['timeout']} 秒 · 等待小程序请求")
                elif event == 'token':
                    self.generation += 1
                    self.settings.data['tasktoken'] = value
                    self.settings.save()
                    self.capture_phase = 'success'
                    self.capture_title.set('抓取成功，tasktoken 已保存')
                    self.capture_status.set('正在读取成绩。可点击“查看成绩”，下次启动自动读取配置。')
                    self.capture_results.configure(state='normal')
                    self.status.set('tasktoken 已保存，正在读取成绩…')
                    self.refresh()
                elif event == 'dashboard':
                    if value[0] == self.generation:
                        self.render(value[1])
                elif event == 'idle':
                    self.busy = False
                    self.refresh_button.configure(state='normal')
                    if self.pending_refresh:
                        self.pending_refresh = False
                        self.refresh()
                elif event == 'expired':
                    if value == self.generation:
                        self.choose_token()
                elif event == 'error':
                    if self.capture_ui_active:
                        self.capture_phase = 'error'
                        self.capture_title.set('抓取遇到问题')
                        self.capture_status.set(value)
                    self.status.set(value)
                    if not self.closing:
                        self.dialog.showerror('GhostRunner',value)
                elif event == 'planned':
                    version,generation,route = value
                    if version == self.plan_version and generation == self.generation:
                        self.route = route
                        self.checkpoints = route['checkpoints']
                        self.run_state = 'ready'
                        self.run_info.set(f"{len(self.checkpoints)} 个打卡点 · {route['km']:.3f} 公里 · 建议配速 {route['pace']} /km · 步频 {route['cadence']} · 预计 {route['duration']:.1f} 分钟 · {self.jitter_summary(route)}")
                        if not self.demo:
                            self.settings.data['run_km'] = route.get('requested_km',route['km'])
                            self.settings.data['route_jitter'] = jitter_config({
                                'enabled':self.jitter_enabled.get(),'amplitude_m':self.jitter_amplitude.get(),
                                'smooth_points':self.jitter_smooth.get(),'seed':self.jitter_seed.get()})
                            self.settings.save()
                        self.load_map()
                        self.status.set('路线已生成，可刷新选择方案，满意后点击“确认运行”。')
                elif event == 'plan_error':
                    if value[0] == self.plan_version:
                        self.run_info.set(value[1])
                        self.status.set('路线规划失败：'+value[1])
                        self.dialog.showerror('路线规划',value[1])
                elif event == 'plan_idle':
                    self.planning = False
                    self.set_run_controls()
                elif event == 'run_started':
                    self.pending_session = None
                    self.run_state = 'running'
                    self.status.set('会话已创建，正在按计划执行；record_id='+str(value['record_id']))
                    self.set_run_controls()
                    self.tabs.select(self.execution_tab)
                    self.execution_state.set('执行中 · 会话 '+str(value['record_id'])+' · 按计划等待并上传分片')
                elif event == 'request_log':
                    self.append_request_log(value)
                elif event == 'run_retry_wait':
                    if self.run_state=='stopping':
                        continue
                    if self.run_state!='retry_wait':
                        self.retry_resume_state = self.run_state
                    self.run_state = 'retry_wait'
                    self.retry_path = value['path']
                    detail = f"{value['remaining']} 秒后自动重试" if value['automatic'] else '等待手动重试或停止'
                    code = str(value['code']) if value['code'] is not None else value['error_type']
                    text = f"请求失败（{code}）· {value['path']} · {detail} · 下次第 {value['attempt']} 次尝试"
                    self.execution_state.set(text)
                    self.status.set(text)
                    self.tabs.select(self.execution_tab)
                    self.set_run_controls()
                elif event == 'run_retrying':
                    if self.run_state=='stopping':
                        continue
                    self.run_state = self.retry_resume_state
                    self.execution_state.set(f"正在重试 {value['path']} · 第 {value['attempt']} 次尝试")
                    self.set_run_controls()
                elif event == 'run_plan_updated':
                    self.route = value['plan']
                    self.checkpoints = self.route['checkpoints']
                    route = self.route
                    self.run_info.set(f"已同步会话打卡点 · {route['km']:.3f} 公里 · 配速 {route['pace']} · 预计 {route['duration']:.1f} 分钟 · {self.jitter_summary(route)}")
                    self.execution_state.set('本次会话路线已同步，自动继续执行。')
                    self.load_map()
                elif event == 'run_replanned':
                    self.pending_session = value['session']
                    self.route = value.get('plan')
                    self.checkpoints = self.pending_session['checkpoints']
                    self.run_state = 'ready'
                    self.set_run_controls()
                    self.execution_state.set('本次会话路线规划需要调整，已保留会话。')
                    self.tabs.select(self.map_tab)
                    if self.route:
                        route = self.route
                        self.run_info.set(f"已同步本次会话 {len(self.checkpoints)} 个实际打卡点 · {route['km']:.3f} 公里 · 配速 {route['pace']} · 预计 {route['duration']:.1f} 分钟 · {self.jitter_summary(route)}")
                        self.load_map()
                        self.status.set('会话打卡点已同步并重新规划，请查看路线后再次确认；将复用 record_id='+str(value['record_id']))
                    else:
                        self.run_info.set('实际打卡点已同步，请调整公里数并刷新路线：'+value.get('message',''))
                        self.status.set('已保留会话，调整路线后再确认运行；record_id='+str(value['record_id']))
                elif event == 'run_progress':
                    self.progress_value.set(min(99,100*value['elapsed']/max(1,value['duration'])))
                    self.execution_percent.set(f"{min(99,int(100*value['elapsed']/max(1,value['duration'])))}%")
                    self.execution_metrics['elapsed'].set(self.duration_text(value['elapsed']))
                    self.execution_metrics['remaining'].set(self.duration_text(max(0,value['duration']-value['elapsed'])))
                    self.execution_state.set('执行中 · 等待下一次上传' if value['elapsed']<value['duration'] else '运动计划时间已到 · 等待结束请求确认')
                    self.status.set(f"运行中 · {int(value['elapsed'])//60} 分 {int(value['elapsed'])%60:02d} 秒 · 已发送 {value['sent']}/{value['total']}")
                elif event == 'run_upload':
                    self.status.set(f"已发送 {value['sent']}/{value['total']} 个请求")
                elif event in ('run_finished','run_stopped','run_error'):
                    self.pending_session = None
                    self.run_state = 'finished' if event=='run_finished' else 'stopped'
                    self.set_run_controls()
                    if event=='run_finished':
                        self.progress_value.set(100)
                        self.execution_percent.set('100%')
                        self.execution_metrics['remaining'].set('00:00:00')
                        self.execution_state.set('任务完成 · 结束请求成功，成绩以平台审核结果为准。' if not self.demo else '离线演示完成 · 全部模拟请求成功。')
                        self.status.set('结束接口返回成功，正在刷新成绩。' if not self.demo else '离线演示运行完成')
                        self.refresh()
                    elif event=='run_stopped':
                        self.execution_state.set('已停止 · 已发送的请求保留，未自动发送结束请求。')
                        self.status.set('运行已停止；已提交的记录保留，未自动提交结束请求。')
                    else:
                        self.execution_state.set('执行失败 · '+value['message'])
                        self.status.set('运行失败：'+value['message'])
                        self.dialog.showerror('运行失败',value['message']+'\nrecord_id='+str(value.get('record_id') or '尚未创建'))
        except queue.Empty:
            pass
        except (OSError, ValueError) as exc:
            self.dialog.showerror('配置保存失败',str(exc))
        self.poll_map_ready()
        if self.map_process and self.map_process.poll() is not None:
            self.map_embedded = False
            self.map_hint.place(relx=.5,rely=.5,anchor='center')
            self.map_hint.configure(text='地图进程已结束。请确认 WebView2 Runtime 已安装，且 Key 已开通 JS API。')
            self.map_process = None
            self.map_log.close()
        self.root.after(100,self.events)

    def show_demo(self):
        records = [{'id':i,'created_at':f'2026-10-{i+1:02d} 17:30','distance':3.2,
                    'duration':1152,'pace':'6′00″','is_completed':True,'has_cheating':i==2} for i in range(8)]
        self.render({'info':{'student_name':'演示用户 · 离线预览'},'records':records,'summary':summarize(records),
                     'ranking':{'current_user_rank':{'rank':12},'rank_list':[{'rank':i+1,'user':{'student_name':f'演示同学 {i+1}','total_distance':80-i*3}} for i in range(15)]}})
        self.status.set('离线演示数据 · 未读取真实账号 · 未修改系统代理')

    def close(self):
        self.closing = True
        if self.run_session and self.run_session.thread and self.run_session.thread.is_alive():
            self.run_session.stop()
            self.status.set('正在停止运行任务后退出…')
            self.root.after(200,self.close)
            return
        if self.capture and self.capture.thread.is_alive():
            self.capture.stop()
            self.status.set('正在等待抓取退出，恢复原有代理后关闭…')
            self.root.after(200,self.close)
            return
        try:
            if not self.demo:
                ProxyLease().restore()
        except Exception:
            self.closing = False
            self.dialog.showerror('代理恢复','代理尚未恢复，请先点击恢复代理。')
            return
        if self.map_process and self.map_process.poll() is None:
            self.map_process.terminate()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo',action='store_true')
    parser.add_argument('--guardian',nargs=2,metavar=('PID','JOURNAL'))
    parser.add_argument('--map',nargs=2,metavar=('HWND','HTML'))
    parser.add_argument('--map-input-probe',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--smoke-test',action='store_true')
    args = parser.parse_args()
    if args.guardian:
        guardian(*args.guardian)
        return
    if args.map:
        run_embedded(*args.map,input_probe=args.map_input_probe)
        return
    if os.name != 'nt':
        parser.error('仅支持 Windows')
    # Single instance prevents proxy leases and config writes from overlapping.
    kernel = ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p,ctypes.c_int,ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    mutex = kernel.CreateMutexW(None,False,'Local\\GhostRunnerDesktopSmoke' if args.smoke_test else 'Local\\GhostRunnerDesktop')
    if ctypes.get_last_error() == 183:
        ctypes.windll.user32.MessageBoxW(None,'GhostRunner 已在运行。','GhostRunner',0)
        return
    try:
        application = Application(demo=args.demo or args.smoke_test)
        if args.smoke_test:
            assert str(application.map_tab) not in application.tabs.tabs()
            application.enter_running()
            assert str(application.map_tab) in application.tabs.tabs()
            application.root.after(1200,application.close)
        application.root.mainloop()
    finally:
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(mutex)


if __name__ == '__main__':
    main()
