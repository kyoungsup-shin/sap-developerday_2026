"""Real ASGI HTTP must transmit SSE before the Agent finishes its work."""
import asyncio
import socket
import threading
import time
from unittest.mock import patch

import httpx
import uvicorn
from django.test import SimpleTestCase
from config.asgi import application


class SSETransportTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.socket=socket.socket(); cls.socket.bind(('127.0.0.1',0))
        cls.base_url='http://127.0.0.1:'+str(cls.socket.getsockname()[1])
        cls.server=uvicorn.Server(uvicorn.Config(application,log_level='critical',lifespan='off'))
        cls.thread=threading.Thread(target=lambda:cls.server.run(sockets=[cls.socket]),daemon=True);cls.thread.start()
        deadline=time.monotonic()+5
        while not cls.server.started and time.monotonic()<deadline:threading.Event().wait(.01)
        if not cls.server.started:raise RuntimeError('ASGI test server did not start')

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit=True;cls.thread.join(5);cls.socket.close();super().tearDownClass()

    def test_session_and_updates_arrive_before_review_finishes(self):
        gate=threading.Event(); packets=[]
        def runtime(**kwargs):
            yield {'type':'grounding_started','query':'Focused SOP query'}
            gate.wait(3)
            yield {'type':'complete','result':{'summary':'Review finished','termination':{'state':'completed'}}}
        async def collect():
            async with httpx.AsyncClient(timeout=2) as client:
                async with client.stream('POST',self.base_url+'/api/chat/stream',json={'message':'Review documented evidence','session_id':'asgi-transport-test'}) as response:
                    self.assertEqual(response.status_code,200)
                    async for line in response.aiter_lines():
                        packets.append(line)
                        if line=='event: grounding_started':
                            self.assertFalse(gate.is_set())
                            gate.set()
        with patch('gateway.views.run_handoff_stream',side_effect=runtime):
            try:asyncio.run(collect())
            finally:gate.set()
        self.assertIn('event: session',packets);self.assertIn('event: complete',packets)
        self.assertLess(packets.index('event: session'),packets.index('event: grounding_started'))
