"""Interaction tests for Beta promotion: selection, delete-with-undo,
view-mode switch, similarity-card flow.

These tests exercise behaviour beyond the construction smoke in
test_panels.py — they drive panels through their user-visible actions
to lock the contracts down before we move 3 → 4 (Beta).
"""

from __future__ import annotations

import pytest


# -----------------------------------------------------------------------------
# Selection — ExtendedSelection multi-row select on the file table
# -----------------------------------------------------------------------------

def _load_three_rows():
    from valscanner.gui.models import FileTableModel

    m = FileTableModel()
    m.load([
        ("/tmp/a.txt", "a.txt", "doc",   10, "10 B",  "", "t", "", ""),
        ("/tmp/b.txt", "b.txt", "doc",   20, "20 B",  "", "t", "", ""),
        ("/tmp/c.txt", "c.txt", "image", 30, "30 B",  "", "t", "", ""),
    ])
    return m


def _table_view(model):
    from PySide6.QtWidgets import QAbstractItemView, QTableView

    v = QTableView()
    v.setModel(model)
    v.setSelectionMode(QAbstractItemView.ExtendedSelection)
    v.setSelectionBehavior(QAbstractItemView.SelectRows)
    return v


@pytest.mark.usefixtures("qapp")
def test_file_table_extended_selection_multi_row():
    from PySide6.QtCore import QItemSelection, QItemSelectionModel

    model = _load_three_rows()
    view = _table_view(model)
    sm   = view.selectionModel()
    sel  = QItemSelection(model.index(0, 0), model.index(2, model.columnCount() - 1))
    sm.select(sel, QItemSelectionModel.Select | QItemSelectionModel.Rows)

    rows = sorted({i.row() for i in sm.selectedRows()})
    assert rows == [0, 1, 2]

    sm.clearSelection()
    assert sm.selectedRows() == []
    view.deleteLater()


