from PyQt6.QtCore import QObject, pyqtSignal, QThread, QMutex, QWaitCondition
from collections import OrderedDict
import logging
import pandas as pd
import queue
import hashlib
import json
from utils.peak_matching.peptide_fragmentation import calculate_fragment_ions, match_fragment_ions, filter_ions

logger = logging.getLogger(__name__)


class FragmentationTask:
    """Container for fragmentation task data"""
    def __init__(self, task_id, peptide, modifications, max_charge, ppm_tolerance,
                 selected_ions, selected_internal_ions, user_mz_values,
                 diagnostic_ions, custom_ion_series_list, max_neutral_losses=1,
                 calculate_isotopes=True, mod_neutral_losses=None):
        self.task_id = task_id
        self.peptide = peptide
        self.modifications = modifications
        self.max_charge = max_charge
        self.ppm_tolerance = ppm_tolerance
        self.selected_ions = selected_ions
        self.selected_internal_ions = selected_internal_ions
        self.user_mz_values = user_mz_values
        self.diagnostic_ions = diagnostic_ions
        self.custom_ion_series_list = custom_ion_series_list
        self.max_neutral_losses = max_neutral_losses
        self.calculate_isotopes = calculate_isotopes
        self.mod_neutral_losses = mod_neutral_losses


