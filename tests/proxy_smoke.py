"""Real local mitmproxy startup + synthetic HTTP flow; no system proxy/CA changes."""
import asyncio
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'.vendor'))
from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster
from mitmproxy import http
from proxy_capture import extract_token
from proxy_capture import certificate_info


async def main():
    with tempfile.TemporaryDirectory() as directory:
        captured=[]
        ready=asyncio.Event()
        class MockOrigin:
            def running(self): ready.set()
            def request(self,flow):
                token=extract_token(flow.request.host,flow.request.headers.get('Authorization'))
                if token:captured.append(token)
                flow.response=http.Response.make(200,b'LOCAL_FIXTURE_OK',{'Content-Type':'text/plain'})
        opts=Options(listen_host='127.0.0.1',listen_port=18081,confdir=directory,
                     allow_hosts=[r'^campusrun\.mzwu\.edu\.cn(?::\d+)?$'])
        master=DumpMaster(opts,with_termlog=False,with_dumper=False)
        master.addons.add(MockOrigin())
        task=asyncio.create_task(master.run())
        try:
            await asyncio.wait_for(ready.wait(),15)
            cert_path = Path(directory) / 'mitmproxy-ca-cert.cer'
            thumbprint, expires = certificate_info(cert_path)
            assert len(thumbprint) == 40, thumbprint
            assert expires is not None
            reader,writer=await asyncio.open_connection('127.0.0.1',18081)
            writer.write(b'GET http://campusrun.mzwu.edu.cn/api/fixture HTTP/1.1\r\nHost: campusrun.mzwu.edu.cn\r\nAuthorization: Bearer SYNTHETIC_TOKEN\r\nConnection: close\r\n\r\n')
            await writer.drain()
            output=await asyncio.wait_for(reader.read(),15)
            writer.close()
            await writer.wait_closed()
            assert b'LOCAL_FIXTURE_OK' in output,output
            assert captured==['SYNTHETIC_TOKEN'],captured
            print('PROXY_SMOKE_OK: local listener, PEM CA validation, exact-host Bearer extraction, mock response, clean shutdown')
        finally:
            master.shutdown()
            await task


if __name__=='__main__':
    asyncio.run(main())
