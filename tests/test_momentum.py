import copy
import hashlib
import json
from pathlib import Path
import unittest

from scripts.export_momentum import clean, validate_profile

ROOT=Path(__file__).resolve().parents[1]/'public'/'momentum'

class MomentumSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest=json.loads((ROOT/'manifest.json').read_text())
        cls.profiles={e['id']:json.loads((ROOT/e['file']).read_text()) for e in cls.manifest['profiles']}

    def test_every_published_day_has_consistent_population_and_state(self):
        for p in self.profiles.values():validate_profile(p)

    def test_exact_content_hash_and_default_dates(self):
        for e in self.manifest['profiles']:
            self.assertEqual(hashlib.sha256((ROOT/e['file']).read_bytes()).hexdigest(),e['sha256'])
            p=self.profiles[e['id']]
            ranked=[d for d in p['days'] if d['score_status']=='complete_candidate']
            complete=[d for d in ranked if d['envelope_status']=='complete_candidate']
            self.assertEqual((ranked or p['days'])[-1]['date'],e['default_date'])
            self.assertEqual(p['days'][-1]['date'],e['latest_date'])
            self.assertEqual(ranked[-1]['date'],e['latest_ranked_date'])

    def test_us_envelopes_link_to_selected_coordinates_and_exclude_today(self):
        p=self.profiles['us_etf']
        self.assertEqual(len(p['days']),399)
        valid=[d for d in p['days'] if d['envelopes']]
        self.assertEqual(len(valid),147)
        for d in valid:
            self.assertIsNotNone(d['history']['run_id'])
            self.assertLess(d['history']['end'],d['date'])
            self.assertEqual(d['history']['samples'],7812)

    def test_latest_fed_features_are_reused_but_ranks_are_daily(self):
        for key in ('global_binance','global_coinbase'):
            days=self.profiles[key]['days']
            base={p['key']:p for p in next(d for d in days if d['date']=='2026-09-04')['points']}
            latest=[d for d in days if d['date']>'2026-09-04']
            self.assertEqual(len(latest),4)
            for d in latest:
                self.assertEqual(sum(p['status']=='complete_candidate' for p in d['points']),13)
                self.assertTrue(all(p['rank'] is not None for p in d['points']))
                self.assertEqual(d['envelopes'],[])
                self.assertEqual(sum(p['carried'] for p in d['points']),2)
                for p in d['points']:
                    if p['key'].startswith('fred_'):
                        self.assertEqual(p['source_date'],'2026-09-04')
                        self.assertEqual(p['source_age_days'],int(d['date'][-2:])-4)
                        for metric in ('x','y','volatility'):self.assertEqual(p[metric],base[p['key']][metric])
                    else:self.assertEqual(p['source_date'],d['date'])

    def test_forged_carry_metadata_is_rejected(self):
        for case in ('future','age','non_fed','flag','missing'):
            profile=copy.deepcopy(self.profiles['global_binance'])
            day=profile['days'][-1]
            p=next(p for p in day['points'] if p['carried'])
            if case=='future':p['source_date']='2026-09-14'
            if case=='age':p['source_age_days']=0
            if case=='non_fed':p=next(p for p in day['points'] if not p['key'].startswith('fred_'));p.update(carried=True,source_date='2026-09-04',source_age_days=7)
            if case=='flag':p['carried']=False
            if case=='missing':p['source_date']=None
            with self.subTest(case=case),self.assertRaises(ValueError):validate_profile(profile)

    def test_profile_isolation_and_crypto_gap_preserved(self):
        b=self.profiles['global_binance'];c=self.profiles['global_coinbase']
        self.assertEqual(sum(len(d['envelopes']) for d in b['days']),357)
        self.assertEqual(sum(len(d['envelopes']) for d in c['days']),0)
        for p,prefix,currency in [(b,'binance_','USDT'),(c,'coinbase_','USD')]:
            crypto=[a for a in p['assets'] if a['group']=='crypto']
            self.assertEqual(len(crypto),2)
            self.assertTrue(all(a['key'].startswith(prefix) and a['currency']==currency for a in crypto))

    def test_missing_values_and_liquidity_are_not_zero_or_promoted(self):
        latest=self.profiles['us_etf']['days'][-1]
        unknown=[p for p in latest['points'] if p['liquidity_status']!='complete_candidate']
        self.assertEqual(len(unknown),11)
        self.assertTrue(all(p['turnover'] is None and p['above_threshold'] is None for p in unknown))
        for key,p in self.profiles.items():
            for d in p['days']:
                for row in d['points']:
                    self.assertEqual(row['rank'] is None,row['score'] is None)

    def test_duplicate_mixed_and_incomplete_panels_rejected(self):
        base=self.profiles['global_binance']
        for case in ('duplicate_day','missing_member','mixed_venue','partial_rank','partial_envelope','future_window'):
            p=copy.deepcopy(base)
            d=next(d for d in p['days'] if d['envelopes'])
            if case=='duplicate_day':p['days'].append(p['days'][-1])
            if case=='missing_member':d['points'].pop()
            if case=='mixed_venue':p['assets'][0]['key']='coinbase_btc_usd'
            if case=='partial_rank':d['score_status']='incomplete_population'
            if case=='partial_envelope':d['envelopes'].pop()
            if case=='future_window':d['history']['end']=d['date']
            with self.subTest(case=case),self.assertRaises(ValueError):validate_profile(p)

    def test_no_nonfinite_or_private_database_fields(self):
        for n in (float('nan'),float('inf'),float('-inf')):
            with self.assertRaises(ValueError):clean(n)
        for p in self.profiles.values():
            self.assertEqual(set(p),{'schema_version','id','label','kind','description','run_id','method_version','assets','days'})
            for d in p['days']:
                self.assertEqual(set(d),{'date','score_status','envelope_status','history','points','envelopes'})
                for point in d['points']:
                    self.assertEqual(set(point),{'key','x','y','score','rank','status','quadrant','liquidity_status','turnover','above_threshold','volatility'} | ({'source_date','source_age_days','carried'} if p['kind']=='global' else set()))

if __name__=='__main__':unittest.main()