class PersistentFragmentationWorker(QObject):
    """Persistent worker that processes fragmentation tasks in a dedicated thread"""

    progressChanged = pyqtSignal(int, str)  # progress, task_id
    finished = pyqtSignal(object, str)      # result, task_id
    error = pyqtSignal(str, str)           # error_message, task_id
    cacheHit = pyqtSignal()                # Signal for cache hit
    cacheMiss = pyqtSignal()               # Signal for cache miss

    def __init__(self, fragment_cache=None):
        super().__init__()
        if fragment_cache is not None:
            if not isinstance(fragment_cache, OrderedDict):
                fragment_cache = OrderedDict(fragment_cache)
            self.fragment_cache = fragment_cache
        else:
            self.fragment_cache = OrderedDict()
        self.task_queue = queue.Queue()
        self.current_task = None
        self.should_stop = False
        self.mutex = QMutex()
        self.wait_condition = QWaitCondition()
        self.is_processing = False

    def add_task(self, task):
        """Add a new fragmentation task to the queue"""
        # Clear any pending tasks and add the new one (latest request wins)
        while not self.task_queue.empty():
            try:
                self.task_queue.get_nowait()
            except queue.Empty:
                break

        self.task_queue.put(task)

        # Wake up the worker if it's waiting
        self.mutex.lock()
        self.wait_condition.wakeOne()
        self.mutex.unlock()

    def stop_worker(self):
        """Stop the worker gracefully"""
        logger.debug("PersistentFragmentationWorker stop_worker called")
        self.should_stop = True

        # Wake up the worker if it's waiting
        self.mutex.lock()
        self.wait_condition.wakeAll()
        self.mutex.unlock()

        logger.debug("Worker stop signal sent")

    def run(self):
        """Main worker loop with proper stop handling"""
        logger.debug("Persistent worker started")

        while not self.should_stop:
            task = None

            # Check stop condition before waiting
            if self.should_stop:
                break

            # Wait for a task or stop signal with shorter timeout
            if self.task_queue.empty():
                self.mutex.lock()
                if not self.should_stop and self.task_queue.empty():
                    # Use shorter wait time to check stop condition more frequently
                    self.wait_condition.wait(self.mutex, 1000)  # 1 second
                self.mutex.unlock()

                # Check stop condition after waiting
                if self.should_stop:
                    break
                continue

            # Get task
            try:
                task = self.task_queue.get_nowait()
            except queue.Empty:
                continue

            if task is None or self.should_stop:
                break

            self.current_task = task
            self.is_processing = True

            try:
                # Check stop condition before processing
                if self.should_stop:
                    break

                self._process_task(task)
            except Exception as e:
                if not self.should_stop:  # Only emit error if not stopping
                    logger.error("Error processing task %s: %s", task.task_id, e)
                    self.error.emit(str(e), task.task_id)
            finally:
                self.current_task = None
                self.is_processing = False

        logger.debug("Persistent worker stopped")

    def _process_task(self, task):
        """Process a single fragmentation task"""
        try:
            self.progressChanged.emit(10, task.task_id)

            # Generate cache key
            cache_key = self._generate_cache_key(task)
            # Check cache
            cached_result = self.fragment_cache.get(cache_key)
            if cached_result is not None:
                logger.debug("Cache hit: using cached fragments for task %s", task.task_id)
                calculated_ions = cached_result.copy()
                # Move to end to mark as recently used (LRU)
                self.fragment_cache.move_to_end(cache_key)
                self.progressChanged.emit(50, task.task_id)
                self.cacheHit.emit()  # Emit cache hit signal
            else:
                logger.debug("Cache miss: calculating new fragments for task %s", task.task_id)
                self.cacheMiss.emit()  # Emit cache miss signal

                self.progressChanged.emit(20, task.task_id)

                calculated_ions = calculate_fragment_ions(
                    task.peptide,
                    task.modifications,
                    task.max_charge,
                    task.selected_ions,
                    task.selected_internal_ions,
                    task.custom_ion_series_list,
                    max_neutral_losses=task.max_neutral_losses,
                    calculate_isotopes=task.calculate_isotopes,
                    mod_neutral_losses=task.mod_neutral_losses
                )

                self.progressChanged.emit(35, task.task_id)

                calculated_ions = filter_ions(calculated_ions)

                # Cache the result with size management
                self.fragment_cache[cache_key] = calculated_ions.copy()
                self._manage_cache_size()
                self.progressChanged.emit(50, task.task_id)

            # Add diagnostic ions
            extra_rows = []
            for (ion_name, mass_val, color) in task.diagnostic_ions:
                extra_rows.append({
                    "Theoretical Mass": mass_val,
                    "Ion Number": "",
                    "Ion Type": ion_name,
                    "Fragment Sequence": "",
                    "Neutral Loss": "None",
                    "Charge": 1,
                    "Isotope": 0,
                    "Color": color,
                    "Base Type": None,
                    "Ion Series Type": "Diagnostic-Ion"
                })

            if extra_rows:
                df_custom = pd.DataFrame(extra_rows, columns=calculated_ions.columns)
                combined_df = pd.concat([calculated_ions, df_custom], ignore_index=True)
            else:
                combined_df = calculated_ions

            # Store theoretical data
            theoretical_data = combined_df.copy()
            self.progressChanged.emit(60, task.task_id)

            # Perform matching
            matched_data = match_fragment_ions(
                combined_df.to_dict(orient='records'),
                task.user_mz_values,
                task.ppm_tolerance
            )

            self.progressChanged.emit(90, task.task_id)

            # Emit result
            result = (matched_data, theoretical_data)
            self.progressChanged.emit(100, task.task_id)
            self.finished.emit(result, task.task_id)

        except Exception as e:
            self.error.emit(str(e), task.task_id)

    def _generate_cache_key(self, task):
        """Generate cache key for the task"""

        key_data = {
            'peptide': task.peptide,
            'modifications': sorted(task.modifications) if task.modifications else [],
            'max_charge': task.max_charge,
            'selected_ions': sorted(task.selected_ions) if task.selected_ions else [],
            'selected_internal_ions': sorted(task.selected_internal_ions) if task.selected_internal_ions else [],
            'custom_ion_series': sorted([
                (ion.get('name', ''), ion.get('base', ''), ion.get('offset', 0), ion.get('restriction', ''))
                for ion in task.custom_ion_series_list
            ]) if task.custom_ion_series_list else [],
            'max_neutral_losses': task.max_neutral_losses,
            'calculate_isotopes': task.calculate_isotopes,
            'mod_neutral_losses': str(task.mod_neutral_losses) if task.mod_neutral_losses else None,
        }

        key_string = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(key_string.encode()).hexdigest()

    def _manage_cache_size(self, max_cache_size=100):
        """Manage cache size using LRU eviction"""
        while len(self.fragment_cache) > max_cache_size:
            evicted_key, _ = self.fragment_cache.popitem(last=False)  # evict LRU (oldest accessed)
            logger.debug("Cache eviction: cache size now %d", len(self.fragment_cache))


