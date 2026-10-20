import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC
import QtWebEngine
import md3.Core as MD3

QQC.ApplicationWindow {
    id: window
    visible: true
    width: 1380
    height: 880
    minimumWidth: 1080
    minimumHeight: 700
    title: "GhostRunner " + Backend.version + " · Material You"
    color: MD3.Theme.color.background

    property int pageIndex: 0
    property var pendingUpdate: ({})

    function openError(title, message) {
        messageTitle.text = title
        messageBody.text = message
        messagePopup.open()
    }

    Connections {
        target: Backend
        function onAuthRequired() { authPopup.open() }
        function onErrorRaised(title, message) { window.openError(title, message) }
        function onInfoRaised(title, message) { window.openError(title, message) }
        function onUpdateAvailable(info) {
            pendingUpdate = info
            updateTitle.text = "发现新版本 " + info.version
            updateBody.text = (info.name || "GhostRunner " + info.version) + (info.notes ? "\n\n" + info.notes : "")
            updatePopup.open()
        }
    }

    component SectionTitle: Text {
        color: MD3.Theme.color.onSurfaceColor
        font.family: "Microsoft YaHei UI"
        font.pixelSize: 28
        font.weight: Font.DemiBold
    }

    component BodyText: Text {
        color: MD3.Theme.color.onSurfaceVariantColor
        font.family: "Microsoft YaHei UI"
        font.pixelSize: 14
        wrapMode: Text.Wrap
    }

    component MetricCard: MD3.Card {
        id: metricCard
        property string label: ""
        property string value: "—"
        type: "elevated"
        Layout.fillWidth: true
        Layout.preferredHeight: 126
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 20
            spacing: 8
            BodyText { text: metricCard.label; Layout.fillWidth: true }
            Text {
                text: metricCard.value
                color: MD3.Theme.color.primary
                font.family: "Microsoft YaHei UI"
                font.pixelSize: 28
                font.weight: Font.Bold
                Layout.fillWidth: true
            }
        }
    }

    // Pages provide layout only; individual cards keep their own surfaces.
    component SurfacePage: Item {}

    RowLayout {
        anchors.fill: parent
        spacing: 0

        MD3.NavigationRail {
            id: navigation
            Layout.fillHeight: true
            Layout.preferredWidth: 222
            extended: true
            currentIndex: window.pageIndex
            model: [
                {icon: "home", text: "概览"},
                {icon: "calendar_month", text: "每日记录"},
                {icon: "leaderboard", text: "班级排名"},
                {icon: "route", text: "跑步规划"},
                {icon: "monitoring", text: "任务进度"},
                {icon: "vpn_key", text: "抓取登录"}
            ]
            onItemClicked: function(index) {
                window.pageIndex = index
                if (index === 3 && !Backend.routeReady && !Backend.planning)
                    planCurrent(true)
            }
            header: Component {
                ColumnLayout {
                    width: navigation.width
                    height: 112
                    spacing: 2
                    Text {
                        text: "GhostRunner"
                        color: MD3.Theme.color.primary
                        font.pixelSize: 22
                        font.weight: Font.Bold
                        Layout.leftMargin: 24
                        Layout.topMargin: 24
                    }
                    BodyText { text: "版本 " + Backend.version; Layout.leftMargin: 24 }
                }
            }
            footer: Component {
                ColumnLayout {
                    width: navigation.width
                    spacing: 8
                    MD3.Button {
                        Layout.leftMargin: 16
                        Layout.rightMargin: 16
                        Layout.fillWidth: true
                        text: "设置"
                        icon: "settings"
                        type: "filledTonal"
                        onClicked: settingsPopup.open()
                    }
                    MD3.Button {
                        Layout.leftMargin: 16
                        Layout.rightMargin: 16
                        Layout.bottomMargin: 20
                        Layout.fillWidth: true
                        text: "检查更新"
                        icon: "system_update"
                        type: "text"
                        onClicked: Backend.checkForUpdates()
                    }
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: 20
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 54
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    Text {
                        text: Backend.identity
                        color: MD3.Theme.color.onSurfaceColor
                        font.pixelSize: 18
                        font.weight: Font.DemiBold
                    }
                    BodyText { text: Backend.status; Layout.fillWidth: true; elide: Text.ElideRight }
                }
                MD3.Button { text: "恢复代理"; type: "text"; onClicked: Backend.restoreProxy() }
                MD3.Button { text: "刷新成绩"; icon: "refresh"; type: "filledTonal"; onClicked: Backend.refresh() }
                MD3.Button {
                    text: "开始跑步"
                    icon: "directions_run"
                    type: "filled"
                    onClicked: {
                        window.pageIndex = Backend.runState === "running" || Backend.runState === "retry_wait" ? 4 : 3
                        navigation.currentIndex = window.pageIndex
                        if (window.pageIndex === 3 && !Backend.routeReady && !Backend.planning) planCurrent(true)
                    }
                }
            }

            StackLayout {
                id: pages
                currentIndex: window.pageIndex
                Layout.fillWidth: true
                Layout.fillHeight: true

                SurfacePage {
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 28
                        spacing: 18
                        SectionTitle { text: "运动概览" }
                        BodyText { text: Backend.defaultKeyNotice; Layout.fillWidth: true }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 14
                            MetricCard { label: "总里程"; value: Backend.metrics.distance || "—" }
                            MetricCard { label: "跑步次数"; value: Backend.metrics.count || "—" }
                            MetricCard { label: "平均配速"; value: Backend.metrics.pace || "—" }
                            MetricCard { label: "有效成绩"; value: Backend.metrics.valid || "—" }
                            MetricCard { label: "班级排名"; value: Backend.metrics.rank || "—" }
                        }
                        MD3.Card {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            type: "filled"
                            ColumnLayout {
                                anchors.centerIn: parent
                                spacing: 14
                                Text { text: "directions_run"; font.family: MD3.Theme.iconFont.name; font.pixelSize: 72; color: MD3.Theme.color.primary; Layout.alignment: Qt.AlignHCenter }
                                Text { text: "从规划到执行，一页完成"; font.pixelSize: 22; font.weight: Font.DemiBold; color: MD3.Theme.color.onSurfaceColor; Layout.alignment: Qt.AlignHCenter }
                                BodyText { text: "获取打卡点、规划路线、查看地图、配置抖动和跟踪上传进度。"; Layout.alignment: Qt.AlignHCenter }
                                MD3.Button { text: "开始规划"; type: "filled"; Layout.alignment: Qt.AlignHCenter; onClicked: { window.pageIndex = 3; planCurrent(true) } }
                            }
                        }
                    }
                }

                SurfacePage {
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 28
                        spacing: 16
                        SectionTitle { text: "每日记录" }
                        BodyText { text: "状态依据平台返回字段；缺失状态显示“待确认”。" }
                        MD3.DataTable {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            columns: [
                                {label: "日期", role: "date", width: 180},
                                {label: "里程 / km", role: "distance", width: 100},
                                {label: "时长 / 秒", role: "duration", width: 100},
                                {label: "配速", role: "pace", width: 90},
                                {label: "状态", role: "status", width: 90},
                                {label: "类型", role: "kind", width: 80}
                            ]
                            rowData: Backend.records
                        }
                    }
                }

                SurfacePage {
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 28
                        spacing: 16
                        SectionTitle { text: "班级排名" }
                        BodyText { text: "显示班级前 50 名，个人名次以平台返回值为准。" }
                        MD3.DataTable {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            columns: [
                                {label: "排名", role: "rank", width: 90},
                                {label: "姓名", role: "name", width: 220},
                                {label: "累计里程 / km", role: "distance", width: 160}
                            ]
                            rowData: Backend.rankings
                        }
                    }
                }

                SurfacePage {
                    id: routePage
                    function numeric(field, fallback) {
                        var value = Number(field.text)
                        return isFinite(value) ? value : fallback
                    }
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 20
                        spacing: 12
                        RowLayout {
                            Layout.fillWidth: true
                            SectionTitle { text: "跑步规划"; Layout.fillWidth: true }
                            MD3.Button { text: "重载地图"; type: "text"; onClicked: Backend.reloadMap() }
                            MD3.Button { text: "重新获取打卡点"; type: "outlined"; enabled: !Backend.planning; onClicked: planCurrent(true) }
                            MD3.Button { text: Backend.planning ? "规划中…" : "刷新路线"; type: "filledTonal"; enabled: !Backend.planning; onClicked: planCurrent(false) }
                            MD3.Button { text: "确认运行"; type: "filled"; enabled: Backend.routeReady && !Backend.planning; onClicked: runConfirmPopup.open() }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 12
                            MD3.TextField { id: kmField; Layout.preferredWidth: 150; label: "目标公里数"; type: "outlined"; text: Backend.runKm }
                            MD3.Switch { id: jitterSwitch; checked: !!Backend.jitter.enabled }
                            BodyText { text: "模拟路径抖动" }
                            MD3.TextField { id: amplitudeField; Layout.preferredWidth: 130; label: "幅度 / 米"; type: "outlined"; text: String(Backend.jitter.amplitude_m || 3) }
                            MD3.TextField { id: smoothField; Layout.preferredWidth: 130; label: "平滑点数"; type: "outlined"; text: String(Backend.jitter.smooth_points || 12) }
                            MD3.TextField { id: seedField; Layout.preferredWidth: 170; label: "随机种子（可空）"; type: "outlined"; text: String(Backend.jitter.seed || "") }
                            Item { Layout.fillWidth: true }
                        }
                        BodyText { text: Backend.routeInfo; Layout.fillWidth: true }
                        MD3.LinearProgress { Layout.fillWidth: true; value: Backend.progress; indeterminate: Backend.planning }
                        MD3.Card {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            type: "outlined"
                            Item {
                                anchors.fill: parent
                                anchors.margins: 1
                                Rectangle { anchors.fill: parent; radius: 12; color: MD3.Theme.color.surfaceContainerLow }
                                Loader {
                                    anchors.fill: parent
                                    anchors.margins: 1
                                    active: window.pageIndex === 3 && Backend.mapUrl !== ""
                                    sourceComponent: WebEngineView {
                                        id: mapView
                                        url: Backend.mapUrl
                                        settings.javascriptEnabled: true
                                        // Tencent JavaScript GL reads window.localStorage while
                                        // constructing its internal style registry. Disabling it
                                        // makes localStorage null and the SDK crashes at getItem().
                                        settings.localStorageEnabled: true
                                        settings.fullScreenSupportEnabled: false
                                        onWidthChanged: resizeTimer.restart()
                                        onHeightChanged: resizeTimer.restart()
                                        onLoadingChanged: function(request) {
                                            if (request.status === WebEngineLoadingInfo.LoadSucceededStatus) resizeTimer.restart()
                                        }
                                        Timer {
                                            id: resizeTimer
                                            interval: 120
                                            repeat: false
                                            onTriggered: mapView.runJavaScript("window.GHOSTRUNNER_FORCE_RESIZE && window.GHOSTRUNNER_FORCE_RESIZE()")
                                        }
                                    }
                                }
                                ColumnLayout {
                                    anchors.centerIn: parent
                                    visible: Backend.mapUrl === ""
                                    Text { text: "map"; font.family: MD3.Theme.iconFont.name; font.pixelSize: 64; color: MD3.Theme.color.primary; Layout.alignment: Qt.AlignHCenter }
                                    BodyText { text: Backend.planning ? "正在获取打卡点并规划路线…" : "路线生成后将在这里显示腾讯地图" }
                                }
                            }
                        }
                    }
                }

                SurfacePage {
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 28
                        spacing: 16
                        RowLayout {
                            Layout.fillWidth: true
                            SectionTitle { text: "任务进度"; Layout.fillWidth: true }
                            MD3.Button { text: "返回路线"; type: "text"; onClicked: window.pageIndex = 3 }
                            MD3.Button { text: "立即重试"; type: "filledTonal"; enabled: Backend.runState === "retry_wait"; onClicked: Backend.retryRun() }
                            MD3.Button { text: "停止任务"; type: "outlined"; enabled: Backend.runState === "running" || Backend.runState === "retry_wait" || Backend.runState === "starting"; onClicked: Backend.stopRun() }
                        }
                        BodyText { text: Backend.executionState; Layout.fillWidth: true }
                        Text { text: Math.round(Backend.progress * 100) + "%"; color: MD3.Theme.color.primary; font.pixelSize: 42; font.weight: Font.Bold }
                        MD3.LinearProgress { Layout.fillWidth: true; Layout.preferredHeight: 12; value: Backend.progress }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 14
                            MetricCard { label: "已执行时间"; value: Backend.executionMetrics.elapsed || "00:00:00" }
                            MetricCard { label: "预计剩余"; value: Backend.executionMetrics.remaining || "00:00:00" }
                            MetricCard { label: "已上传分片"; value: Backend.executionMetrics.uploads || "0" }
                            MetricCard { label: "请求成功 / 失败"; value: Backend.executionMetrics.requests || "0 / 0" }
                        }
                        BodyText { text: "上传请求日志（不记录 token、签名、salt 或轨迹正文）" }
                        MD3.DataTable {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            columns: [
                                {label: "时间", role: "time", width: 90}, {label: "方法", role: "method", width: 65},
                                {label: "接口", role: "path", width: 260}, {label: "分片", role: "chunk", width: 60},
                                {label: "点数", role: "points", width: 60}, {label: "状态", role: "status", width: 150},
                                {label: "耗时 / ms", role: "duration", width: 90}
                            ]
                            rowData: Backend.requestLogs
                        }
                    }
                }

                SurfacePage {
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 40
                        spacing: 18
                        SectionTitle { text: "抓取 tasktoken" }
                        Text { text: Backend.captureTitle; color: MD3.Theme.color.primary; font.pixelSize: 24; font.weight: Font.DemiBold }
                        MD3.Card {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 245
                            type: "filled"
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 24
                                spacing: 12
                                BodyText { text: "1. 程序先验证并安装 mitmproxy 根证书，成功后才启用系统代理。" }
                                BodyText { text: "2. 看到“抓取已开始”后，打开 Windows 微信电脑版。" }
                                BodyText { text: "3. 打开校园跑步小程序，进入成绩 / 跑步记录页面；已打开则刷新。" }
                                BodyText { text: "4. 获取到 token 后会自动保存，并恢复抓取前的全部代理设置。" }
                                BodyText { text: "其他网站走透传通道；抓取仅检查目标域名的 Authorization: Bearer。" }
                            }
                        }
                        BodyText { text: Backend.captureStatus; Layout.fillWidth: true }
                        MD3.Card {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 112
                            type: "outlined"
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 16
                                spacing: 10
                                BodyText { text: "证书状态：" + Backend.certificateStatus; Layout.fillWidth: true }
                                RowLayout {
                                    spacing: 10
                                    MD3.Button { text: "验证证书"; type: "outlined"; enabled: !Backend.certificateBusy && !Backend.captureActive; onClicked: Backend.verifyCertificate() }
                                    MD3.Button { text: Backend.certificateBusy ? "处理中…" : "安装证书"; type: "filled"; enabled: !Backend.certificateBusy && !Backend.captureActive; onClicked: certificateInstallPopup.open() }
                                    MD3.Button { text: "一键修复"; type: "text"; enabled: !Backend.certificateBusy && !Backend.captureActive; onClicked: certificateRepairPopup.open() }
                                }
                            }
                        }
                        MD3.LinearProgress { Layout.fillWidth: true; indeterminate: Backend.captureActive }
                        BodyText { text: Backend.captureRemaining }
                        RowLayout {
                            spacing: 12
                            MD3.Button { text: Backend.captureActive ? "抓取中…" : "开始抓取"; type: "filled"; enabled: !Backend.captureActive; onClicked: captureConfirmPopup.open() }
                            MD3.Button { text: "停止抓取"; type: "outlined"; enabled: Backend.captureActive; onClicked: Backend.stopCapture() }
                            MD3.Button { text: "手动填写"; type: "text"; onClicked: settingsPopup.open() }
                            MD3.Button { text: "恢复代理"; type: "text"; onClicked: Backend.restoreProxy() }
                        }
                        Item { Layout.fillHeight: true }
                    }
                }
            }
        }
    }

    function planCurrent(reloadPoints) {
        Backend.planRoute(routePage.numeric(kmField, 3), jitterSwitch.checked,
                          routePage.numeric(amplitudeField, 3), Math.round(routePage.numeric(smoothField, 12)),
                          seedField.text, reloadPoints)
    }

    QQC.Popup {
        id: messagePopup
        anchors.centerIn: parent
        width: 520
        modal: true
        closePolicy: QQC.Popup.CloseOnEscape
        background: MD3.Card { type: "elevated" }
        contentItem: ColumnLayout {
            spacing: 18
            SectionTitle { id: messageTitle; font.pixelSize: 22; Layout.fillWidth: true }
            BodyText { id: messageBody; Layout.fillWidth: true }
            MD3.Button { text: "确定"; type: "filled"; Layout.alignment: Qt.AlignRight; onClicked: messagePopup.close() }
        }
        padding: 26
    }

    QQC.Popup {
        id: authPopup
        anchors.centerIn: parent
        width: 500
        modal: true
        closePolicy: QQC.Popup.NoAutoClose
        background: MD3.Card { type: "elevated" }
        contentItem: ColumnLayout {
            spacing: 18
            SectionTitle { text: "配置 tasktoken"; font.pixelSize: 22 }
            BodyText { text: "自动抓取时，请在 Windows 微信电脑版打开小程序；也可以手动填写已有 token。"; Layout.fillWidth: true }
            RowLayout {
                Layout.fillWidth: true
                MD3.Button { text: "自动抓取"; type: "filled"; onClicked: { authPopup.close(); window.pageIndex = 5; captureConfirmPopup.open() } }
                Item { Layout.fillWidth: true }
                MD3.Button { text: "手动填写"; type: "outlined"; onClicked: { authPopup.close(); settingsPopup.open() } }
            }
        }
        padding: 26
    }

    QQC.Popup {
        id: settingsPopup
        anchors.centerIn: parent
        width: 700
        modal: true
        closePolicy: QQC.Popup.CloseOnEscape
        onOpened: {
            tokenSetting.text = Backend.tasktoken
            wsSetting.text = Backend.tencentKey
            jsSetting.text = Backend.tencentJsKey
        }
        background: MD3.Card { type: "elevated" }
        contentItem: ColumnLayout {
            spacing: 16
            SectionTitle { text: "设置"; font.pixelSize: 22 }
            MD3.TextField { id: tokenSetting; Layout.fillWidth: true; label: "tasktoken"; type: "outlined"; isPassword: true }
            MD3.TextField { id: wsSetting; Layout.fillWidth: true; label: "腾讯 WebService Key"; type: "outlined"; isPassword: true }
            MD3.TextField { id: jsSetting; Layout.fillWidth: true; label: "腾讯 JavaScript GL Key"; type: "outlined"; isPassword: true }
            BodyText { text: Backend.defaultKeyNotice + "\n配置位置：" + Backend.settingsPath; Layout.fillWidth: true }
            RowLayout {
                Layout.fillWidth: true
                MD3.Button { text: "重新抓取"; type: "text"; onClicked: { settingsPopup.close(); window.pageIndex = 5; captureConfirmPopup.open() } }
                Item { Layout.fillWidth: true }
                MD3.Button { text: "取消"; type: "text"; onClicked: settingsPopup.close() }
                MD3.Button { text: "保存"; type: "filled"; onClicked: { Backend.saveSettings(tokenSetting.text, wsSetting.text, jsSetting.text); settingsPopup.close() } }
            }
        }
        padding: 28
    }

    QQC.Popup {
        id: captureConfirmPopup
        anchors.centerIn: parent
        width: 560
        modal: true
        background: MD3.Card { type: "elevated" }
        contentItem: ColumnLayout {
            spacing: 16
            SectionTitle { text: "开始自动抓取？"; font.pixelSize: 22 }
            BodyText { text: "程序会先验证根证书，再临时启用本机代理。成功、停止、超时或退出时会恢复原有代理。看到页面提示后再打开微信小程序。"; Layout.fillWidth: true }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                MD3.Button { text: "取消"; type: "text"; onClicked: captureConfirmPopup.close() }
                MD3.Button { text: "继续"; type: "filled"; onClicked: { captureConfirmPopup.close(); window.pageIndex = 5; Backend.startCapture() } }
            }
        }
        padding: 26
    }

    QQC.Popup {
        id: certificateInstallPopup
        anchors.centerIn: parent
        width: 560
        modal: true
        background: MD3.Card { type: "elevated" }
        contentItem: ColumnLayout {
            spacing: 16
            SectionTitle { text: "安装 mitmproxy 根证书？"; font.pixelSize: 22 }
            BodyText { text: "程序会生成专用根证书并添加到 Windows 信任存储；此操作不会启用系统代理。"; Layout.fillWidth: true }
            RowLayout { Layout.fillWidth: true; Item { Layout.fillWidth: true }
                MD3.Button { text: "取消"; type: "text"; onClicked: certificateInstallPopup.close() }
                MD3.Button { text: "安装并验证"; type: "filled"; onClicked: { certificateInstallPopup.close(); Backend.installCertificate() } }
            }
        }
        padding: 26
    }

    QQC.Popup {
        id: certificateRepairPopup
        anchors.centerIn: parent
        width: 590
        modal: true
        background: MD3.Card { type: "elevated" }
        contentItem: ColumnLayout {
            spacing: 16
            SectionTitle { text: "修复 mitmproxy 证书？"; font.pixelSize: 22 }
            BodyText { text: "程序会先备份现有 CA 文件，再重新生成、安装并验证新证书；失败时自动恢复原文件。此操作不会启用系统代理。"; Layout.fillWidth: true }
            RowLayout { Layout.fillWidth: true; Item { Layout.fillWidth: true }
                MD3.Button { text: "取消"; type: "text"; onClicked: certificateRepairPopup.close() }
                MD3.Button { text: "开始修复"; type: "filled"; onClicked: { certificateRepairPopup.close(); Backend.repairCertificate() } }
            }
        }
        padding: 26
    }

    QQC.Popup {
        id: runConfirmPopup
        anchors.centerIn: parent
        width: 580
        modal: true
        background: MD3.Card { type: "elevated" }
        contentItem: ColumnLayout {
            spacing: 16
            SectionTitle { text: "确认运行"; font.pixelSize: 22 }
            BodyText { text: Backend.routeInfo + "\n\n确认后将创建跑步会话并按实际等待时间执行。"; Layout.fillWidth: true }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                MD3.Button { text: "返回调整"; type: "text"; onClicked: runConfirmPopup.close() }
                MD3.Button { text: "确认运行"; type: "filled"; onClicked: { runConfirmPopup.close(); window.pageIndex = 4; Backend.executeRun() } }
            }
        }
        padding: 26
    }

    QQC.Popup {
        id: updatePopup
        anchors.centerIn: parent
        width: 620
        modal: true
        background: MD3.Card { type: "elevated" }
        contentItem: ColumnLayout {
            spacing: 16
            SectionTitle { id: updateTitle; font.pixelSize: 22 }
            BodyText { id: updateBody; Layout.fillWidth: true; maximumLineCount: 12; elide: Text.ElideRight }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                MD3.Button { text: "稍后"; type: "text"; onClicked: updatePopup.close() }
                MD3.Button { text: "前往 GitHub 更新"; type: "filled"; onClicked: { Backend.openUrl(pendingUpdate.url || ""); updatePopup.close() } }
            }
        }
        padding: 26
    }
}
