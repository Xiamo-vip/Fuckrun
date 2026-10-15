const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const path = require('path');
const runtime = fs.readFileSync(path.join(__dirname,'..','map_runtime.js'),'utf8');

function fixture(config, sdk=true) {
  const status = {};
  const draws = {bounds:0, markers:0, timers:[]};
  const context = {console, clearTimeout(){},setTimeout(fn){draws.timers.push(fn);return 1;},
    document:{getElementById(){return status;},createElement(){return {};},
              head:{appendChild(script){draws.script=script;}}}};
  context.window=context;
  context.GHOSTRUNNER_PLAN=config;
  if(sdk) context.TMap={
    LatLng:class {constructor(lat,lng){this.lat=lat;this.lng=lng;}},
    Map:class {fitBounds(bounds){assert(bounds);draws.fit=true;} on(){}},
    PolylineStyle:class {},MultiPolyline:class {},MarkerStyle:class {},
    MultiMarker:class {constructor(opts){draws.markers=opts.geometries.length;}},
    LatLngBounds:class {constructor(sw,ne){if(!sw||!ne)throw Error('sw/ne required');draws.bounds++;}extend(){}}
  };
  vm.createContext(context);
  return {context,status,draws};
}
const config={key:'SYNTHETIC_KEY',points:[[25,118],[25.001,118.001]],checkpoints:[{id:1,latitude:25,longitude:118}]};
if(process.argv[2]==='--baseline') {
  const html=fs.readFileSync(process.argv[3],'utf8');
  const scripts=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).filter(s=>s.trim());
  const f=fixture(config);
  scripts.forEach(s=>vm.runInContext(s,f.context));
  assert(String(f.status.innerText).includes('地图加载失败'));
  console.log('BASELINE_BUG_REPRODUCED: empty LatLngBounds throws and displays generic Key/network error');
  process.exit(0);
}
let f=fixture(config);vm.runInContext(runtime,f.context);
assert.equal(f.context.GHOSTRUNNER_MAP_STATE.state,'ready');
assert.equal(f.draws.bounds,1);assert.equal(f.draws.markers,1);assert(f.draws.fit);
f=fixture({...config,points:[[NaN,118]]});vm.runInContext(runtime,f.context);
assert.equal(f.context.GHOSTRUNNER_MAP_STATE.state,'render-error');
assert(f.status.textContent.includes('无效经纬度'));
f=fixture({...config,key:''},false);vm.runInContext(runtime,f.context);
assert.equal(f.context.GHOSTRUNNER_MAP_STATE.state,'missing-key');
f=fixture(config,false);vm.runInContext(runtime,f.context);f.draws.script.onerror();
assert.equal(f.context.GHOSTRUNNER_MAP_STATE.state,'network-error');
f=fixture(config,false);vm.runInContext(runtime,f.context);f.draws.script.onload();
assert.equal(f.context.GHOSTRUNNER_MAP_STATE.state,'sdk-error');
f=fixture(config,false);vm.runInContext(runtime,f.context);f.draws.timers[0]();
assert.equal(f.context.GHOSTRUNNER_MAP_STATE.state,'timeout');
console.log('MAP_RUNTIME_OK: 6 cases; explicit bounds, checkpoint markers, distinct rendering/network/key/timeout errors');