class PersistentFragmentationManager(QObject):
    """Manager for the persistent fragmentation worker thread"""

    progressChanged = pyqtSignal(int)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    cacheHit = pyqtSignal()    # Forward cache hit signals
    cacheMiss = pyqtSignal()   # Forward cache miss signals

    def __init__(self, fragment_cache=None):
        super().__init__()
        if fragment_cache is not None:
            if not isinstance(fragment_cache, OrderedDict):
                fragment_cache = OrderedDict(fragment_cache)
            self.fragment_cache = fragment_cache
        else:
            self.fragment_cache = OrderedDict()
        self.worker = None
        self.worker_thread = None
        self.current_task_id = None
        self.task_counter = 0
        self._setup_worker()

    def _setup_worker(self):
        """Setup the persistent worker thread"""
        if self.worker_thread is not None:
            self._cleanup_worker()

        # Create worker and thread with shared cache
        self.worker = PersistentFragmentationWorker(self.fragment_cache)
        self.worker_thread = QThread()

        # Move worker to thread
        self.worker.moveToThread(self.worker_thread)

        # Connect signals
        self.worker_thread.started.connect(self.worker.run)
        self.worker.progressChanged.connect(self._on_worker_progress)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.error.connect(self._on_worker_error)
        self.worker.cacheHit.connect(self.cacheHit.emit)
        self.worker.cacheMiss.connect(self.cacheMiss.emit)

        # Start the thread
        self.worker_thread.start()
        logger.debug("Persistent manager: worker thread started")

    def submit_task(self, peptide, modifications, max_charge, ppm_tolerance,
                   selected_ions, selected_internal_ions, user_mz_values,
                   diagnostic_ions, custom_ion_series_list, max_neutral_losses=1,
                   calculate_isotopes=True, mod_neutral_losses=None):
        """Submit a new fragmentation task"""
        self.task_counter += 1
        task_id = f"task_{self.task_counter}"
        self.current_task_id = task_id

        task = FragmentationTask(
            task_id, peptide, modifications, max_charge, ppm_tolerance,
            selected_ions, selected_internal_ions, user_mz_values,
            diagnostic_ions, custom_ion_series_list, max_neutral_losses,
            calculate_isotopes, mod_neutral_losses
        )

        if self.worker is None:
            self._setup_worker()

        self.worker.add_task(task)
        return task_id

    def _on_worker_progress(self, progress, task_id):
        """Handle progress updates from worker"""
        if task_id == self.current_task_id:
            self.progressChanged.emit(progress)

    def _on_worker_finished(self, result, task_id):
        """Handle completion from worker"""
        if task_id == self.current_task_id:
            self.finished.emit(result)

    def _on_worker_error(self, error_message, task_id):
        """Handle errors from worker"""
        if task_id == self.current_task_id:
            self.error.emit(error_message)

    def _cleanup_worker(self):
        """Clean up the worker thread"""
        if self.worker is not None:
            self.worker.stop_worker()

        if self.worker_thread is not None and self.worker_thread.isRunning():
            self.worker_thread.quit()
            if not self.worker_thread.wait(3000):  # Wait up to 3 seconds
                logger.warning("Worker thread did not finish cleanly")
                self.worker_thread.terminate()
                self.worker_thread.wait(1000)

        self.worker = None
        self.worker_thread = None

    def shutdown(self):
        """Properly shutdown the manager and worker thread"""
        logger.debug("PersistentFragmentationManager shutdown called")

        if self.worker_thread and self.worker_thread.isRunning():
            logger.debug("Stopping worker thread...")

            # Signal the worker to stop
            if self.worker:
                self.worker.stop_worker()

            # Quit the thread event loop
            self.worker_thread.quit()

            # Wait for thread to finish with timeout
            if not self.worker_thread.wait(2000):  # 2 second timeout
                logger.warning("Worker thread didn't quit gracefully, terminating...")
                self.worker_thread.terminate()
                self.worker_thread.wait(1000)  # Wait 1 more second after terminate

            logger.debug("Worker thread stopped")

        # Clean up references
        self.worker = None
        self.worker_thread = None
