import unittest
from unittest.mock import Mock
import requests
from akshare_request_policy import PacedRequests

class Clock:
    def __init__(self):self.now=100.;self.sleeps=[]
    def __call__(self):return self.now
    def sleep(self,value):self.sleeps.append(value);self.now+=value
class PolicyTests(unittest.TestCase):
    def make(self,side_effect):
        clock=Clock()
        transport=Mock(side_effect=side_effect)
        policy=PacedRequests(transport,clock=clock,sleep=clock.sleep,jitter=lambda:0)
        return clock,transport,policy
    def response(self,status):
        r=Mock(status_code=status,headers={})
        if status==429:r.raise_for_status.side_effect=requests.HTTPError("429")
        return r
    def test_eastmoney_uses_slower_gap(self):
        c,t,p=self.make([self.response(200),self.response(200)])
        for _ in range(2):p.request(None,"GET","https://push2delay.eastmoney.com")
        self.assertEqual(c.sleeps,[8.])
    def test_eastmoney_gateway_has_longer_backoff(self):
        c,t,p=self.make([self.response(502),self.response(200)])
        p.request(None,"GET","https://push2delay.eastmoney.com")
        self.assertEqual(c.sleeps,[30.])
    def test_two_transports_share_one_gate(self):
        c,t,p=self.make([self.response(200)])
        other=Mock(return_value=self.response(200))
        p.request(None,"GET","https://host.test")
        p.request(None,"GET","https://other.test",_transport=other)
        self.assertEqual(c.sleeps,[4.])
        self.assertNotIn("_transport",other.call_args.kwargs)
    def test_pagination_requests_are_spaced(self):
        c,t,p=self.make([self.response(200)]*3)
        for _ in range(3):p.request(None,"GET","https://host.test/pages")
        self.assertEqual(c.sleeps,[4.,4.])
        self.assertEqual(t.call_count,3)
    def test_gateway_retries_only_once_after_delay(self):
        bad=self.response(502)
        c,t,p=self.make([bad,self.response(200)])
        self.assertEqual(p.request(None,"GET","https://host.test").status_code,200)
        self.assertEqual(c.sleeps,[15.])
        bad.close.assert_called_once()
    def test_persistent_gateway_failure_cools_host(self):
        c,t,p=self.make([self.response(502),self.response(502)])
        self.assertEqual(p.request(None,"GET","https://host.test").status_code,502)
        with self.assertRaises(requests.exceptions.RetryError):p.request(None,"GET","https://host.test")
        self.assertEqual(t.call_count,2)
    def test_rate_limit_stops_same_host(self):
        c,t,p=self.make([self.response(429)])
        with self.assertRaises(requests.HTTPError):p.request(None,"GET","https://host.test")
        with self.assertRaises(requests.exceptions.RetryError):p.request(None,"GET","https://host.test")
        self.assertEqual(t.call_count,1)
    def test_non_get_is_not_retried(self):
        c,t,p=self.make([self.response(502)])
        self.assertEqual(p.request(None,"POST","https://host.test").status_code,502)
        self.assertEqual(t.call_count,1)
    def test_timeout_has_one_delayed_retry(self):
        c,t,p=self.make([requests.Timeout(),self.response(200)])
        self.assertEqual(p.request(None,"GET","https://host.test").status_code,200)
        self.assertEqual(c.sleeps,[15.])
if __name__=="__main__":unittest.main()
