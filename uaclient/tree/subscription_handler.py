from PyQt5.QtCore import pyqtSignal, QObject, QMutex
from uaclient.tree.subscribe_worker import SubscribeWorker
from uaclient.tree.unsubscribe_worker import UnsubscribeWorker


class SubscriptionHandler(QObject):
    unsubscribe_started = pyqtSignal()
    unsubscribe_ended = pyqtSignal()
    subscribe_started = pyqtSignal()
    subscribe_ended = pyqtSignal()

    def __init__(self, model, idx):
        super().__init__()
        self.model = model
        self.idx = idx
        self.is_subscribe_running = False
        self.is_unsubscribe_running = False
        self.is_expanded = False
        self.unsubscribe_is_waiting = False
        self.subscribe_is_waiting = False

        self.subscribe_ended.connect(self.after_subscribe)
        self.is_unsubscribe_running_lock = QMutex()

    def relaunch_subscribe(self, index):
        self.model.threadpool.start(SubscribeWorker(self.idx, self.model, self, index))

    def after_subscribe(self):
        if self.unsubscribe_is_waiting and not self.is_expanded:
            self.model.threadpool.start(UnsubscribeWorker(self.idx, self.model, self))