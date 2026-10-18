"""Capture real Material QML windows with in-scene numbered arrows.

Only offline demonstration data is used. Labels and arrows are QML objects
rendered before grabWindow, not a painted or fabricated application screenshot.
Usage: python tests/capture_material_docs.py overview|capture|route|execution|settings
"""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.vendor'))
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
os.environ['GHOSTRUNNER_STATE_DIR'] = str(ROOT.parent / '.codex-artifacts/documentation-preview-state')

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlEngine, QQmlExpression
from PySide6.QtQuick import QQuickWindow
from PySide6.QtWebEngineQuick import QtWebEngineQuick
from material_app import Backend

SCENES = {
    'overview': (0, '00-material-overview.png', [
        (1, '左侧切换页面', 490, 88, 102, 113),
        (2, '查看里程、配速与排名', 760, 95, 802, 264),
        (3, '设置 Key / 手动登录', 290, 758, 108, 792),
        (4, '进入跑步规划', 1015, 100, 1297, 47),
    ]),
    'capture': (5, '01-capture.png', [
        (1, '先阅读页面提示', 910, 120, 602, 191),
        (2, '在此查看状态与倒计时', 760, 495, 432, 529),
        (3, '开始抓取 / 随时停止', 380, 681, 405, 605),
        (4, '退出前可恢复原代理', 918, 646, 709, 605),
    ]),
    'route': (3, '02-route.png', [
        (1, '设置目标公里数', 435, 82, 336, 186),
        (2, '刷新路线方案', 940, 79, 1187, 126),
        (3, '离线演示不加载在线底图', 630, 362, 803, 536),
        (4, '检查参数后确认运行', 1030, 242, 1291, 126),
    ]),
    'execution': (4, '03-execution.png', [
        (1, '查看执行进度', 421, 179, 795, 280),
        (2, '时间、分片与请求统计', 878, 213, 918, 360),
        (3, '逐条检查请求日志', 624, 746, 795, 613),
        (4, '重试或停止当前任务', 1000, 170, 1283, 134),
    ]),
    'settings': (0, '04-settings.png', [
        (1, '仅填写自己的 tasktoken', 290, 145, 691, 319),
        (2, 'WebService 路线规划 Key', 285, 215, 695, 391),
        (3, 'JavaScript GL 地图 Key', 940, 641, 695, 462),
        (4, '确认后保存配置', 1015, 748, 973, 603),
    ]),
}

OVERLAY = r'''
import QtQuick
Item {
    id: guide
    anchors.fill: parent
    z: 100000
    property var marks: []
    Canvas {
        anchors.fill: parent
        onPaint: {
            var c = getContext("2d"); c.reset();
            c.strokeStyle = "#FFD166"; c.fillStyle = "#FFD166"; c.lineWidth = 3.5;
            for (var i=0; i<guide.marks.length; i++) {
                var m=guide.marks[i], sx=m.x+120, sy=m.y+22;
                var a=Math.atan2(m.ty-sy,m.tx-sx), tx=m.tx-15*Math.cos(a), ty=m.ty-15*Math.sin(a);
                c.beginPath(); c.moveTo(sx,sy); c.lineTo(tx,ty); c.stroke();
                c.beginPath(); c.moveTo(tx,ty);
                c.lineTo(tx-15*Math.cos(a-0.5),ty-15*Math.sin(a-0.5));
                c.lineTo(tx-15*Math.cos(a+0.5),ty-15*Math.sin(a+0.5));
                c.closePath(); c.fill();
                c.beginPath(); c.arc(m.tx,m.ty,10,0,2*Math.PI); c.stroke();
            }
        }
    }
    Repeater {
        model: guide.marks
        Rectangle {
            required property var modelData
            x: modelData.x; y: modelData.y; width: 250; height: 44
            radius: 9; color: "#172B4D"; border.color: "#FFD166"; border.width: 2
            Rectangle {
                x: 8; y: 8; width: 28; height: 28; radius: 14; color: "#FFD166"
                Text { anchors.centerIn: parent; text: modelData.n; color: "#172B4D"; font.bold: true; font.pixelSize: 18 }
            }
            Text {
                x: 43; anchors.verticalCenter: parent.verticalCenter
                text: modelData.label; color: "white"; font.family: "Microsoft YaHei UI"; font.pixelSize: 15; font.bold: true
            }
        }
    }
}
'''


def main(scene):
    page, name, marks = SCENES[scene]
    QtWebEngineQuick.initialize()
    app = QGuiApplication(sys.argv[:1])
    app.setApplicationName('GhostRunner documentation preview')
    engine = QQmlApplicationEngine()
    material = ROOT / 'third_party/material-components-pyside'
    sys.path.insert(0, str(material))
    from stylemanager import StyleManager
    style = StyleManager()
    style.setSeedColor('#2864DC')
    backend = Backend(demo=True, check_updates=False)
    if scene == 'settings':
        backend.settings.path = Path('DEMO/config.json')
        backend._set(settingsPath='DEMO/config.json')
    engine.addImportPath(str(material / 'src'))
    engine.rootContext().setContextProperty('Backend', backend)
    engine.rootContext().setContextProperty('StyleManager', style)
    engine.load(QUrl.fromLocalFile(str(ROOT / 'ui/Main.qml')))
    if not engine.rootObjects():
        raise RuntimeError('QML application failed to load')
    window = engine.rootObjects()[0]
    window.setProperty('pageIndex', page)
    app.aboutToQuit.connect(backend.close)
    if page in (3, 4):
        backend.planRoute(3.0, True, 3.0, 12, '42', True)
    if page == 4:
        def run_demo():
            if backend.routeReady and not backend.planning:
                backend.executeRun()
            else:
                QTimer.singleShot(100, run_demo)
        QTimer.singleShot(100, run_demo)
    if scene == 'settings':
        expression = QQmlExpression(QQmlEngine.contextForObject(window), window, 'settingsPopup.open()')
        expression.evaluate()
        if expression.hasError():
            raise RuntimeError(expression.error().toString())
    component = QQmlComponent(engine)
    component.setData(OVERLAY.encode('utf-8'), QUrl('file:///documentation-overlay.qml'))
    if component.isError():
        raise RuntimeError(str(component.errors()))
    guide = component.createWithInitialProperties({'marks': [
        dict(n=n, label=label, x=x, y=y, tx=tx, ty=ty) for n,label,x,y,tx,ty in marks
    ]})
    if scene == 'settings':
        overlay = QQmlExpression(QQmlEngine.contextForObject(window), window, 'QQC.Overlay.overlay')
        overlay_item = overlay.evaluate()
        if isinstance(overlay_item, tuple):
            overlay_item = overlay_item[0]
        if overlay.hasError() or overlay_item is None:
            raise RuntimeError('Cannot resolve the popup overlay')
        guide.setParentItem(overlay_item)
    else:
        guide.setParentItem(window.contentItem())
    guide.setParent(window)
    def capture():
        target = ROOT / 'docs/screenshots' / name
        if not QQuickWindow.grabWindow(window).save(str(target)):
            app.exit(2)
            return
        print(f'DOC_SCREENSHOT_OK: {name}; page={page}; numbered_arrows={len(marks)}; offline_demo=True')
        app.quit()
    QTimer.singleShot(3500 if page == 4 else 2600, capture)
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1]))
