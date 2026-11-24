"""Conservative request pacing for AKShare collectors, including internal pagination."""
import random
import threading
import time
from urllib.parse import urlsplit
import requests

class PacedRequests:
    def __init__(self, transport, interval=4.0, clock=time.monotonic, sleep=time.sleep, jitter=None):
        self.transport=transport
        self.interval=interval
        self.clock=clock
        self.sleep=sleep
        self.jitter=jitter or (lambda:random.uniform(0,.5))
        self.lock=threading.Lock()
        self.next_request=0.
        self.blocked={}
        self.calls=0
        self.retries=0

    def request(self, session, method, url, _transport=None, **kwargs):
        host=urlsplit(str(url)).hostname or "unknown"
        method=method.upper()
        eastmoney=host=="eastmoney.com" or host.endswith(".eastmoney.com")
        interval=max(self.interval,8.) if eastmoney else self.interval
        retry_delay=30. if eastmoney else 15.
        # Hold through the response: worker pools cannot burst concurrent pages.
        with self.lock:
            for attempt in range(2 if method=="GET" else 1):
                if self.blocked.get(host,0)>self.clock():
                    raise requests.exceptions.RetryError("AKShare server cooling down: "+host)
                delay=self.next_request-self.clock()
                if delay>0:self.sleep(delay)
                kwargs.setdefault("timeout",(10,30))
                try:
                    self.calls+=1
                    response=(_transport or self.transport)(session,method,url,**kwargs)
                except (requests.exceptions.Timeout,requests.exceptions.ConnectionError):
                    self.next_request=self.clock()+interval+self.jitter()
                    if method!="GET" or attempt:raise
                    self.retries+=1
                    self.next_request=self.clock()+retry_delay+self.jitter()
                    print("AKShare transient network failure; delayed retry: "+host,flush=True)
                    continue
                self.next_request=self.clock()+interval+self.jitter()
                status=response.status_code
                if status==429:
                    try:cooldown=max(300,min(float(response.headers.get("Retry-After",300)),3600))
                    except (ValueError,TypeError):cooldown=300
                    self.blocked[host]=self.clock()+cooldown
                    response.raise_for_status()
                    raise requests.exceptions.RetryError("AKShare HTTP 429: "+host)
                if status in (502,503,504) and method=="GET":
                    if attempt==0:
                        response.close()
                        self.retries+=1
                        self.next_request=self.clock()+retry_delay+self.jitter()
                        print("AKShare HTTP "+str(status)+"; delayed retry: "+host,flush=True)
                        continue
                    self.blocked[host]=self.clock()+300
                return response

def install():
    current=requests.sessions.Session.request
    if getattr(current,"_akshare_paced",False):return
    limiter=PacedRequests(current)
    def paced(session,method,url,**kwargs):
        return limiter.request(session,method,url,**kwargs)
    paced._akshare_paced=True
    paced.limiter=limiter
    requests.sessions.Session.request=paced
    # Some AKShare sources use curl_cffi for browser-compatible TLS.
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        curl_requests=None
    if curl_requests is not None:
        original_curl=curl_requests.Session.request
        def paced_curl(session,method,url,**kwargs):
            return limiter.request(session,method,url,_transport=original_curl,**kwargs)
        paced_curl._akshare_paced=True
        curl_requests.Session.request=paced_curl
    print("AKShare request policy: serial requests, 4-4.5s gap (Eastmoney 8-8.5s), one delayed GET retry",flush=True)
