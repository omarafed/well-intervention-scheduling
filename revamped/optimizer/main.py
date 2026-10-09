import io
import json
import os
import secrets
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
import pandas as pd
from engine import optimize, _validate_optimization_inputs, _as_nonnegative_int
from fastapi.responses import StreamingResponse
from progress import stream_optimization

app = FastAPI(title="Platform scheduling optimizer", docs_url=None, redoc_url=None)


@app.get('/health')
def health():
    return {"status": "ok"}


@app.middleware('http')
async def authenticate(request: Request, call_next):
    from fastapi.responses import JSONResponse
    if request.url.path != '/health' and not secrets.compare_digest(request.headers.get('x-service-token', ''), os.environ['SERVICE_TOKEN']):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


@app.post('/optimize')
async def solve(request: Request):
    data = await request.json()
    if not 1 <= len(data.get('wells', [])) <= 200 or not 1 <= len(data.get('platforms', {})) <= 20:
        raise HTTPException(422, 'Use 1–200 wells and 1–20 platforms per optimization.')
    try:
        result = await run_in_threadpool(optimize, data)
        # Convert NumPy scalar values to JSON-native values and reject non-finite values.
        return json.loads(json.dumps(result, default=lambda x: x.item(), allow_nan=False))
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post('/optimize/stream')
async def solve_stream(request: Request):
    data = await request.json()
    if not 1 <= len(data.get('wells', [])) <= 200 or not 1 <= len(data.get('platforms', {})) <= 20:
        raise HTTPException(422, 'Use 1–200 wells and 1–20 platforms per optimization.')
    return StreamingResponse(stream_optimization(data), media_type='application/x-ndjson',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.post('/parse/{kind}')
async def parse(kind: str, request: Request, filename: str = 'data.csv'):
    if kind not in ('wells', 'platforms'):
        raise HTTPException(422, 'Unknown dataset type')
    body = await request.body()
    if len(body) > 10 * 1024 * 1024:
        raise HTTPException(413, 'File exceeds 10 MiB')
    try:
        return await run_in_threadpool(parse_file, kind, filename, body)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


def parse_file(kind, filename, body):
    if filename.lower().endswith('.csv'):
        df = pd.read_csv(io.BytesIO(body))
    elif filename.lower().endswith('.xlsx'):
        df = pd.read_excel(io.BytesIO(body))
    else:
        raise ValueError('Upload a CSV or XLSX file.')
    if not 1 <= len(df) <= 1000:
        raise ValueError('Imports must contain 1–1000 rows.')
    if kind == 'wells':
        df = df.rename(columns={'Gain_BOPD': 'BOPD'})
        # Reuse engine validation with a dummy compatible platform.
        dummy = {'validation': {'Supported_Job_Categories': ['validation'], 'Mob_Demob_Days': 0, 'Daily_Cost_kUSD': 1}}
        validated, _ = _validate_optimization_inputs(df, dummy)
        return [{'name': str(r['Well_ID']).strip(), 'category': str(r['Job Category']).strip(),
                 'duration_days': int(r['Duration_Days']), 'gain_bopd': int(r['BOPD']),
                 'lat': float(r['Lat']), 'lon': float(r['Lon'])} for r in validated.to_dict('records')]
    # Accept exports from the original notebook while keeping the new template canonical.
    if 'Platform_Name' not in df.columns and 'Rig_Name' in df.columns:
        df = df.rename(columns={'Rig_Name': 'Platform_Name'})
    required = ['Platform_Name', 'Supported_Job_Categories', 'Mob_Demob_Days', 'Daily_Cost_kUSD']
    if any(c not in df.columns for c in required):
        raise ValueError('Required columns: ' + ', '.join(required))
    if df['Platform_Name'].isna().any() or df['Platform_Name'].duplicated().any():
        raise ValueError('Platform names must be non-empty and unique.')
    from datetime import datetime
    rows = []
    categories = ["Downhole Logging, Survey & Test", "Wellhead Maintenance", "Slickline Services", "CTU Services", "Sand Control & Monitoring", "Perforation", "Well Repair & Maintenance", "Well Stimulation", "Artificial Lift Enhancement"]
    for r in df.fillna('').to_dict('records'):
        raw = str(r['Supported_Job_Categories'])
        supported = [c.strip() for c in raw.split(';') if c.strip()] if ';' in raw else [c for c in categories if c in raw]
        if not supported:
            supported = [raw.strip()] if raw.strip() else []
        end = str(r.get('Contract_End_Date', ''))[:10]
        if end:
            datetime.strptime(end, '%Y-%m-%d')
        rows.append({'name': str(r['Platform_Name']).strip(), 'type': str(r.get('Type', '')),
                     'categories': supported, 'mob_demob_days': _as_nonnegative_int(r['Mob_Demob_Days'], 'Mob/Demob Days'),
                     'daily_cost_kusd': float(r['Daily_Cost_kUSD']), 'contract_end_date': end})
    return rows
