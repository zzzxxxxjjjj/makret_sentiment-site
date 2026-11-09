"""Publish only the timing snapshot/status, never workbooks or raw licensed inputs."""
import json
from pathlib import Path
import os
import publish_daily_snapshot as publisher

ROOT = Path(__file__).resolve().parent


def main():
    status = json.loads((ROOT/'position-update-status.json').read_text(encoding='utf-8'))
    publisher.FILES = ('position-update-status.json',)
    if status.get('ok') is True:
        snapshot = json.loads((ROOT/'position-advice.json').read_text(encoding='utf-8'))
        if snapshot.get('asOf') != status.get('targetDate') or snapshot.get('mode') != status.get('modelVersion'):
            raise ValueError('Timing date/version mismatch')
        publisher.FILES += ('position-advice.json',)
    # Existing publisher creates a tree on the latest main; no unrelated files.
    result = publisher.GitHub(os.environ.get('GITHUB_TOKEN', '')).publish(ROOT, status.get('targetDate') or 'timing-status')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
