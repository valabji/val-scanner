from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, QRect, QSize
from PySide6.QtWidgets import QLayout, QLayoutItem, QSizePolicy, QWidgetItem


class FlowLayout(QLayout):
    """Wrapping flow layout for tag chips and similar inline widgets."""

    def __init__(self, parent=None, spacing: int = 4):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), dry_run=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, dry_run=False)

    def _do_layout(self, rect: QRect, *, dry_run: bool) -> int:
        m = self.contentsMargins()
        left = rect.x() + m.left()
        top = rect.y() + m.top()
        right = rect.right() - m.right()
        sp = self._spacing

        x = left
        y = top
        row_h = 0

        for item in self._items:
            hint = item.sizeHint()
            w, h = hint.width(), hint.height()
            if x + w > right and x > left:
                x = left
                y += row_h + sp
                row_h = 0
            if not dry_run:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += w + sp
            row_h = max(row_h, h)

        return (y - rect.y()) + row_h + m.top() + m.bottom()
