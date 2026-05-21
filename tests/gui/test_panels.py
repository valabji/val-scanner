"""Construction smoke tests for every panel class.

A Qt import-time crash (typo in a stylesheet f-string, missing import)
is caught here in CI rather than at runtime.
"""

import pytest


@pytest.mark.usefixtures("qapp")
def test_detail_panel():
    from valscanner.gui.panels.detail import DetailPanel

    w = DetailPanel()
    w.deleteLater()


@pytest.mark.usefixtures("qapp")
def test_folders_panel():
    from valscanner.gui.panels.folders import FolderPanel

    w = FolderPanel()
    w.deleteLater()


@pytest.mark.usefixtures("qapp")
def test_scans_panel():
    from valscanner.gui.panels.scans import ScansPanel

    w = ScansPanel()
    w.deleteLater()


@pytest.mark.usefixtures("qapp")
def test_console_panel():
    from valscanner.gui.panels.console import ConsolePanel

    w = ConsolePanel()
    w.deleteLater()


@pytest.mark.usefixtures("qapp")
def test_similar_panel():
    from valscanner.gui.panels.similar import SimilarFoldersPanel

    w = SimilarFoldersPanel()
    w.deleteLater()


@pytest.mark.usefixtures("qapp")
def test_process_panel():
    from valscanner.gui.panels.process import ProcessPanel

    w = ProcessPanel()
    w.deleteLater()
