from PyQt5.QtCore import QRunnable


class UnsubscribeWorker(QRunnable):
    def __init__(self, idx, model, subscription_handler):
        super().__init__()
        self.idx = idx
        self.model = model
        self.uaclient = model.uaclient
        self.data_change_manager = model.data_change_manager
        self.node_signal_dict = model.node_signal_dict
        self.idx = idx
        self.subscription_handler = subscription_handler

    def run(self):
        self.subscription_handler.is_expanded = False
        if self.subscription_handler.is_subscribe_running:
            self.subscription_handler.unsubscribe_is_waiting = True
            return
        self.subscription_handler.is_unsubscribe_running = True
        self.subscription_handler.unsubscribe_started.emit()
        item = self.model.itemFromIndex(self.idx)
        i = 0
        while True:
            if self.subscription_handler.is_expanded:
                self.subscription_handler.relaunch_subscribe(i)
                break
            child = item.child(i)
            if child is None:
                break
            index = item.child(i).index()
            childNodeId = self.model.data(index.sibling(index.row(), 2))
            childNode = self.uaclient.client.get_node(childNodeId)
            if childNodeId in self.node_signal_dict:
                self.data_change_manager._unsubscribe(childNode)
            i = i + 1
        self.subscription_handler.is_unsubscribe_running = False
        self.subscription_handler.unsubscribe_ended.emit()