"""Один фоновый запуск на процесс, статус последнего запуска в памяти."""
import logging
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Lock

logger = logging.getLogger(__name__)


class TrainingJobs:
    def __init__(self, trainer):
        self.trainer = trainer
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='ml-train')
        self.lock = Lock()
        self.state = {'status': 'idle'}

    def submit(self):
        with self.lock:
            if self.state['status'] == 'running':
                return False
            self.state = {'status': 'running'}
            try:
                self.executor.submit(self._run)
            except Exception:
                self.state = {'status': 'failed', 'error': 'TRAIN_SUBMISSION_FAILED'}
                raise
        return True

    def _run(self):
        try:
            result = self.trainer()
            state = {'status': 'succeeded', 'result': result}
        except Exception as exc:
            logger.error('Training failed: %s', type(exc).__name__)
            state = {'status': 'failed', 'error': 'TRAIN_FAILED'}
        with self.lock:
            self.state = state

    def status(self):
        with self.lock:
            return deepcopy(self.state)

    def close(self):
        self.executor.shutdown(wait=True)
