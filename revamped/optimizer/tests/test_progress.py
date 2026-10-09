import json
import threading
import time
import unittest
from unittest.mock import patch
from engine import optimize
from progress import stream_optimization, ProgressTracker
from test_engine import fixture


class ProgressTests(unittest.TestCase):
    def test_real_solver_reports_feasible_preview_and_final_score(self):
        updates = []
        result = optimize(fixture(), on_progress=updates.append)
        previews = [u for u in updates if 'preview' in u]
        self.assertTrue(previews)
        self.assertTrue(all('risk' not in u['preview'] and 'monte_carlo' not in u['preview'] for u in previews))
        self.assertEqual(len(previews[-1]['preview']['schedule']), 2)
        scores = [u['objective'] for u in updates if 'objective' in u]
        self.assertEqual(scores, sorted(scores))
        self.assertEqual(scores[-1], result['objective'])
        self.assertEqual(updates[-1]['phase'], 'finalizing')
        self.assertIn('risk', result)

    def test_heartbeat_keeps_best_schedule_when_no_new_solution_arrives(self):
        def fake(data, on_progress, stop_event):
            on_progress({'phase': 'searching', 'solutions': 1, 'objective': 100, 'best_bound': 120,
                         'preview': {'schedule': [{'Well_ID': 'W1'}]}})
            time.sleep(.08)
            return {'status': 'FEASIBLE', 'schedule': [{'Well_ID': 'W1'}]}
        with patch('progress.optimize', side_effect=fake):
            events = [json.loads(line) for line in stream_optimization({}, interval=.02)]
        ticks = [e for e in events if e['type'] == 'progress' and e['progress']['solutions']]
        self.assertGreaterEqual(len(ticks), 2)
        self.assertLess(ticks[0]['progress']['elapsed_seconds'], ticks[-1]['progress']['elapsed_seconds'])
        self.assertEqual(ticks[-1]['progress']['gap_percent'], 20)
        self.assertEqual(ticks[0]['preview'], ticks[-1]['preview'])
        self.assertEqual(events[-1]['type'], 'result')
        self.assertEqual(events[-1]['progress']['phase'], 'completed')

    def test_invalid_input_has_terminal_nonretryable_error(self):
        with patch('progress.optimize', side_effect=ValueError('Unsupported category')):
            events = [json.loads(line) for line in stream_optimization({})]
        self.assertEqual(events[-1]['type'], 'error')
        self.assertFalse(events[-1]['retryable'])
        self.assertEqual(events[-1]['message'], 'Unsupported category')

    def test_disconnect_signals_solver_cancellation(self):
        stopped = threading.Event()
        def fake(data, on_progress, stop_event):
            if stop_event.wait(2):
                stopped.set()
            return {}
        with patch('progress.optimize', side_effect=fake):
            stream = stream_optimization({}, interval=.01)
            next(stream)
            next(stream)
            stream.close()
            self.assertTrue(stopped.wait(1))

    def test_tracker_does_not_replace_best_preview_with_a_worse_solution(self):
        tracker = ProgressTracker()
        tracker.update({'objective': 100, 'preview': {'schedule': ['best']}})
        tracker.update({'objective': 90, 'preview': {'schedule': ['worse']}})
        progress, preview = tracker.snapshot()
        self.assertEqual(progress['objective'], 100)
        self.assertEqual(preview['schedule'], ['best'])
