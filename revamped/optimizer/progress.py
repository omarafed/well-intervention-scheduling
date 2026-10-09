"""Thread-safe solver snapshots and a five-second NDJSON heartbeat."""
import json
import queue
import threading
import time
from engine import optimize


class ProgressTracker:
    def __init__(self):
        self.lock = threading.Lock()
        self.started = time.monotonic()
        self.search_started = None
        self.state = {'phase': 'building', 'solutions': 0, 'time_limit_seconds': 45}
        self.preview = None
        self.history = []

    def update(self, update):
        with self.lock:
            update = dict(update)
            if update.get('phase') == 'searching' and self.search_started is None:
                self.search_started = time.monotonic()
            if 'objective' in update and update['objective'] < self.state.get('objective', float('-inf')):
                update.pop('objective')
                update.pop('preview', None)
            if 'preview' in update:
                self.preview = update.pop('preview')
            self.state.update(update)

    def snapshot(self):
        with self.lock:
            now = time.monotonic()
            state = dict(self.state)
            state['elapsed_seconds'] = round(now - self.started, 2)
            state['search_seconds'] = round(now - self.search_started, 2) if self.search_started else 0
            objective, bound = state.get('objective'), state.get('best_bound')
            if objective is not None and bound is not None:
                state['gap_percent'] = max(0, bound - objective) / max(abs(objective), 1) * 100
                self.history.append({key: state[key] for key in ('elapsed_seconds', 'objective', 'best_bound', 'solutions')})
            state['history'] = list(self.history)
            return state, self.preview


def stream_optimization(data, interval=5):
    tracker = ProgressTracker()
    outcome = queue.Queue(maxsize=1)
    cancel = threading.Event()

    def run():
        try:
            result = optimize(data, on_progress=tracker.update, stop_event=cancel)
            tracker.update({'phase': 'completed'})
            outcome.put(('result', result))
        except Exception as exc:
            outcome.put(('error', (str(exc), not isinstance(exc, (ValueError, TypeError, KeyError)))))

    def encode(event):
        return json.dumps(event, default=lambda value: value.item(), allow_nan=False) + '\n'

    try:
        # Publish before launching the thread so the first event is always a clean initial state.
        progress, preview = tracker.snapshot()
        yield encode({'type': 'progress', 'progress': progress, 'preview': preview})
        threading.Thread(target=run, daemon=True).start()
        while True:
            try:
                kind, value = outcome.get(timeout=interval)
            except queue.Empty:
                progress, preview = tracker.snapshot()
                yield encode({'type': 'progress', 'progress': progress, 'preview': preview})
                continue
            progress, _ = tracker.snapshot()
            if kind == 'error':
                message, retryable = value
                yield encode({'type': 'error', 'message': message, 'retryable': retryable})
            else:
                yield encode({'type': 'result', 'result': value, 'progress': progress})
            break
    finally:
        cancel.set()
