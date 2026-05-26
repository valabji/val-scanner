"""Every QThread in valscanner.gui.workers must satisfy the worker contract:
- subclass has a stop() method
- subclass has an error = Signal(str) attribute
"""


def test_workers_satisfy_contract():
    from valscanner.gui import workers
    import inspect
    from PySide6.QtCore import QThread

    subclasses = [
        (name, obj)
        for name, obj in inspect.getmembers(workers, inspect.isclass)
        if issubclass(obj, QThread) and obj is not QThread
    ]
    assert subclasses, "expected at least one QThread subclass in workers"

    for name, obj in subclasses:
        assert hasattr(obj, "stop"), f"{name} missing stop()"
        assert hasattr(obj, "error"), f"{name} missing error signal"
