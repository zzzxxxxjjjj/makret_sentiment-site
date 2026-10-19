import base64
import copy
import json
import unittest
import urllib.error

from fund_exposure_cloud_sync import publish
from test_fund_exposure_refresh import snapshot


class FakeGitHub:
    def __init__(self, data, conflict=False):
        self.data = data
        self.conflict = conflict
        self.calls = []

    def request(self, method, path, data=None):
        self.calls.append((method, path, data))
        if path == '/git/ref/heads/main':
            return {'object': {'sha': 'head-' + str(len(self.calls))}}
        if path.startswith('/contents/'):
            return {'content': base64.b64encode(json.dumps(self.data).encode()).decode()}
        if path.startswith('/git/commits/'):
            return {'tree': {'sha': 'base'}}
        if path == '/git/refs/heads/main':
            if self.conflict:
                self.conflict = False
                raise urllib.error.HTTPError('https://api.github.com', 422, 'branch moved', {}, None)
            return {}
        return {'sha': 'new-' + path.rsplit('/', 1)[-1]}


class CloudFundTests(unittest.TestCase):
    def test_unchanged_data_never_creates_a_commit(self):
        source = snapshot()
        remote = copy.deepcopy(source)
        remote['updatedAt'] = 'different check time'
        github = FakeGitHub(remote)
        self.assertFalse(publish(github, source)['changed'])
        self.assertTrue(all(method == 'GET' for method, _, _ in github.calls))

    def test_concurrent_branch_move_rebuilds_only_the_fund_file(self):
        source = snapshot()
        remote = copy.deepcopy(source)
        remote['industries'][0]['name'] = 'old name'
        github = FakeGitHub(remote, conflict=True)
        self.assertTrue(publish(github, source)['changed'])
        trees = [data for _, path, data in github.calls if path == '/git/trees']
        self.assertEqual(len(trees), 2)
        self.assertTrue(all(t['tree'][0]['path'] == 'rqdata-fund-exposure.json' and len(t['tree']) == 1 for t in trees))
        patches = [data for method, _, data in github.calls if method == 'PATCH']
        self.assertTrue(all(data['force'] is False for data in patches))

    def test_newer_remote_week_is_never_overwritten(self):
        source = snapshot()
        remote = copy.deepcopy(source)
        remote['asOf'] = '2026-10-23'
        for item in remote['industries']:
            item['tradeDate'] = remote['asOf']
        github = FakeGitHub(remote)
        with self.assertRaises(ValueError):
            publish(github, source)
        self.assertTrue(all(method == 'GET' for method, _, _ in github.calls))


if __name__ == '__main__':
    unittest.main()
