"""Exercise the shared workspace without authentication; preserve existing datasets."""
import json
import os
import time
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get('BAYU_API', 'http://localhost:8080/api')


def request(path, method='GET', data=None, content_type='application/json'):
    if isinstance(data, dict):
        data = json.dumps(data).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={'Content-Type': content_type})
    with urllib.request.urlopen(req, timeout=20) as response:
        body = response.read()
        return json.loads(body) if body else None


def wait(job):
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        response = request('/jobs/' + job['id'])
        if response['job']['status'] == 'failed':
            raise AssertionError(response['job']['error'])
        if response['job']['status'] == 'completed':
            return response['result']
        time.sleep(1)
    raise AssertionError('Job did not finish before timeout')


def upload(kind, content):
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{kind}.csv"\r\nContent-Type: text/csv\r\n\r\n'.encode()
            + content + f'\r\n--{boundary}--\r\n'.encode())
    return request('/imports/' + kind, 'POST', body, 'multipart/form-data; boundary=' + boundary)


def main():
    prefix = 'SMOKE-' + uuid.uuid4().hex[:12]
    category = prefix + '-Logging'
    created = []
    baseline = request('/wells')
    request('/platforms')
    request('/jobs')
    for path in ['/auth/register', '/auth/login', '/me']:
        try:
            request(path, 'GET' if path == '/me' else 'POST', {} if path != '/me' else None)
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError('Legacy authentication endpoint remains available')
    try:
        platform = request('/platforms', 'POST', {
            'name': prefix + '-Platform', 'type': 'Smoke test', 'categories': [category],
            'mob_demob_days': 2, 'daily_cost_kusd': 12.125, 'contract_end_date': ''})
        created.append(('platforms', platform['id']))
        wells = []
        for i in range(2):
            well = request('/wells', 'POST', {
                'name': prefix + '-W' + str(i), 'category': category, 'duration_days': 5 + i,
                'gain_bopd': 500, 'lat': 4.1 + .1*i, 'lon': 112.2 + .1*i})
            wells.append(well)
            created.append(('wells', well['id']))
        assert {w['name'] for w in wells}.issubset({w['name'] for w in request('/wells')})
        job = request('/optimizations', 'POST', {
            'name': prefix + ' scenario', 'start_date': '2026-10-09',
            'dropped_wells': [w['name'] for w in baseline]})
        result = wait(job)
        assert {r['Well_ID'] for r in result['schedule']} == {w['name'] for w in wells}
        previous_end = 0
        for row in result['schedule']:
            assert row['Platform_Assigned'] == platform['name']
            assert row['End_Day'] <= 365
            assert row['End_Day'] - row['Start_Day'] == row['Duration_Days'] + 2
            assert row['Start_Day'] >= previous_end
            previous_end = row['End_Day']
        assert len(result['monte_carlo']['gain_bopd']) == 10000
        assert wait(upload('wells', (f'Well_ID,Job Category,Duration_Days,Gain_BOPD,Lat,Lon\n{wells[0]["name"]},{category},8,550,4.1,112.2\n').encode()))['imported'] == 1
        assert wait(upload('platforms', (f'Platform_Name,Supported_Job_Categories,Mob_Demob_Days,Daily_Cost_kUSD\n{platform["name"]},{category},3,15\n').encode()))['imported'] == 1
        before = request('/wells')
        bad = upload('wells', (f'Well_ID,Job Category,Duration_Days,Gain_BOPD,Lat,Lon\n{wells[0]["name"]},{category},20,400,4,112\nBAD,{category},5,400,91,112\n').encode())
        try:
            wait(bad)
        except AssertionError as exc:
            assert 'Latitude' in str(exc)
        else:
            raise AssertionError('Invalid import succeeded')
        assert request('/wells') == before
        well = dict(wells[0]); well['name'] = prefix + '-UPDATED'
        request('/wells/' + str(well['id']), 'PUT', well)
        saved = request('/jobs/' + job['id'])
        assert saved['progress']['phase'] == 'completed'
        assert saved['progress']['solutions'] >= 1
        assert saved['progress']['history']
        assert saved['progress']['elapsed_seconds'] >= 0
        original = next(w for w in saved['input']['wells'] if w['Well_ID'] == wells[0]['name'])
        assert original['Duration_Days'] == 5
        print('PASS: direct access, shared datasets, CRUD, saved snapshots, optimization, Monte Carlo, staged imports, and import rollback')
    finally:
        for kind, identifier in reversed(created):
            request(f'/{kind}/{identifier}', 'DELETE')


if __name__ == '__main__':
    main()
