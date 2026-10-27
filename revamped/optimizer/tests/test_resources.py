"""Resource guards must reject overload before allocating a routing model."""
import threading
import unittest
from unittest.mock import patch

import engine
from progress import stream_optimization
from test_engine import fixture


class ResourceTests(unittest.TestCase):
    def test_disconnected_stream_keeps_slot_until_solver_really_exits(self):
        started = threading.Event()
        finish = threading.Event()
        stopped = threading.Event()

        def slow_solver(data, on_progress, stop_event):
            started.set()
            finish.wait(2)
            stopped.set()
            return {}

        with patch('engine._optimize', side_effect=slow_solver):
            stream = stream_optimization({}, interval=.01)
            next(stream)
            next(stream)
            self.assertTrue(started.wait(1))
            stream.close()
            try:
                with self.assertRaises(engine.OptimizerBusy):
                    engine.optimize({})
            finally:
                finish.set()
            self.assertTrue(stopped.wait(1))
        # The solving thread releases the slot after returning, so wait for it.
        with engine._solve_slot:
            pass
        self.assertEqual(len(engine.optimize(fixture())['schedule']), 2)

    def test_failed_solver_releases_slot(self):
        with self.assertRaises(KeyError):
            engine.optimize({})
        self.assertEqual(len(engine.optimize(fixture())['schedule']), 2)

    def test_model_budget_rejects_before_model_allocation(self):
        with patch.dict('os.environ', {'OPTIMIZER_MAX_ROUTE_PAIRS': '1'}):
            with patch('engine.cp_model.CpModel') as model:
                with self.assertRaisesRegex(ValueError, '2 route connections'):
                    engine.optimize(fixture())
                model.assert_not_called()

    def test_budget_counts_only_active_compatible_wells(self):
        data = fixture()
        data['dropped_wells'] = ['W2']
        data['platforms']['Other'] = {
            'Supported_Job_Categories': ['Other'],
            'Mob_Demob_Days': 0, 'Daily_Cost_kUSD': 1,
        }
        with patch.dict('os.environ', {'OPTIMIZER_MAX_ROUTE_PAIRS': '1'}):
            self.assertEqual(len(engine.optimize(data)['schedule']), 1)

    def test_cancel_before_build_releases_slot(self):
        cancel = threading.Event()
        cancel.set()
        with patch('engine.cp_model.CpModel') as model:
            with self.assertRaisesRegex(ValueError, 'cancelled'):
                engine.optimize(fixture(), stop_event=cancel)
            model.assert_not_called()
        self.assertEqual(len(engine.optimize(fixture())['schedule']), 2)

    def test_default_solver_uses_one_worker(self):
        solver = engine.cp_model.CpSolver()
        with patch.dict('os.environ', {}, clear=True):
            with patch('engine.cp_model.CpSolver', return_value=solver):
                engine.optimize(fixture())
        self.assertEqual(solver.parameters.num_search_workers, 1)


if __name__ == '__main__':
    unittest.main()
