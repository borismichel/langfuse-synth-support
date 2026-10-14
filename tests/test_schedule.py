"""The supported schedule is observable in the actual runtime Spool."""
import json
from datetime import datetime, timezone

import pytest

from synth.config import load_config
from synth.seed import run_seed


def generated_spool(tmp_path, *, volume=200, seed=42, as_of='2026-10-16'):
    cfg = load_config('config/demo.yaml', overrides=[
        f'generation.target_traces={volume}', f'generation.seed={seed}',
        f'generation.as_of_date={as_of}',
    ])
    path = run_seed(cfg, dry_run=True, do_import=False,
                    spool_path=tmp_path / 'events.ndjson', log=lambda _: None)
    return cfg, [json.loads(line) for line in path.read_text().splitlines()]


def observation_times(events):
    return [datetime.fromtimestamp(int(event[key]) / 1e9, timezone.utc)
            for event in events if 'spanId' in event
            for key in ('startTimeUnixNano', 'endTimeUnixNano')]


@pytest.mark.parametrize('volume', [1, 200, 1000])
def test_selected_friday_is_present_in_the_inclusive_28_day_history(tmp_path, volume):
    _, events = generated_spool(tmp_path, volume=volume)
    stamps = observation_times(events)
    assert min(stamps) >= datetime(2026, 9, 19, tzinfo=timezone.utc)
    assert max(stamps) < datetime(2026, 10, 17, tzinfo=timezone.utc)
    roots = [event for event in events if event.get('name') == 'support-triage-turn']
    assert len(roots) == volume
    assert max(observation_times(roots)).date().isoformat() == '2026-10-16'


def test_late_turn_children_and_feedback_stay_on_the_selected_day(tmp_path):
    # This real seed emits a late-night turn with feedback after midnight unless
    # the whole turn has enough headroom. All durations must remain positive.
    _, events = generated_spool(tmp_path, seed=196)
    end = datetime(2026, 10, 17, tzinfo=timezone.utc)
    stamps = observation_times(events)
    for event in events:
        if event.get('type') == 'score-create':
            stamps.append(datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00')))
        else:
            assert int(event['endTimeUnixNano']) >= int(event['startTimeUnixNano'])
            for attr in event.get('attributes', []):
                if attr['key'] == 'langfuse.observation.completion_start_time':
                    stamps.append(datetime.fromisoformat(attr['value']['stringValue'].replace('Z', '+00:00')))
    assert max(stamps) < end


def test_seed_publishes_requested_schedule_and_measured_observation_range(tmp_path, monkeypatch):
    from langfuse_synth_core.seed import ingest

    class Projects:
        def raise_for_status(self): pass
        def json(self): return {'data': [{'id': 'offline-demo', 'name': 'demo'}]}

    def request(method, url, **_kwargs):
        assert method == 'GET' and url.endswith('/api/public/projects')
        return Projects()

    monkeypatch.setattr(ingest, 'request_retry', request)
    monkeypatch.setenv('LANGFUSE_PUBLIC_KEY', 'pk-offline')
    monkeypatch.setenv('LANGFUSE_SECRET_KEY', 'sk-offline')
    monkeypatch.setenv('SYNTH_OUT_DIR', str(tmp_path / 'out'))
    cfg = load_config('config/demo.yaml', overrides=[
        'generation.target_traces=200', 'generation.as_of_date=2026-10-16',
    ])
    spool = run_seed(cfg, do_import=False, spool_path=tmp_path / 'events.ndjson', log=lambda _: None)
    events = [json.loads(line) for line in spool.read_text().splitlines()]
    schedule = json.loads((tmp_path / 'out' / 'SCHEDULE.json').read_text())
    assert schedule['version'] == 1
    assert schedule['requested'] == {
        'as_of_date': '2026-10-16', 'history_days': 28, 'timezone': 'UTC', 'end': 'inclusive',
    }
    stamps = observation_times(events)
    actual = schedule['generated_range']
    assert actual['timezone'] == 'UTC'
    assert datetime.fromisoformat(actual['start'].replace('Z', '+00:00')) == min(stamps)
    assert datetime.fromisoformat(actual['end'].replace('Z', '+00:00')) == max(stamps)
    assert (tmp_path / 'out' / 'DEMO_SCRIPT.md').is_file()


@pytest.mark.parametrize('volume', [200, 1000])
def test_presentation_and_rehearsal_pass_the_real_scenario_oracle(tmp_path, monkeypatch, volume):
    from generated_readback import install_readback
    from synth.verify import run_verify

    cfg, events = generated_spool(tmp_path, volume=volume)
    install_readback(monkeypatch, events)
    report = run_verify(cfg, log=lambda _: None)
    checks = {check.name: check.ok for check in report.checks}
    assert checks['selected_day_present']
    assert report.ok, [vars(check) for check in report.checks if not check.ok]


def test_latest_day_scores_cannot_replace_missing_latest_day_observations(tmp_path, monkeypatch):
    from generated_readback import install_readback
    from synth.verify import run_verify

    cfg, events = generated_spool(tmp_path)
    install_readback(monkeypatch, events, omit_day='2026-10-16')
    checks = {check.name: check.ok for check in run_verify(cfg, log=lambda _: None).checks}
    assert checks['selected_day_present'] is False
    assert checks['retrieval_regression_visible'] is True


@pytest.mark.parametrize('as_of,start,end', [
    ('2027-01-01', '2026-12-05', '2027-01-02'),
    ('2028-02-29', '2028-02-02', '2028-03-01'),
    ('2026-03-29', '2026-03-02', '2026-03-30'),
])
def test_fixed_utc_calendar_survives_year_leap_and_dst_boundaries(tmp_path, as_of, start, end):
    _, events = generated_spool(tmp_path, as_of=as_of)
    stamps = observation_times(events)
    assert min(stamps) >= datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    assert max(stamps) < datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
    assert max(stamps).date().isoformat() == as_of
