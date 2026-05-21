"""Unit tests for FlowLayout — heightForWidth math and wrapping edge cases."""

from PySide6.QtCore import QRect, QSize


def test_empty_layout_height():
    from valscanner.gui.layouts import FlowLayout

    layout = FlowLayout()
    assert layout.heightForWidth(200) >= 0


def test_single_item_height(qapp):
    from PySide6.QtWidgets import QLabel
    from valscanner.gui.layouts import FlowLayout

    container_w = QLabel()
    layout = FlowLayout(container_w)
    chip = QLabel("tag")
    layout.addWidget(chip)

    h = layout.heightForWidth(400)
    assert h >= chip.sizeHint().height()


def test_wrapping_increases_height(qapp):
    from PySide6.QtWidgets import QLabel
    from valscanner.gui.layouts import FlowLayout

    container = QLabel()
    layout = FlowLayout(container)
    for i in range(8):
        layout.addWidget(QLabel(f"tag-{i}"))

    h_wide = layout.heightForWidth(1000)
    h_narrow = layout.heightForWidth(80)
    assert h_narrow >= h_wide


def test_count_and_take(qapp):
    from PySide6.QtWidgets import QLabel, QWidgetItem
    from valscanner.gui.layouts import FlowLayout

    container = QLabel()
    layout = FlowLayout(container)
    for _ in range(3):
        layout.addWidget(QLabel("x"))

    assert layout.count() == 3
    item = layout.takeAt(0)
    assert item is not None
    assert layout.count() == 2
