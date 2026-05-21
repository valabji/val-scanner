"""MainWindow constructs against a fresh DB without raising."""

import pytest


@pytest.mark.usefixtures("qapp")
def test_mainwindow_constructs(fixture_db):
    from valscanner.gui.window import MainWindow

    win = MainWindow()
    try:
        assert win.windowTitle()
        assert win.centralWidget() is not None
    finally:
        win.close()
        win.deleteLater()


@pytest.mark.usefixtures("qapp")
def test_mainwindow_no_db():
    """No --db passed: window still constructs and waits for a DB."""
    from valscanner.gui.window import MainWindow

    win = MainWindow()
    try:
        assert win.centralWidget() is not None
    finally:
        win.close()
        win.deleteLater()
