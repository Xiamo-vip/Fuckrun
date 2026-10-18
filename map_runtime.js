/* SDK loading, route painting and key diagnostics are separate stages. */
(function () {
  'use strict';
  /* QtWebEngine may provide null localStorage/sessionStorage when the page
     origin is a loopback HTTP server.  The Tencent Maps GL SDK calls
     localStorage.getItem() internally for its style registry; a null
     reference triggers "Cannot read properties of null (reading 'getItem')".
     Polyfill both stores with an in-memory Map so the SDK works normally. */
  (function patchStorage() {
    function memoryStorage() {
      var data = {};
      return {
        getItem: function (k) { return data.hasOwnProperty(k) ? data[k] : null; },
        setItem: function (k, v) { data[k] = String(v); },
        removeItem: function (k) { delete data[k]; },
        clear: function () { data = {}; },
        get length() { return Object.keys(data).length; },
        key: function (i) { var keys = Object.keys(data); return i < keys.length ? keys[i] : null; }
      };
    }
    try { if (!window.localStorage || typeof window.localStorage.getItem !== 'function') throw 0; } catch (_) {
      Object.defineProperty(window, 'localStorage', { value: memoryStorage(), configurable: true });
    }
    try { if (!window.sessionStorage || typeof window.sessionStorage.getItem !== 'function') throw 0; } catch (_) {
      Object.defineProperty(window, 'sessionStorage', { value: memoryStorage(), configurable: true });
    }
  })();
  const config = window.GHOSTRUNNER_PLAN || {};
  const status = document.getElementById('status');
  let timer;
  let map = null;
  let routeLayer = null;
  let markerLayer = null;
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
  function fitPath(values) {
    if (!values.length || !map) return;
    let minLat = values[0][0], maxLat = values[0][0];
    let minLng = values[0][1], maxLng = values[0][1];
    values.slice(1).forEach(value => {
      minLat = Math.min(minLat, value[0]); maxLat = Math.max(maxLat, value[0]);
      minLng = Math.min(minLng, value[1]); maxLng = Math.max(maxLng, value[1]);
    });
    const span = Math.max(maxLat - minLat, (maxLng - minLng) * Math.cos((minLat + maxLat) * Math.PI / 360));
    const zoom = span < 0.002 ? 17 : span < 0.005 ? 16 : span < 0.012 ? 15 : span < 0.025 ? 14 : 13;
    const center = new TMap.LatLng((minLat + maxLat) / 2, (minLng + maxLng) / 2);
    if (typeof map.setCenter === 'function') map.setCenter(center);
    if (typeof map.setZoom === 'function') map.setZoom(zoom);
  }
  function drawRoute(path) {
    const geometry = [{id: 'route', styleId: 'route', paths: path}];
    try {
      routeLayer = new TMap.MultiPolyline({map: map,
        styles: {route: new TMap.PolylineStyle({color: '#2878ed', width: 6,
          borderWidth: 2, borderColor: '#ffffff', lineCap: 'round'})},
        geometries: geometry});
    } catch (_) {
      // Stable API fallback used by Tencent's own assistant example.  It
      // avoids the affected SDK style registry where a null getItem occurred.
      routeLayer = new TMap.MultiPolyline({map: map,
        geometries: [{id: 'route', paths: path}]});
    }
  }
  function drawMarkers(cps) {
    if (!cps.length || !TMap.MultiMarker) return;
    const geometries = cps.map((cp, i) => ({
      id: String(cp.id === undefined ? i : cp.id),
      styleId: 'checkpoint',
      position: point([Number(cp.latitude), Number(cp.longitude)]),
      content: String(i + 1), properties: {title: '打卡点 ' + (i + 1)}
    }));
    try {
      markerLayer = new TMap.MultiMarker({map: map,
        styles: {checkpoint: new TMap.MarkerStyle({width: 25, height: 35,
          anchor: {x: 12, y: 35}, src: 'https://mapapi.qq.com/web/lbs/javascriptGL/demo/img/markerDefault.png'})},
        geometries: geometries});
    } catch (_) {
      markerLayer = new TMap.MultiMarker({map: map,
        geometries: geometries.map(item => ({id: item.id, position: item.position, properties: item.properties}))});
    }
  }
  function initialize() {
    clearTimeout(timer);
    if (!window.TMap || !TMap.Map) {
      show('SDK 已下载，但未提供 TMap。请检查 JavaScript GL Key 是否开通；WebService Key 不一定支持网页地图。', 'sdk-error');
      return;
    }
    try {
      const values = config.points || [];
      const cps = config.checkpoints || [];
      const center = values[0] || (cps[0] && [Number(cps[0].latitude), Number(cps[0].longitude)]);
      if (!center) { show('请先获取打卡点并规划路线。', 'empty'); return; }
      const path = values.map(point);
      map = new TMap.Map(document.getElementById('map'), {center: point(center), zoom: 16});
      window.ghostRunnerMap = map;
      if (path.length > 1) {
        drawRoute(path);
        fitPath(values);
      }
      drawMarkers(cps);
      show('路线已绘制 · ' + cps.length + ' 个打卡点 · ' + path.length + ' 个路线点', 'ready');
      map.on('error', e => show('地图服务错误：' + String((e && (e.message || e.code)) || '请检查 Key 的 JS API 权限与 127.0.0.1 域名设置'), 'service-error'));
    } catch (error) {
      show('地图绘制错误：' + String(error.message || error) + '。这不是统一的 Key 鉴权错误。', 'render-error');
    }
  }
  window.ghostRunnerInitialize = initialize;
  window.GHOSTRUNNER_FORCE_RESIZE = function () {
    if (!map) return false;
    try {
      if (typeof map.resize === 'function') map.resize();
      window.dispatchEvent(new Event('resize'));
      return true;
    } catch (_) { return false; }
  };
  // QtWebEngine resizes the page natively. This observer makes the Tencent
  // canvas consume the first complete compositor frame instead of keeping the
  // small initialization viewport that produced a clipped upper-left map.
  if (window.ResizeObserver) {
    const observer = new ResizeObserver(() => {
      requestAnimationFrame(() => window.GHOSTRUNNER_FORCE_RESIZE());
    });
    observer.observe(document.documentElement);
  }
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) requestAnimationFrame(() => window.GHOSTRUNNER_FORCE_RESIZE());
  });
  if (!config.key || !config.key.trim()) {
    show('请在设置中填写腾讯 JavaScript GL Key；步行规划所用 WebService Key 与网页地图权限分别配置。', 'missing-key');
    return;
  }
  if (window.TMap) { initialize(); return; }
  const sdk = document.createElement('script');
  sdk.charset = 'utf-8';
  sdk.async = true;
  sdk.src = 'https://map.qq.com/api/gljs?v=1&key=' + encodeURIComponent(config.key);
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
