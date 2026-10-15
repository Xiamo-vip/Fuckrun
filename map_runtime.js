/* SDK loading, route painting and key diagnostics are separate stages. */
(function () {
  'use strict';
  const config = window.GHOSTRUNNER_PLAN || {};
  const status = document.getElementById('status');
  let timer;
  function show(message, state) {
    status.textContent = message;
    window.GHOSTRUNNER_MAP_STATE = {state: state, message: message};
  }
  function point(value) {
    if (!Array.isArray(value) || value.length < 2 || !Number.isFinite(value[0]) ||
        !Number.isFinite(value[1]) || Math.abs(value[0]) > 90 || Math.abs(value[1]) > 180) {
      throw new Error('路线包含无效经纬度');
    }
    return new TMap.LatLng(value[0], value[1]);
  }
  function initialize() {
    clearTimeout(timer);
    if (!window.TMap || !TMap.Map) {
      show('SDK 已下载，但未提供 TMap。请检查 JavaScript GL Key 是否开通；WebService Key 不一定支持网页地图。', 'sdk-error');
      return;
    }
    let map;
    try {
      const values = config.points || [];
      const cps = config.checkpoints || [];
      const center = values[0] || (cps[0] && [Number(cps[0].latitude), Number(cps[0].longitude)]);
      if (!center) { show('请先获取打卡点并规划路线。', 'empty'); return; }
      const path = values.map(point);
      map = new TMap.Map('map', {center: point(center), zoom: 16});
      window.ghostRunnerMap = map;
      if (path.length > 1) {
        new TMap.MultiPolyline({map: map,
          styles: {route: new TMap.PolylineStyle({color: '#2878ed', width: 6})},
          geometries: [{id: 'route', styleId: 'route', paths: path}]});
        // Tencent requires southwest and northeast LatLng arguments.
        // An empty constructor used by the old version threw during rendering.
        const bounds = new TMap.LatLngBounds(path[0], path[0]);
        path.slice(1).forEach(p => bounds.extend(p));
        map.fitBounds(bounds, {padding: 55});
      }
      if (cps.length && TMap.MultiMarker) {
        new TMap.MultiMarker({map: map,
          styles: {checkpoint: new TMap.MarkerStyle({width: 25, height: 35,
            anchor: {x: 12, y: 35}, src: 'https://mapapi.qq.com/web/lbs/javascriptGL/demo/img/markerDefault.png'})},
          geometries: cps.map((cp, i) => ({
          id: String(cp.id === undefined ? i : cp.id),
          styleId: 'checkpoint',
          position: point([Number(cp.latitude), Number(cp.longitude)]),
          content: String(i + 1), properties: {title: '打卡点 ' + (i + 1)}
        }))});
      }
      show('路线已绘制 · ' + cps.length + ' 个打卡点 · ' + path.length + ' 个路线点', 'ready');
      map.on('error', e => show('地图服务错误：' + String((e && (e.message || e.code)) || '请检查 Key 的 JS API 权限与 127.0.0.1 域名设置'), 'service-error'));
    } catch (error) {
      show('地图绘制错误：' + String(error.message || error) + '。这不是统一的 Key 鉴权错误。', 'render-error');
    }
  }
  window.ghostRunnerInitialize = initialize;
  if (!config.key || !config.key.trim()) {
    show('请在设置中填写腾讯 JavaScript GL Key；步行规划所用 WebService Key 与网页地图权限分别配置。', 'missing-key');
    return;
  }
  if (window.TMap) { initialize(); return; }
  const sdk = document.createElement('script');
  sdk.charset = 'utf-8';
  sdk.async = true;
  sdk.src = 'https://map.qq.com/api/gljs?v=1.exp&key=' + encodeURIComponent(config.key);
  sdk.onload = initialize;
  sdk.onerror = () => {
    clearTimeout(timer);
    show('腾讯地图 SDK 下载失败。请检查 map.qq.com 网络连接，然后点击“重载地图”。', 'network-error');
  };
  function loadSDK() {
    timer = setTimeout(() => show('腾讯地图 SDK 加载超时，请检查网络并重载地图。', 'timeout'), 20000);
    document.head.appendChild(sdk);
  }
  // Local HTML must finish loading before a slow SDK download begins, so that
  // WebView2 can attach to Tkinter and show timeout/network diagnostics in-place.
  if (document.readyState === 'loading' && window.addEventListener) {
    window.addEventListener('load', loadSDK, {once: true});
  } else {
    loadSDK();
  }
})();
