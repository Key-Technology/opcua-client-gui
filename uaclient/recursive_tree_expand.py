from PyQt5.QtCore import Qt, QRunnable


class RecursiveTreeExpand(QRunnable):

    def __init__(self, idx, window):
        super().__init__()
        self.idx = idx
        self.window = window
        self.expand = window.expand

    def run(self):
        self.window.running_expands.append(self.idx)
        item = self.window.tree_ui.model.itemFromIndex(self.idx)
        text = item.text()
        self.window.tree_ui.model.fetchMore(self.idx)
        self.expand.emit(self.idx)
        item.setText("loading...")
        children = []
        children.append(item)
        while len(children) > 0:
            child_item = children[0]
            i = 0
            if self.idx not in self.window.running_expands:
                break
            while True:
                child = child_item.child(i)
                if child is None:
                    break
                index = child.index()

                node = child.data(Qt.UserRole)
                if len(node.get_children_descriptions()) > 0:
                    if self.idx not in self.window.running_expands:
                        break
                    children.append(child)
                    self.window.tree_ui.model.fetchMore(index)
                    self.expand.emit(index)
                i = i + 1
            children.pop(0)
        if self.idx in self.window.running_expands:
            self.window.running_expands.remove(self.idx)
        item.setText(text)
