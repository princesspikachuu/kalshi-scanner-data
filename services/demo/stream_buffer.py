"""One socket reader independent of REST I/O, with bounded lossless buffering."""
from collections import deque
import threading,time
from .exchange import ExchangeFailure

class BufferedSocket:
    def __init__(self,connection,*,max_bytes=8*1024*1024,max_messages=4096):
        self.connection=connection;self.max_bytes=max_bytes;self.max_messages=max_messages
        self.queue=deque();self.bytes=0;self.error=None;self.stopped=False;self.received_at=None
        self.condition=threading.Condition()
        self.thread=threading.Thread(target=self._read,name='demo-price-receiver',daemon=True);self.thread.start()
    def _read(self):
        try:
            while True:
                with self.condition:
                    if self.stopped:return
                try:message=self.connection.recv(timeout=1)
                except TimeoutError:continue
                received=time.time();size=len(message.encode('utf-8')) if isinstance(message,str) else len(message)
                with self.condition:
                    if self.stopped:return
                    if len(self.queue)>=self.max_messages or self.bytes+size>self.max_bytes:raise ExchangeFailure('stream_backlog')
                    self.queue.append((message,received,size));self.bytes+=size;self.condition.notify_all()
        except Exception as error:
            with self.condition:
                if not self.stopped:self.error=error
                self.queue.clear();self.bytes=0;self.condition.notify_all()
    def recv(self,timeout=None):
        deadline=None if timeout is None else time.monotonic()+timeout
        with self.condition:
            while True:
                if self.error:raise self.error
                if self.stopped:raise ExchangeFailure('connection')
                if self.queue:
                    message,self.received_at,size=self.queue.popleft();self.bytes-=size;return message
                remaining=None if deadline is None else deadline-time.monotonic()
                if remaining is not None and remaining<=0:raise TimeoutError()
                self.condition.wait(remaining)
    def stats(self):
        with self.condition:return dict(messages=len(self.queue),bytes=self.bytes,reader_alive=self.thread.is_alive())
    def send(self,*args,**kwargs):return self.connection.send(*args,**kwargs)
    def ping(self,*args,**kwargs):return self.connection.ping(*args,**kwargs)
    def close(self):
        with self.condition:self.stopped=True;self.queue.clear();self.bytes=0;self.condition.notify_all()
        try:self.connection.close()
        finally:
            if self.thread is not threading.current_thread():self.thread.join(timeout=3)

def close_details(error):
    """Fixed diagnostics only; never log raw server reasons or payloads."""
    sent=getattr(error,'sent',None);received=getattr(error,'rcvd',None)
    reason=str(getattr(sent,'reason','')).lower()
    return dict(sent_code=getattr(sent,'code',None),received_code=getattr(received,'code',None),
        close_cause='keepalive_timeout' if 'ping timeout' in reason else 'connection_closed' if sent or received else None)
