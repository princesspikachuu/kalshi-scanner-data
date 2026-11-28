"""One socket reader independent of REST I/O, with bounded lossless buffering."""
from collections import deque
import threading,time
from websockets.exceptions import ConnectionClosed,ConnectionClosedOK
from .exchange import ExchangeFailure

class BufferedSocket:
    def __init__(self,connection,*,max_bytes=16*1024*1024,max_messages=16384):
        self.connection=connection;self.max_bytes=max_bytes;self.max_messages=max_messages
        self.queue=deque();self.bytes=0;self.error=None;self.stopped=False;self.received_at=None
        self.received_count=0;self.consumed_count=0;self.peak_messages=0;self.peak_bytes=0;self.close_code=None
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
                    self.queue.append((message,received,size));self.bytes+=size
                    self.received_count+=1;self.peak_messages=max(self.peak_messages,len(self.queue));self.peak_bytes=max(self.peak_bytes,self.bytes)
                    self.condition.notify_all()
        except ConnectionClosed as error:
            # A normal exchange close is a transport lifecycle event, not a
            # worker crash. Deliver every already received, sequenced message
            # before asking the owner loop to restore its fresh subscriptions.
            with self.condition:
                if not self.stopped:
                    self.close_code=getattr(getattr(error,'rcvd',None),'code',None)
                    self.error=ExchangeFailure('stream_closed' if isinstance(error,ConnectionClosedOK) else 'stream_connection_lost')
                self.condition.notify_all()
        except Exception as error:
            # Overflow or an unknown reader failure cannot preserve a complete
            # event sequence. Fail closed instead of using a truncated order book.
            with self.condition:
                if not self.stopped:self.error=error
                self.queue.clear();self.bytes=0;self.condition.notify_all()
    def recv(self,timeout=None):
        deadline=None if timeout is None else time.monotonic()+timeout
        with self.condition:
            while True:
                if self.error and not (isinstance(self.error,ExchangeFailure) and self.error.code in ('stream_closed','stream_connection_lost')):raise self.error
                if self.stopped:raise ExchangeFailure('connection')
                if self.queue:
                    message,self.received_at,size=self.queue.popleft();self.bytes-=size;self.consumed_count+=1;return message
                if self.error:raise self.error
                remaining=None if deadline is None else deadline-time.monotonic()
                if remaining is not None and remaining<=0:raise TimeoutError()
                self.condition.wait(remaining)
    def stats(self):
        with self.condition:return dict(messages=len(self.queue),bytes=self.bytes,reader_alive=self.thread.is_alive(),
            received=self.received_count,consumed=self.consumed_count,peak_messages=self.peak_messages,peak_bytes=self.peak_bytes,
            oldest_age_seconds=round(max(0,time.time()-self.queue[0][1]),3) if self.queue else 0,
            close_code=self.close_code)
    def send(self,*args,**kwargs):
        try:return self.connection.send(*args,**kwargs)
        except ConnectionClosedOK:raise ExchangeFailure('stream_closed') from None
        except ConnectionClosed:raise ExchangeFailure('stream_connection_lost') from None
    def ping(self,*args,**kwargs):
        try:return self.connection.ping(*args,**kwargs)
        except ConnectionClosedOK:raise ExchangeFailure('stream_closed') from None
        except ConnectionClosed:raise ExchangeFailure('stream_connection_lost') from None
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
