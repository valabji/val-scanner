"""Automated proxies for the manual checks in UX steps 13.6 and 5.4.

Step 13.6 calls for dragging file rows to Finder/Explorer; the underlying
contract is that `mimeData()` returns `text/uri-list` + plain text with
the right paths. We test that contract directly.

Step 5.4 calls for a VoiceOver pass; the underlying contract is that
every named interactive control exposes a non-empty `accessibleName`.
We assert that on a curated list per panel/dialog.
"""

from __future__ import annotations

import pytest


@pytest.mark.usefixtures("qapp")
def test_file_table_mime_data_single_row():
    from PySide6.QtCore import QModelIndex
    from valscanner.gui.models import FileTableModel

    m = FileTableModel()
    m.load([("/tmp/a.txt", "a.txt", "doc", 10, "10 B", "", "tag", "", "")])

    idx = m.index(0, 0)
    md = m.mimeData([idx])

    assert md.hasUrls()
    urls = md.urls()
    assert len(urls) == 1
    assert urls[0].toLocalFile() == "/tmp/a.txt"
    assert md.hasText()
    assert md.text() == "/tmp/a.txt"


@pytest.mark.usefixtures("qapp")
def test_file_table_mime_data_multi_row_dedups():
    from valscanner.gui.models import FileTableModel

    m = FileTableModel()
    m.load([
        ("/tmp/a.txt", "a.txt", "doc",   10, "10 B", "", "t", "", ""),
        ("/tmp/b.txt", "b.txt", "doc",   20, "20 B", "", "t", "", ""),
        ("/tmp/c.txt", "c.txt", "image", 30, "30 B", "", "t", "", ""),
    ])
    indexes = [m.index(r, c) for r in (0, 1, 2) for c in range(3)]
    md = m.mimeData(indexes)

    paths = [u.toLocalFile() for u in md.urls()]
    assert paths == ["/tmp/a.txt", "/tmp/b.txt", "/tmp/c.txt"]
    assert md.text().split("\n") == paths


@pytest.mark.usefixtures("qapp")
def test_file_table_mime_data_skips_group_headers():
    from valscanner.gui.models import FileTableModel

    m = FileTableModel()
    m.load([
        ("group://hdr", "Header", "__group__", 0, "", "", "", "", ""),
        ("/tmp/a.txt",  "a.txt",  "doc",       10, "10 B", "", "t", "", ""),
    ])
    indexes = [m.index(0, 0), m.index(1, 0)]
    md = m.mimeData(indexes)

    assert [u.toLocalFile() for u in md.urls()] == ["/tmp/a.txt"]


@pytest.mark.usefixtures("qapp")
def test_file_icon_model_mime_data():
    from valscanner.gui.models import FileIconModel

    m = FileIconModel()
    m.load([
        ("/tmp/a.png", "a.png", "image", 10, "10 B", "", "t", "", ""),
        ("/tmp/b.png", "b.png", "image", 20, "20 B", "", "t", "", ""),
    ])
    idxs = [m.index(0), m.index(1)]
    md = m.mimeData(idxs)

    assert [u.toLocalFile() for u in md.urls()] == ["/tmp/a.png", "/tmp/b.png"]


@pytest.mark.usefixtures("qapp")
def test_folder_tree_mime_data_returns_urls():
    """FolderPanel's tree model should produce file URLs for drag-out."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QStandardItem
    from valscanner.gui.panels.folders import FolderPanel

    panel = FolderPanel()
    model = panel.tree.model().sourceModel() if hasattr(panel.tree.model(), "sourceModel") else panel.tree.model()

    item = QStandardItem("things")
    item.setData("/tmp/things", Qt.UserRole)
    model.invisibleRootItem().appendRow(item)

    idx = model.indexFromItem(item)
    md = model.mimeData([idx])

    assert md.hasUrls()
    assert md.urls()[0].toLocalFile() == "/tmp/things"
    panel.deleteLater()


@pytest.mark.usefixtures("qapp")
def test_detail_panel_accessible_names():
    """Step 5: detail-panel interactive controls expose accessibleName."""
    from valscanner.gui.panels.detail import DetailPanel

    p = DetailPanel()
    for attr in ("open_btn", "sample_btn", "meta_text"):
        w = getattr(p, attr, None)
        assert w is not None, f"DetailPanel missing {attr}"
        assert w.accessibleName(), f"DetailPanel.{attr} has empty accessibleName"
    p.deleteLater()


@pytest.mark.usefixtures("qapp")
def test_scans_panel_accessible_names():
    from valscanner.gui.panels.scans import ScansPanel

    p = ScansPanel()
    for attr in ("table", "_del_btn", "_show_all_btn"):
        w = getattr(p, attr, None)
        assert w is not None, f"ScansPanel missing {attr}"
        assert w.accessibleName(), f"ScansPanel.{attr} has empty accessibleName"
    p.deleteLater()


@pytest.mark.usefixtures("qapp")
def test_folder_panel_accessible_names():
    from valscanner.gui.panels.folders import FolderPanel

    p = FolderPanel()
    assert p.tree.accessibleName(), "FolderPanel.tree has empty accessibleName"
    p.deleteLater()


@pytest.mark.usefixtures("qapp")
def test_console_panel_accessible_names():
    from valscanner.gui.panels.console import ConsolePanel

    p = ConsolePanel()
    for attr in ("_output", "_clear_btn"):
        w = getattr(p, attr, None)
        assert w is not None, f"ConsolePanel missing {attr}"
        assert w.accessibleName(), f"ConsolePanel.{attr} has empty accessibleName"
    p.deleteLater()


@pytest.mark.usefixtures("qapp")
def test_similar_panel_accessible_names():
    from valscanner.gui.panels.similar import SimilarFoldersPanel

    p = SimilarFoldersPanel()
    for attr in (
        "min_spin", "thresh_combo", "filters_btn", "history_btn",
        "analyze_btn", "sort_combo", "min_size_combo",
    ):
        w = getattr(p, attr, None)
        assert w is not None, f"SimilarFoldersPanel missing {attr}"
        assert w.accessibleName(), f"SimilarFoldersPanel.{attr} has empty accessibleName"
    p.deleteLater()


@pytest.mark.usefixtures("qapp")
def test_scan_options_dialog_accessible_names():
    from valscanner.gui.dialogs import ScanOptionsDialog

    d = ScanOptionsDialog()
    for attr in ("thumb_size", "thumb_quality", "sample_dur"):
        w = getattr(d, attr, None)
        assert w is not None, f"ScanOptionsDialog missing {attr}"
        assert w.accessibleName(), f"ScanOptionsDialog.{attr} has empty accessibleName"
    d.deleteLater()
