"""Export an explicit, read-only PostgreSQL snapshot for the static Pages UI.

Only derived chart values are exported. No raw responses, DSNs, or arbitrary
JSON metadata are published. Changing a run requires an explicit CLI argument.
"""
import argparse
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path

DEFAULT_RUNS = {
    'us_etf': '8f1b68e2-e3a4-4345-8f90-5983b7f4a738',
    'global_binance': 'a9da8669-7e99-4fe6-a71c-52c682fd0574',
    'global_coinbase': 'c4df5169-7846-4cd4-97dc-cdae4b82eff4',
}
PROFILE_INFO = {
    'us_etf': ('미국 ETF', 'us', 'SPY 대비 상대강도 · 섹터 대비 가속도'),
    'global_binance': ('글로벌 · Binance USDT', 'global', 'BTC·ETH: Binance 현물 USDT, USD 환산 없음'),
    'global_coinbase': ('글로벌 · Coinbase USD', 'global', 'BTC·ETH: Coinbase 현물 USD, 거래소 결측 보존'),
}


def clean(value):
    if isinstance(value, (float, Decimal)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('Non-finite public chart value')
        return round(number, 8)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def source_for(key):
    if key.startswith('binance_'):
        return {'name': 'Binance', 'url': 'https://data.binance.vision/'}
    if key.startswith('coinbase_'):
        return {'name': 'Coinbase Exchange', 'url': 'https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles'}
    if key.startswith('fred_'):
        return {'name': 'Federal Reserve H.10', 'url': 'https://www.federalreserve.gov/releases/h10/'}
    if key.startswith('krx_'):
        return {'name': 'Kiwoom 공식 지수 응답', 'url': 'https://openapi.kiwoom.com/'}
    return {'name': 'Alpaca · 운용사 기업행동 검토', 'url': 'https://docs.alpaca.markets/docs/historical-stock-data-1'}


def validate_profile(profile):
    """Fail closed before publishing partial, mixed or ambiguous panels."""
    expected = 31 if profile['kind'] == 'us' else 13
    keys = {a['key'] for a in profile['assets']}
    if len(keys) != expected or len(profile['assets']) != expected:
        raise ValueError('Unexpected profile population')
    if profile['id'] == 'global_binance' and (any(k.startswith('coinbase_') for k in keys) or not {'binance_btc_usdt', 'binance_eth_usdt'} <= keys):
        raise ValueError('Mixed crypto profile')
    if profile['id'] == 'global_coinbase' and (any(k.startswith('binance_') for k in keys) or not {'coinbase_btc_usd', 'coinbase_eth_usd'} <= keys):
        raise ValueError('Mixed crypto profile')
    dates = [d['date'] for d in profile['days']]
    if not dates or dates != sorted(set(dates)):
        raise ValueError('Empty, unordered or duplicate dates')
    for d in profile['days']:
        if len(d['points']) != expected or {p['key'] for p in d['points']} != keys:
            raise ValueError('Incomplete day population')
        for p in d['points']:
            if (p['status'] == 'complete_candidate') != (p['x'] is not None and p['y'] is not None):
                raise ValueError('Coordinate status mismatch')
            if profile['kind'] == 'global':
                sd=p['source_date'];age=p['source_age_days'];carried=p['carried']
                if sd is not None:
                    expected_age=(date.fromisoformat(d['date'])-date.fromisoformat(sd)).days
                    if expected_age<0 or age!=expected_age:raise ValueError('Invalid source observation date')
                elif age is not None or p['status']=='complete_candidate':raise ValueError('Missing source observation date')
                if carried != bool(sd and sd<d['date'] and p['status']=='complete_candidate'):
                    raise ValueError('Carry state mismatch')
                if carried and p['key'] not in ('fred_dexkous','fred_dtwexbgs'):
                    raise ValueError('Carry is restricted to Fed series')
            if (p['score'] is None) != (p['rank'] is None):
                raise ValueError('Score/rank mismatch')
        ranks = [p for p in d['points'] if p['rank'] is not None]
        if d['score_status'] != 'complete_candidate' and ranks:
            raise ValueError('Ranking incomplete population')
        if d['score_status'] == 'complete_candidate' and len(ranks) != (26 if profile['kind'] == 'us' else 13):
            raise ValueError('Missing ranks')
        levels = d['envelopes']
        if d['envelope_status'] == 'complete_candidate':
            if [x['coverage'] for x in levels] != [0.8, 0.95, 0.99]:
                raise ValueError('Incomplete envelope levels')
            h = d['history']
            if h['sessions'] != 252 or h['samples'] != expected * 252 or not h['end'] < d['date']:
                raise ValueError('Invalid historical window')
        elif levels:
            raise ValueError('Envelope supplied for withheld day')
    clean(profile)


def export_profile(conn, profile_id, run_id):
    info = PROFILE_INFO[profile_id]
    us = info[1] == 'us'
    run = conn.execute('SELECT status,loader_version,summary FROM ingest.pipeline_run WHERE run_id=%s', (run_id,)).fetchone()
    if not run or run['status'] != 'completed_with_issues':
        raise ValueError('Require a completed coordinate run')
    if not run['loader_version'].startswith('us_momentum_coordinates_' if us else 'global_momentum_coordinates_'):
        raise ValueError('Wrong run type')
    if profile_id == 'global_binance' and run['summary'].get('profile') != 'global_binance_usdt_v1':
        raise ValueError('Wrong Binance profile')
    assets = {}; points = defaultdict(list); envelopes = defaultdict(list); histories = {}
    if us:
        rows = conn.execute('''SELECT p.*,a.asset_key,a.initial_ticker,a.label_ko
            FROM report.us_momentum_point p JOIN ref.asset a USING(asset_id)
            WHERE p.run_id=%s ORDER BY p.session_date,a.initial_ticker''', (run_id,)).fetchall()
        for r in rows:
            key = r['asset_key']
            assets[key] = dict(key=key, ticker=r['initial_ticker'], label=r['label_ko'], group='us_equity' if r['role'] in ('ranked','benchmark') else 'context', role=r['role'], basis='market_total_return', currency='USD', source=source_for(key))
            points[str(r['session_date'])].append(dict(key=key, x=r['x_pp'], y=r['y_bps'], score=r['composite_score'], rank=r['observation_rank'], status=r['coordinate_status'], quadrant=r['quadrant'], liquidity_status=r['liquidity_status'], turnover=r['mean_turnover_20_usd'], above_threshold=r['candidate_above_threshold'], volatility=None))
        daily = conn.execute('SELECT * FROM report.us_momentum_daily WHERE run_id=%s ORDER BY session_date', (run_id,)).fetchall()
        history_rows = conn.execute('''SELECT DISTINCT ON (d.session_date) d.*
            FROM report.us_momentum_envelope_daily d JOIN ingest.pipeline_run r USING(run_id)
            WHERE d.coordinate_run_id=%s AND r.status='completed_with_issues'
            ORDER BY d.session_date,r.finished_at DESC,d.run_id DESC''', (run_id,)).fetchall()
        for r in history_rows:
            ds = str(r['session_date'])
            histories[ds] = dict(start=r['first_history_session'], end=r['last_history_session'], sessions=r['history_sessions'], samples=r['sample_count'], expected_samples=7812, status=r['status'], run_id=str(r['run_id']))
            for e in conn.execute('SELECT * FROM report.us_momentum_envelope WHERE run_id=%s AND session_date=%s ORDER BY coverage', (r['run_id'],r['session_date'])):
                envelopes[ds].append(dict(coverage=e['coverage'],x=e['x_bound_pp'],y=e['y_bound_bps'],samples=e['covered_samples'],empirical=e['empirical_coverage']))
    else:
        rows = conn.execute('''SELECT p.*,m.series_key,m.metadata,a.initial_ticker FROM report.global_momentum_point p
            JOIN ref.global_member m USING(member_id) LEFT JOIN ref.asset a ON a.asset_id=m.etf_asset_id
            WHERE p.run_id=%s ORDER BY p.observation_date,m.series_key''', (run_id,)).fetchall()
        for r in rows:
            key=r['series_key']; m=r['metadata']
            ticker = r['initial_ticker'] or {'krx_kospi':'KOSPI','krx_kosdaq':'KOSDAQ','fred_dtwexbgs':'BROAD USD','fred_dexkous':'KRW'}.get(key) or ('BTC' if 'btc' in key else 'ETH')
            assets[key] = dict(key=key,ticker=ticker,label=m['label_ko'],group=m['asset_class'],role='ranked',basis=m['basis'],currency=m.get('quote_currency',m.get('currency')),source=source_for(key))
            points[str(r['observation_date'])].append(dict(key=key,x=r['x_trend'],y=r['y_acceleration'],score=r['composite_score'],rank=r['observation_rank'],status=r['coordinate_status'],quadrant=r['quadrant'],liquidity_status=None,turnover=None,above_threshold=None,volatility=r['annualized_volatility_20'],source_date=r['details'].get('source_observation_date'),source_age_days=r['details'].get('source_age_days'),carried=r['details'].get('carried_forward',False)))
        daily = conn.execute('SELECT * FROM report.global_momentum_daily WHERE run_id=%s ORDER BY observation_date',(run_id,)).fetchall()
        for r in daily:
            ds=str(r['observation_date']);h=r['details'].get('envelope',{});hd=h.get('history_dates',[])
            histories[ds]=dict(start=hd[0] if hd else None,end=hd[-1] if hd else None,sessions=len(hd),samples=h.get('sample_count',0),expected_samples=3276,status=r['envelope_status'],run_id=run_id)
        for e in conn.execute('SELECT * FROM report.global_momentum_envelope WHERE run_id=%s ORDER BY observation_date,coverage',(run_id,)):
            envelopes[str(e['observation_date'])].append(dict(coverage=e['coverage'],x=e['x_bound'],y=e['y_bound'],samples=e['covered_samples'],empirical=e['empirical_coverage']))
    days=[]
    for r in daily:
        ds=str(r['session_date' if us else 'observation_date'])
        history=histories.get(ds,dict(start=None,end=None,sessions=0,samples=0,expected_samples=7812,status=r['envelope_status'],run_id=None))
        days.append(dict(date=ds,score_status=r['score_status'],envelope_status=history['status'],history=history,points=points[ds],envelopes=envelopes[ds]))
    result=clean(dict(schema_version=1,id=profile_id,label=info[0],kind=info[1],description=info[2],run_id=run_id,method_version=daily[0]['method_version'] if daily else None,assets=list(assets.values()),days=days))
    validate_profile(result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',type=Path,default=Path(__file__).resolve().parents[1]/'public'/'momentum')
    for key,value in DEFAULT_RUNS.items():p.add_argument('--'+key.replace('_','-')+'-run',default=value)
    args=p.parse_args()
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    from psycopg.rows import dict_row
    dsn=os.environ.get('ASSET_MOMENTUM_POSTGRES_DSN','dbname=asset_momentum')
    if conninfo_to_dict(dsn).get('dbname') != 'asset_momentum':raise ValueError('Require asset_momentum database')
    profiles=[]
    with psycopg.connect(dsn,options='-c default_transaction_read_only=on -c default_transaction_isolation=repeatable\\ read',row_factory=dict_row) as conn:
        for key in PROFILE_INFO:profiles.append(export_profile(conn,key,getattr(args,key+'_run')))
    # All validation precedes any output update; manifest is replaced last.
    args.output_dir.mkdir(parents=True,exist_ok=True)
    manifest=dict(schema_version=1,exported_at=datetime.now(timezone.utc).isoformat(),candidate_only=True,history_mode='current_revised_not_as_known',profiles=[])
    for profile in profiles:
        body=json.dumps(profile,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
        sha=hashlib.sha256(body).hexdigest();filename=profile['id']+'-'+sha[:12]+'.json'
        (args.output_dir/filename).write_bytes(body)
        dates=[d['date'] for d in profile['days']];ranked=[d['date'] for d in profile['days'] if d['score_status']=='complete_candidate'];complete=[d['date'] for d in profile['days'] if d['score_status']=='complete_candidate' and d['envelope_status']=='complete_candidate']
        manifest['profiles'].append(dict(id=profile['id'],label=profile['label'],kind=profile['kind'],description=profile['description'],file=filename,sha256=sha,dates=len(dates),latest_date=dates[-1],latest_ranked_date=ranked[-1] if ranked else None,default_date=(ranked or dates)[-1]))
    tmp=args.output_dir/'manifest.json.tmp';tmp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n');tmp.replace(args.output_dir/'manifest.json')
    active={r['file'] for r in manifest['profiles']}
    for f in args.output_dir.glob('*.json'):
        if f.name != 'manifest.json' and any(f.name.startswith(k+'-') for k in PROFILE_INFO) and f.name not in active:f.unlink()
    print(json.dumps(manifest,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
