import unittest
from engine import optimize, haversine
from main import parse_file


def fixture():
    return {'start_date': '2026-10-08', 'time_limit': 2, 'wells': [
        {'Well_ID': 'W1', 'Job Category': 'Logging', 'Duration_Days': 5, 'BOPD': 500, 'Lat': 4.1, 'Lon': 112.2},
        {'Well_ID': 'W2', 'Job Category': 'Logging', 'Duration_Days': 3, 'BOPD': 400, 'Lat': 4.2, 'Lon': 112.3},
    ], 'platforms': {'Platform-1': {'Supported_Job_Categories': ['Logging'], 'Mob_Demob_Days': 2, 'Daily_Cost_kUSD': 12.125, 'Contract_End_Date': '2026-10-09'}}}


class EngineTests(unittest.TestCase):
    def test_schedule_transit_cost_and_risk(self):
        result = optimize(fixture())
        rows = result['schedule']
        self.assertEqual({r['Well_ID'] for r in rows}, {'W1', 'W2'})
        for row in rows:
            self.assertEqual(row['Platform_Assigned'], 'Platform-1')
            self.assertEqual(row['End_Day'] - row['Start_Day'], row['Duration_Days'] + 2)
            self.assertAlmostEqual(row['Cost_kUSD'], (row['Duration_Days'] + 2) * 12.125)
            self.assertLessEqual(row['End_Day'], 365)
        import math
        transit = math.ceil(haversine(rows[0]['Lat'], rows[0]['Lon'], rows[1]['Lat'], rows[1]['Lon']) / 50) + 1
        self.assertGreaterEqual(rows[1]['Start_Day'], rows[0]['End_Day'] + transit)
        self.assertEqual(len(result['monte_carlo']['gain_bopd']), 10000)
        self.assertLess(result['risk']['gain']['p90'], result['risk']['gain']['p10'])
        self.assertGreater(result['risk']['cost']['p90'], result['risk']['cost']['p10'])
        self.assertTrue(result['warnings'])

    def test_exclusion_and_unsupported_category(self):
        data = fixture(); data['dropped_wells'] = ['W2']
        self.assertEqual([r['Well_ID'] for r in optimize(data)['schedule']], ['W1'])
        data = fixture(); data['wells'][0]['Job Category'] = 'Unsupported'
        with self.assertRaisesRegex(ValueError, 'No platform supports'):
            optimize(data)

    def test_invalid_and_infeasible_inputs(self):
        data = fixture(); data['wells'][0]['Lat'] = 91
        with self.assertRaises(ValueError): optimize(data)
        data = fixture(); data['wells'][0]['Duration_Days'] = 366
        with self.assertRaisesRegex(ValueError, 'No feasible schedule'): optimize(data)
        data = fixture(); data['dropped_wells'] = ['W1', 'W2']
        with self.assertRaisesRegex(ValueError, 'At least one'): optimize(data)

    def test_csv_and_excel_imports(self):
        body = b'Well_ID,Job Category,Duration_Days,Gain_BOPD,Lat,Lon\nW1,Logging,5,500,4.1,112.2\n'
        rows = parse_file('wells', 'wells.csv', body)
        self.assertEqual(rows[0]['gain_bopd'], 500)
        import io
        import pandas as pd
        stream = io.BytesIO(); pd.read_csv(io.BytesIO(body)).to_excel(stream, index=False)
        self.assertEqual(parse_file('wells', 'wells.xlsx', stream.getvalue()), rows)
        platforms = parse_file('platforms', 'platforms.csv', b'Platform_Name,Supported_Job_Categories,Mob_Demob_Days,Daily_Cost_kUSD\nPlatform-1,Logging;Perforation,2,12\n')
        self.assertEqual(platforms[0]['categories'], ['Logging', 'Perforation'])
        self.assertIsInstance(platforms[0]['mob_demob_days'], int)
        with self.assertRaises(ValueError): parse_file('wells', 'bad.csv', body + b'W1,Logging,5,500,4.1,112.2\n')
        with self.assertRaises(ValueError): parse_file('wells', 'bad.csv', body + b' W1 ,Logging,5,500,4.1,112.2\n')

    def test_legacy_platform_name_header(self):
        import io
        import pandas as pd
        legacy = b'Rig_Name,Type,Supported_Job_Categories,Mob_Demob_Days,Daily_Cost_kUSD,Contract_End_Date\nRig-1 (Light Unit),Light Unit,"Downhole Logging, Survey & Test, Wellhead Maintenance, Slickline Services",2,12,2027-09-10\n'
        canonical = legacy.replace(b'Rig_Name,', b'Platform_Name,', 1)
        expected = parse_file('platforms', 'platforms.csv', canonical)
        self.assertEqual(parse_file('platforms', 'example_rig.csv', legacy), expected)
        self.assertEqual(expected[0]['name'], 'Rig-1 (Light Unit)')
        self.assertEqual(expected[0]['categories'], ['Downhole Logging, Survey & Test', 'Wellhead Maintenance', 'Slickline Services'])
        stream = io.BytesIO()
        pd.read_csv(io.BytesIO(legacy)).to_excel(stream, index=False)
        self.assertEqual(parse_file('platforms', 'legacy.xlsx', stream.getvalue()), expected)
        # Prefer the canonical name when a file includes both headers.
        both = pd.read_csv(io.BytesIO(legacy))
        both['Platform_Name'] = 'Platform-1'
        rows = parse_file('platforms', 'both.csv', both.to_csv(index=False).encode())
        self.assertEqual(rows[0]['name'], 'Platform-1')


if __name__ == '__main__': unittest.main()
