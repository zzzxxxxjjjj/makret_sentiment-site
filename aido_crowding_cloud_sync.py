"""Publish only validated style crowding, using a non-forced atomic Git ref update."""
import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from aido_style_crowding_refresh import validate_snapshot
from fund_exposure_cloud_sync import GitHub, same_data

FILENAME = 'style-crowding.json'


def publish(github, snapshot):
    validate_snapshot(snapshot)
    for attempt in range(3):
        head = github.request('GET', '/git/ref/heads/main')['object']['sha']
        try:
            raw = github.request('GET', '/contents/'+FILENAME+'?ref='+head)
            previous = json.loads(base64.b64decode(raw['content']))
        except urllib.error.HTTPError as exc:
            if exc.code != 404: raise
            previous = {}
        if previous.get('asOf', '') > snapshot['asOf']:
            raise ValueError('Refusing crowding rollback')
        if same_data(previous, snapshot): return {'changed': False, 'commit': head}
        tree = github.request('GET', '/git/commits/'+head)['tree']['sha']
        blob = github.request('POST', '/git/blobs', {'content': json.dumps(snapshot, ensure_ascii=False, allow_nan=False), 'encoding':'utf-8'})['sha']
        tree = github.request('POST', '/git/trees', {'base_tree':tree, 'tree':[{'path':FILENAME,'mode':'100644','type':'blob','sha':blob}]})['sha']
        commit = github.request('POST', '/git/commits', {'message':'Update style crowding '+snapshot['asOf'],'tree':tree,'parents':[head]})['sha']
        try:
            github.request('PATCH', '/git/refs/heads/main', {'sha':commit,'force':False})
            return {'changed':True,'commit':commit}
        except urllib.error.HTTPError as exc:
            if exc.code not in (409,422) or attempt == 2: raise


def verify_public(snapshot, attempts=20):
    for attempt in range(attempts):
        try:
            req = urllib.request.Request('https://makret-sentiment-site.pages.dev/'+FILENAME+'?verify='+str(time.time_ns()),headers={'Cache-Control':'no-cache','User-Agent':'MarketSentimentPublicationCheck/1.0'})
            with urllib.request.urlopen(req, timeout=15) as response: actual = json.load(response)
            validate_snapshot(actual)
            if same_data(actual,snapshot) or actual['asOf'] > snapshot['asOf']: return
        except (OSError,ValueError): pass
        if attempt+1 < attempts: time.sleep(10)
    raise RuntimeError('Public crowding verification timed out')


if __name__ == '__main__':
    snapshot = json.loads(Path(__file__).with_name(FILENAME).read_text(encoding='utf-8'))
    result = publish(GitHub(os.environ.get('GITHUB_TOKEN','')),snapshot)
    verify_public(snapshot)
    print(json.dumps({'asOf':snapshot['asOf'],'publicVerified':True,**result},ensure_ascii=True))
