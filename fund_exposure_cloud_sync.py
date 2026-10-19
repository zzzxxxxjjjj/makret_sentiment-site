"""Publish one validated fund snapshot independently of Wind and RQData."""
from __future__ import annotations

import base64
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

from rqdata_fund_exposure_refresh import validate_snapshot

REPOSITORY = 'zzzxxxxjjjj/makret_sentiment-site'
FILENAME = 'rqdata-fund-exposure.json'
PUBLIC_URL = 'https://makret-sentiment-site.pages.dev/' + FILENAME


def same_data(left, right):
    return ({k: v for k, v in left.items() if k != 'updatedAt'} ==
            {k: v for k, v in right.items() if k != 'updatedAt'})


class GitHub:
    def __init__(self, token):
        if not token:
            raise ValueError('GitHub publishing authentication is missing')
        self.token = token

    def request(self, method, path, data=None):
        req = urllib.request.Request('https://api.github.com/repos/' + REPOSITORY + path,
            data=json.dumps(data).encode('utf-8') if data is not None else None, method=method,
            headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json', 'User-Agent': 'FundExposureCloudSync/1.0'})
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)


def publish(github, snapshot):
    validate_snapshot(snapshot)
    content = json.dumps(snapshot, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    for attempt in range(3):
        head = github.request('GET', '/git/ref/heads/main')['object']['sha']
        remote = github.request('GET', '/contents/' + FILENAME + '?ref=' + head)
        previous = json.loads(base64.b64decode(remote['content']))
        validate_snapshot(previous)
        if previous['asOf'] > snapshot['asOf']:
            raise ValueError('Remote fund data is newer; refusing a weekly data rollback')
        if same_data(previous, snapshot):
            return {'changed': False, 'commit': head}
        base = github.request('GET', '/git/commits/' + head)['tree']['sha']
        blob = github.request('POST', '/git/blobs', {'content': content, 'encoding': 'utf-8'})['sha']
        tree = github.request('POST', '/git/trees', {'base_tree': base, 'tree': [
            {'path': FILENAME, 'mode': '100644', 'type': 'blob', 'sha': blob}]})['sha']
        commit = github.request('POST', '/git/commits', {
            'message': 'Update weekly fund exposure ' + snapshot['asOf'],
            'tree': tree, 'parents': [head]})['sha']
        try:
            # A moved branch rejects this sibling commit; never force an update.
            github.request('PATCH', '/git/refs/heads/main', {'sha': commit, 'force': False})
            return {'changed': True, 'commit': commit}
        except urllib.error.HTTPError as exc:
            if exc.code not in (409, 422) or attempt == 2:
                raise
    raise RuntimeError('Concurrent updates prevented publication')


def verify_public(snapshot, attempts=20):
    # A dedicated User-Agent and unique query also avoid intermediary stale caches.
    for attempt in range(attempts):
        request = urllib.request.Request(PUBLIC_URL + '?verify=' + str(time.time_ns()),
            headers={'Cache-Control': 'no-cache', 'User-Agent': 'MarketSentimentPublicationCheck/1.0'})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                actual = json.load(response)
            validate_snapshot(actual)
            if same_data(actual, snapshot):
                return
            if actual['asOf'] > snapshot['asOf']:
                return  # A concurrent job already published a newer validated week.
        except (OSError, ValueError):
            pass
        if attempt + 1 < attempts:
            time.sleep(10)
    raise RuntimeError('Cloudflare did not serve the validated fund snapshot before verification timed out')


def main():
    snapshot = json.loads(Path(__file__).with_name(FILENAME).read_text(encoding='utf-8'))
    result = publish(GitHub(os.environ.get('GITHUB_TOKEN', '')), snapshot)
    verify_public(snapshot)
    report = {'checkedAt': datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),
              'sourceDate': snapshot['asOf'], 'industries': len(snapshot['industries']),
              'publicVerified': True, **result}
    print(json.dumps(report, ensure_ascii=True))
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as output:
            output.write('### Weekly fund exposure\n\n' +
                         f"Source date: {snapshot['asOf']}; 31 industries validated; public deployment verified.\n")


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as exc:
        raise SystemExit('Fund publication failed: HTTP ' + str(exc.code))
