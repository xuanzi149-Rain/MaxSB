"""Loopback-only byte tunnel to the disposable Django server; no response fixtures."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import subprocess

FORWARD = '''import socket,sys
request=sys.stdin.buffer.read()
with socket.create_connection(('127.0.0.1',18084),timeout=120) as conn:
 conn.sendall(request)
 while True:
  data=conn.recv(65536)
  if not data: break
  sys.stdout.buffer.write(data)
  sys.stdout.buffer.flush()
'''

class Handler(BaseHTTPRequestHandler):
    def forward(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        headers = [(k, v) for k, v in self.headers.items() if k.lower() not in {'connection', 'host'}]
        request = (f'{self.command} {self.path} HTTP/1.0\r\nHost: 127.0.0.1:18084\r\nConnection: close\r\n' +
                   ''.join(f'{k}: {v}\r\n' for k, v in headers) + '\r\n').encode() + body
        with subprocess.Popen(['docker', 'exec', '-i', 'maxkb-task0', '/opt/py3/bin/python', '-u', '-c', FORWARD],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE) as proc:
            proc.stdin.write(request)
            proc.stdin.close()
            while data := os.read(proc.stdout.fileno(), 65536):
                self.connection.sendall(data)
        self.close_connection = True
    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = forward
    def log_message(self, *args):
        pass

if __name__ == '__main__':
    print('Task4 real HTTP tunnel: http://127.0.0.1:8084', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8084), Handler).serve_forever()
