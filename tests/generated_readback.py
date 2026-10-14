"""Project finalized runtime Spools onto the external v4 read API for offline checks."""
import json
from datetime import datetime, timezone

from langfuse_synth_core import read


class Response:
    status_code = 200

    def __init__(self, rows):
        self.rows = rows

    def json(self):
        return {'data': self.rows, 'meta': {}}

    def raise_for_status(self):
        pass


def install_readback(monkeypatch, events, *, omit_day=None):
    observations, scores = [], []
    for event in events:
        if event.get('type') == 'score-create':
            body = event['body']
            kind, key = ('session', 'sessionId') if body.get('sessionId') else (
                ('observation', 'observationId') if body.get('observationId') else ('trace', 'traceId'))
            scores.append({**body, 'timestamp': event['timestamp'],
                           'subject': {'kind': kind, 'id': body[key], 'traceId': body.get('traceId')}})
            continue
        attrs = {attr['key']: attr['value'].get('stringValue') for attr in event.get('attributes', [])}
        cost = json.loads(attrs.get('langfuse.observation.cost_details') or '{}')
        start = datetime.fromtimestamp(int(event['startTimeUnixNano']) / 1e9, timezone.utc).isoformat()
        if omit_day and start.startswith(omit_day):
            continue
        observations.append({
            'id': event['spanId'], 'traceId': event['traceId'],
            'parentObservationId': event.get('parentSpanId'), 'name': event['name'],
            'type': attrs.get('langfuse.observation.type', 'SPAN').upper(),
            'startTime': start, 'sessionId': attrs.get('langfuse.session.id'),
            'costDetails': cost, 'totalCost': cost.get('total'),
        })
    observations.sort(key=lambda row: row['startTime'], reverse=True)

    def request(method, url, *, params=None, **_kwargs):
        assert method == 'GET'
        params = params or {}
        if url.endswith('/api/public/v2/observations'):
            return Response([row for row in observations if not params.get('type') or row['type'] == params['type']])
        if url.endswith('/api/public/v3/scores'):
            return Response([row for row in scores if not params.get('name') or row['name'] == params['name']])
        raise AssertionError(f'Unexpected API request: {url}')

    monkeypatch.setattr(read, 'request_retry', request)