@pytest.mark.usefixtures("qapp")
def test_file_table_single_row_selection_replaces_previous():
    from PySide6.QtCore import QItemSelectionModel

    model = _load_three_rows()
    view  = _table_view(model)
    sm    = view.selectionModel()

    sm.select(model.index(0, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
    sm.select(model.index(2, 0),
              QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)

    rows = [i.row() for i in sm.selectedRows()]
    assert rows == [2]
    view.deleteLater()


@pytest.mark.usefixtures("qapp")
def test_file_table_select_all_via_view():
    """QTableView.selectAll() is what Ctrl+A is wired to in MainWindow."""
    model = _load_three_rows()
    view  = _table_view(model)

    view.selectAll()
    rows = sorted({i.row() for i in view.selectionModel().selectedRows()})
    assert rows == [0, 1, 2]
    view.deleteLater()


@pytest.mark.usefixtures("qapp")
def test_file_icon_view_selection_currentchanged_signal():
    """Grid view emits currentChanged so the detail panel can update."""
    from PySide6.QtWidgets import QListView, QAbstractItemView
    from valscanner.gui.models import FileIconModel

    model = FileIconModel()
    model.load([
        ("/tmp/a.png", "a.png", "image", 10, "10 B", "", "t", "", ""),
        ("/tmp/b.png", "b.png", "image", 20, "20 B", "", "t", "", ""),
    ])
    view = QListView()
    view.setModel(model)
    view.setSelectionMode(QAbstractItemView.ExtendedSelection)

    seen: list[int] = []
    view.selectionModel().currentChanged.connect(
        lambda cur, _prev: seen.append(cur.row())
    )

    view.setCurrentIndex(model.index(1))
    assert seen and seen[-1] == 1
    view.deleteLater()


# -----------------------------------------------------------------------------
# Delete-with-undo — ScansPanel commit / undo / status emission
# -----------------------------------------------------------------------------

@pytest.fixture
def seeded_db(tmp_path):
    """A DB with three scan rows ready for delete tests."""
    from valscanner.core.bootstrap import ensure_schema
    from valscanner.core.db import repo_for, list_scans

    db_path = tmp_path / "scans.db"
    url = f"sqlite:///{db_path}"
    ensure_schema(url)
    repo = repo_for(url)
    for label in ("alpha", "beta", "gamma"):
        repo.create_scan(root=f"/data/{label}", label=label)
    assert len(list_scans(url)) == 3
    return url


@pytest.mark.usefixtures("qapp")
def test_scans_panel_delete_commit_emits_status(seeded_db, monkeypatch):
    from PySide6.QtCore import QItemSelection, QItemSelectionModel
    from valscanner.core.db import list_scans
    from valscanner.gui.panels import scans as scans_mod
    from valscanner.gui.panels.scans import ScansPanel

    monkeypatch.setattr(scans_mod, "confirm_destructive", lambda *a, **kw: True)
    monkeypatch.setattr(scans_mod, "undo_toast", lambda *a, **kw: None)

    panel = ScansPanel()
    panel.load(seeded_db)
    assert panel._model.rowCount() == 3

    messages: list[tuple[str, str]] = []
    panel.status_message.connect(lambda m, l: messages.append((m, l)))

    sel = QItemSelection(panel._model.index(0, 0), panel._model.index(0, 5))
    panel.table.selectionModel().select(
        sel, QItemSelectionModel.Select | QItemSelectionModel.Rows,
    )

    panel._delete_selected()
    assert panel._pending_ids and panel._pending_timer is not None
    pending = list(panel._pending_ids)

    panel._commit_delete(pending)
    assert panel._pending_ids == []
    assert len(list_scans(seeded_db)) == 2

    levels = [lvl for _, lvl in messages]
    assert "success" in levels
    panel.deleteLater()


@pytest.mark.usefixtures("qapp")
def test_scans_panel_undo_restores_rows(seeded_db, monkeypatch):
    from PySide6.QtCore import QItemSelection, QItemSelectionModel
    from valscanner.core.db import list_scans
    from valscanner.gui.panels import scans as scans_mod
    from valscanner.gui.panels.scans import ScansPanel

    monkeypatch.setattr(scans_mod, "confirm_destructive", lambda *a, **kw: True)
    monkeypatch.setattr(scans_mod, "undo_toast", lambda *a, **kw: None)

    panel = ScansPanel()
    panel.load(seeded_db)

    messages: list[tuple[str, str]] = []
    panel.status_message.connect(lambda m, l: messages.append((m, l)))

    sel = QItemSelection(panel._model.index(0, 0), panel._model.index(1, 5))
    panel.table.selectionModel().select(
        sel, QItemSelectionModel.Select | QItemSelectionModel.Rows,
    )

    panel._delete_selected()
    assert len(panel._pending_ids) == 2

    panel._undo_delete()
    assert panel._pending_ids == []
    assert panel._pending_timer is None
    assert len(list_scans(seeded_db)) == 3
    assert any(lvl == "warning" for _, lvl in messages)
    panel.deleteLater()


@pytest.mark.usefixtures("qapp")
def test_scans_panel_delete_cancelled_by_confirm_dialog(seeded_db, monkeypatch):
    """If the destructive-confirm dialog returns False, nothing pends."""
    from PySide6.QtCore import QItemSelection, QItemSelectionModel
    from valscanner.core.db import list_scans
    from valscanner.gui.panels import scans as scans_mod
    from valscanner.gui.panels.scans import ScansPanel

    monkeypatch.setattr(scans_mod, "confirm_destructive", lambda *a, **kw: False)
    toast_called = {"n": 0}
    def _track_toast(*a, **kw):
        toast_called["n"] += 1
    monkeypatch.setattr(scans_mod, "undo_toast", _track_toast)

    panel = ScansPanel()
    panel.load(seeded_db)

    sel = QItemSelection(panel._model.index(0, 0), panel._model.index(0, 5))
    panel.table.selectionModel().select(
        sel, QItemSelectionModel.Select | QItemSelectionModel.Rows,
    )

    panel._delete_selected()
    assert panel._pending_ids == []
    assert panel._pending_timer is None
    assert toast_called["n"] == 0
    assert len(list_scans(seeded_db)) == 3
    panel.deleteLater()


@pytest.mark.usefixtures("qapp")
def test_scans_panel_delete_with_no_selection_is_noop(seeded_db, monkeypatch):
    from valscanner.core.db import list_scans
    from valscanner.gui.panels import scans as scans_mod
    from valscanner.gui.panels.scans import ScansPanel

    confirm_calls = {"n": 0}
    def _confirm(*a, **kw):
        confirm_calls["n"] += 1
        return True
    monkeypatch.setattr(scans_mod, "confirm_destructive", _confirm)
    monkeypatch.setattr(scans_mod, "undo_toast", lambda *a, **kw: None)

    panel = ScansPanel()
    panel.load(seeded_db)

    panel._delete_selected()
    assert confirm_calls["n"] == 0
    assert panel._pending_ids == []
    assert len(list_scans(seeded_db)) == 3
    panel.deleteLater()


@pytest.mark.usefixtures("qapp")
def test_scans_panel_supersede_pending_delete(seeded_db, monkeypatch):
    """A second delete while one is pending commits the first immediately."""
    from PySide6.QtCore import QItemSelection, QItemSelectionModel
    from valscanner.core.db import list_scans
    from valscanner.gui.panels import scans as scans_mod
    from valscanner.gui.panels.scans import ScansPanel

    monkeypatch.setattr(scans_mod, "confirm_destructive", lambda *a, **kw: True)
    monkeypatch.setattr(scans_mod, "undo_toast", lambda *a, **kw: None)

    panel = ScansPanel()
    panel.load(seeded_db)

    sel1 = QItemSelection(panel._model.index(0, 0), panel._model.index(0, 5))
    panel.table.selectionModel().select(
        sel1, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
    )
    panel._delete_selected()
    first_pending = list(panel._pending_ids)
    assert len(first_pending) == 1

    sel2 = QItemSelection(panel._model.index(0, 0), panel._model.index(0, 5))
    panel.table.selectionModel().select(
        sel2, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
    )
    panel._delete_selected()

    # Supersede semantics: first batch was committed immediately when the
    # second delete fired; second batch is now the new pending set.
    assert len(list_scans(seeded_db)) == 2
    second_pending = list(panel._pending_ids)
    assert len(second_pending) == 1
    assert second_pending != first_pending

    if panel._pending_timer is not None:
        panel._pending_timer.stop()
    panel._commit_delete(panel._pending_ids)
    assert len(list_scans(seeded_db)) == 1
    panel.deleteLater()


# -----------------------------------------------------------------------------
# View-mode switch — MainWindow toggling Details/Grid/List
# -----------------------------------------------------------------------------

@pytest.mark.usefixtures("qapp")
def test_mainwindow_view_mode_switch(fixture_db):
    from valscanner.gui.window import MainWindow

    win = MainWindow()
    try:
        win._db_url = f"sqlite:///{fixture_db}"
        expected = {0: win.table, 1: win.grid_view, 2: win.list_view}
        for mode in (1, 2, 0):
            win._set_view_mode(mode)
            assert win._current_view_index == mode
            assert win._view_stack.currentWidget() is expected[mode]
    finally:
        win.close()
        win.deleteLater()


@pytest.mark.usefixtures("qapp")
def test_mainwindow_view_mode_switch_via_button_group(fixture_db):
    """Clicking a view-mode button goes through the same _set_view_mode path."""
    from valscanner.gui.window import MainWindow

    win = MainWindow()
    try:
        win._db_url = f"sqlite:///{fixture_db}"
        grid_btn = win._view_btn_grp.button(1)
        list_btn = win._view_btn_grp.button(2)
        assert grid_btn is not None and list_btn is not None

        grid_btn.click()
        assert win._current_view_index == 1
        assert win._view_stack.currentWidget() is win.grid_view

        list_btn.click()
        assert win._current_view_index == 2
        assert win._view_stack.currentWidget() is win.list_view
    finally:
        win.close()
        win.deleteLater()


# -----------------------------------------------------------------------------
# Similarity panel — selection toggle + dismiss
# -----------------------------------------------------------------------------

@pytest.mark.usefixtures("qapp")
def test_similar_panel_card_select_and_dismiss():
    from valscanner.gui.panels.similar import SimilarFoldersPanel, FolderGroupCard

    panel = SimilarFoldersPanel()
    fake_results = [
        {
            "folder_a": "/a/photos", "folder_b": "/b/photos",
            "scan_id_a": 1, "scan_id_b": 2,
            "scan_label_a": "scan1", "scan_label_b": "scan2",
            "files_a": 10, "files_b": 12,
            "bytes_a": 1000, "bytes_b": 1100,
            "score": 0.92, "label": "near-duplicate",
            "name_score": 0.9, "ext_score": 0.95, "size_score": 0.88,
            "hash_score": 0.0, "shared_names": 8, "shared_hashes": 0,
        },
        {
            "folder_a": "/a/docs", "folder_b": "/b/docs",
            "scan_id_a": 1, "scan_id_b": 2,
            "scan_label_a": "scan1", "scan_label_b": "scan2",
            "files_a": 3, "files_b": 4,
            "bytes_a": 200, "bytes_b": 250,
            "score": 0.78, "label": "related",
            "name_score": 0.7, "ext_score": 0.85, "size_score": 0.78,
            "hash_score": 0.0, "shared_names": 2, "shared_hashes": 0,
        },
    ]

    panel._on_done(fake_results)

    cards = []
    for i in range(panel.cards_lay.count()):
        w = panel.cards_lay.itemAt(i).widget()
        if isinstance(w, FolderGroupCard):
            cards.append(w)
    assert len(cards) == 2

    cards[0].set_selected(True)
    cards[0].selected_changed.emit(cards[0], True)
    assert cards[0] in panel._selected_cards
    assert panel._dismiss_sel_btn.isHidden() is False

    cards[0].set_selected(False)
    cards[0].selected_changed.emit(cards[0], False)
    assert cards[0] not in panel._selected_cards
    assert panel._dismiss_sel_btn.isHidden() is True

    cards[1].set_selected(True)
    cards[1].selected_changed.emit(cards[1], True)
    panel._dismiss_selected_cards()
    assert panel._selected_cards == []
    assert cards[1].isHidden() is True
    panel.deleteLater()


@pytest.mark.usefixtures("qapp")
def test_similar_panel_empty_results_emits_status():
    from valscanner.gui.panels.similar import SimilarFoldersPanel

    panel = SimilarFoldersPanel()
    msgs: list[tuple[str, str]] = []
    panel.status_message.connect(lambda m, l: msgs.append((m, l)))

    panel._on_done([])

    assert panel._results == []
    assert any(lvl == "success" for _, lvl in msgs)
    assert any("No similar folders" in m for m, _ in msgs)
    panel.deleteLater()


@pytest.mark.usefixtures("qapp")
def test_similar_panel_sort_change_reorders_cards(monkeypatch):
    from valscanner.gui.panels import similar as similar_mod
    from valscanner.gui.panels.similar import SimilarFoldersPanel

    build_log: list[dict] = []

    class _RecordingCard(similar_mod.FolderGroupCard):
        def __init__(self, result, is_child=False, parent=None):
            build_log.append(result)
            super().__init__(result, is_child=is_child, parent=parent)

    monkeypatch.setattr(similar_mod, "FolderGroupCard", _RecordingCard)

    panel = SimilarFoldersPanel()
    panel._on_done([
        {
            "folder_a": "/big/a", "folder_b": "/big/b",
            "scan_id_a": 1, "scan_id_b": 2,
            "scan_label_a": "s1", "scan_label_b": "s2",
            "files_a": 2, "files_b": 2,
            "bytes_a": 5_000_000, "bytes_b": 5_000_000,
            "score": 0.50, "label": "related",
            "name_score": 0.5, "ext_score": 0.5, "size_score": 0.5,
            "hash_score": 0.0, "shared_names": 1, "shared_hashes": 0,
        },
        {
            "folder_a": "/small/a", "folder_b": "/small/b",
            "scan_id_a": 1, "scan_id_b": 2,
            "scan_label_a": "s1", "scan_label_b": "s2",
            "files_a": 50, "files_b": 50,
            "bytes_a": 10, "bytes_b": 10,
            "score": 0.95, "label": "near-duplicate",
            "name_score": 0.9, "ext_score": 0.95, "size_score": 0.9,
            "hash_score": 0.0, "shared_names": 40, "shared_hashes": 0,
        },
    ])

    panel.sort_combo.setCurrentIndex(0)
    panel._apply_sort_filter()
    last_two = [r["score"] for r in build_log[-2:]]
    assert last_two == [0.95, 0.50]

    panel.sort_combo.setCurrentIndex(1)
    panel._apply_sort_filter()
    last_two_bytes = [r["total_bytes"] for r in build_log[-2:]]
    assert last_two_bytes == [10_000_000, 20]
    panel.deleteLater()
