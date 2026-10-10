"""Loopback-only deterministic OpenAI protocol fixture; no external connections."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import time

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        answer='Local deployment probe completed.'
        value={'id':'probe','created':int(time.time()),'model':body['model']}
        self.send_response(200)
        if body.get('stream'):
            self.send_header('Content-Type','text/event-stream')
            self.send_header('Connection','close')
            self.end_headers()
            for delta,finish in [({'role':'assistant','content':answer},None),({},'stop')]:
                chunk={**value,'object':'chat.completion.chunk','choices':[{'index':0,'delta':delta,'finish_reason':finish}]}
                self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
        else:
            self.send_header('Content-Type','application/json')
            self.end_headers()
            self.wfile.write(json.dumps({**value,'object':'chat.completion','choices':[{'index':0,
                'message':{'role':'assistant','content':answer},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':5,'completion_tokens':5,'total_tokens':10}}).encode())
    def log_message(self,*args):
        pass
ThreadingHTTPServer(('127.0.0.1',18085),Handler).serve_forever()
