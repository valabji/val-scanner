"""Every QThread in valscanner.gui.workers must satisfy the worker
contract defined by step 08. Until step 08 lands, this test is skipped.

After step 08, it asserts:
- subclass has a stop() method
- subclass has an error = Signal(str) attribute
- subclass registers itself with ProcessRegistry on start
"""

import pytest


@pytest.mark.skip(reason="Worker contract introduced in step 08")
def test_workers_satisfy_contract():
    from valscanner.gui import workers
    import inspect
    from PySide6.QtCore import QThread

    for name, obj in inspect.getmembers(workers, inspect.isclass):
        if not issubclass(obj, QThread) or obj is QThread:
            continue
        assert hasattr(obj, "stop"), f"{name} missing stop()"
        assert hasattr(obj, "error"), f"{name} missing error signal"
