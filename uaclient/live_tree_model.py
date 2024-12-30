import logging

from PyQt5.QtCore import (
    pyqtSignal,
    Qt,
    QObject,
    QRunnable,
    QThreadPool,
)
from PyQt5.QtGui import QStandardItem, QIcon

from asyncua import ua
from asyncua.sync import SyncNode, new_node
from asyncua.common.ua_utils import data_type_to_string

from uawidgets.tree_widget import TreeViewModel


logger = logging.getLogger(__name__)


class DescriptionDataTypeLoader(QObject):
    def update_description_and_data_type(self, node, description, data_type):
        attrs = node.read_attributes(
            [ua.AttributeIds.Description, ua.AttributeIds.DataType]
        )
        description.setText(attrs[0].Value.Value.Text)
        if attrs[1].Value.Value:
            data_type.setText(data_type_to_string(attrs[1].Value.Value))


class NodeValueItem(QStandardItem):
    def __init__(self, value):
        super(NodeValueItem, self).__init__(value)

    def update_value(self, node, val, data):
        self.setText(str(val))


class NodeSubscriptionSignal(QObject):
    signal = pyqtSignal(object, object, str)

    def __init__(self):
        QObject.__init__(self)


class SubscriptionHandler(QObject):
    unsubscribe_started = pyqtSignal()
    unsubscribe_ended = pyqtSignal()
    subscribe_started = pyqtSignal()
    subscribe_ended = pyqtSignal()

    def __init__(self, model, idx):
        QObject.__init__(self)
        self.model = model
        self.idx = idx
        self.is_subscribe_running = False
        self.is_unsubscribe_running = False

        self.is_expanded = False
        self.unsubscribe_is_waiting = False
        self.subscribe_is_waiting = False
        self.subscribe_ended.connect(self.after_subscribe)

    def relaunch_subscribe(self, index):
        self.model.threadpool.start(SubscribeWorker(self.idx, self.model, self, index))

    def after_subscribe(self):
        if self.unsubscribe_is_waiting and not self.is_expanded:
            self.model.threadpool.start(UnsubscribeWorker(self.idx, self.model, self))


class SubscribeWorker(QRunnable):
    def __init__(self, idx, model, subscription_handler, last_unsubscribed=-1):
        super().__init__()
        self.idx = idx
        self.model = model
        self.uaclient = model.uaclient
        self.data_change_manager = model.data_change_manager
        self.subscription_handler = subscription_handler
        self.last_unsubscribed = last_unsubscribed

    def run(self):
        self.subscription_handler.subscribe_started.emit()
        self.subscription_handler.is_subscribe_running = True
        if self.subscription_handler.is_unsubscribe_running:
            return
        idx = self.idx
        item = self.model.itemFromIndex(idx)
        i = 0
        while True:
            child = item.child(i)
            if child is None or i == self.last_unsubscribed:
                break
            index = item.child(i).index()
            childNodeId = self.model.data(index.sibling(index.row(), 2))
            childNode = self.uaclient.client.get_node(childNodeId)
            res = self.data_change_manager._subscribe(childNode)
            if res:
                logger.error(res)
                break
            i = i + 1
        self.subscription_handler.is_subscribe_running = False
        self.subscription_handler.subscribe_ended.emit()


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


class DescriptionDatatypeWorker(QRunnable):
    def __init__(self, node, description, data_type):
        super().__init__()
        self.node = node
        self.description = description
        self.data_type = data_type

    def run(self):
        attrs = self.node.read_attributes(
            [ua.AttributeIds.Description, ua.AttributeIds.DataType]
        )
        self.description.setText(attrs[0].Value.Value.Text)
        if attrs[1].Value.Value:
            self.data_type.setText(data_type_to_string(attrs[1].Value.Value))


class LiveTreeModel(TreeViewModel):
    item_added = pyqtSignal(SyncNode)
    item_removed = pyqtSignal(SyncNode)

    description_datatype_added = pyqtSignal(object, object, object)

    def __init__(self, uaclient, node_signal_dict, data_change_manager):
        TreeViewModel.__init__(self)
        self.uaclient = uaclient
        self.test_item = 0
        self.node_signal_dict = node_signal_dict
        self.threadpool = QThreadPool()
        self.data_change_manager = data_change_manager
        self.subscription_handlers = {}

    def set_root_node(self, node):
        desc = self._get_node_desc(node, is_root=True)
        self.add_item(desc, node=node, is_root=True)

    def _get_node_desc(self, node, is_root=False):
        attrs = node.read_attributes(
            [
                ua.AttributeIds.DisplayName,
                ua.AttributeIds.BrowseName,
                ua.AttributeIds.NodeId,
                ua.AttributeIds.NodeClass,
            ]
        )
        desc = ua.ReferenceDescription()
        desc.DisplayName = attrs[0].Value.Value
        desc.BrowseName = attrs[1].Value.Value
        desc.NodeId = attrs[2].Value.Value
        desc.NodeClass = attrs[3].Value.Value
        if is_root:
            desc.TypeDefinition = ua.TwoByteNodeId(ua.ObjectIds.FolderType)
        return desc

    def tree_expanded(self, idx):
        if idx not in self.subscription_handlers:
            self.subscription_handlers[idx] = SubscriptionHandler(self, idx)

        self.subscription_handlers[idx].is_expanded = True

        if self.subscription_handlers[idx].is_subscribe_running:
            return
        self.threadpool.start(
            SubscribeWorker(idx, self, self.subscription_handlers[idx])
        )

    def tree_collapsed(self, idx):
        self.subscription_handlers[idx].is_expanded = False
        unsubscribe_worker = UnsubscribeWorker(
            idx, self, self.subscription_handlers[idx]
        )
        self.threadpool.start(unsubscribe_worker)

    def update_description_and_data_type(self, node, description, data_type):
        worker = DescriptionDatatypeWorker(node, description, data_type)
        self.threadpool.start(worker)

    def add_item(self, desc, parent=None, node=None, is_root=False):
        dname = bname = nodeid = "No Value"
        dtype = value = description = None

        if not node:
            node = self.uaclient.get_node(desc.NodeId)

        if value == "None":
            value = ""
        if description == "no description":
            description = ""

        if desc.DisplayName:
            dname = desc.DisplayName.Text
        if desc.BrowseName:
            bname = desc.BrowseName.to_string()
        nodeid = desc.NodeId.to_string()
        item = [
            QStandardItem(dname),
            QStandardItem(bname),
            QStandardItem(nodeid),
            NodeValueItem(""),
            QStandardItem(description),
            QStandardItem(dtype),
        ]
        if desc.NodeClass == ua.NodeClass.Object:
            if desc.TypeDefinition == ua.TwoByteNodeId(ua.ObjectIds.FolderType):
                item[0].setIcon(QIcon(":/folder.svg"))
            else:
                item[0].setIcon(QIcon(":/object.svg"))
        elif desc.NodeClass == ua.NodeClass.Variable:
            if desc.TypeDefinition == ua.TwoByteNodeId(ua.ObjectIds.PropertyType):
                item[0].setIcon(QIcon(":/property.svg"))
            else:
                item[0].setIcon(QIcon(":/variable.svg"))
        elif desc.NodeClass == ua.NodeClass.Method:
            item[0].setIcon(QIcon(":/method.svg"))
        elif desc.NodeClass == ua.NodeClass.ObjectType:
            item[0].setIcon(QIcon(":/object_type.svg"))
        elif desc.NodeClass == ua.NodeClass.VariableType:
            item[0].setIcon(QIcon(":/variable_type.svg"))
        elif desc.NodeClass == ua.NodeClass.DataType:
            item[0].setIcon(QIcon(":/data_type.svg"))
        elif desc.NodeClass == ua.NodeClass.ReferenceType:
            item[0].setIcon(QIcon(":/reference_type.svg"))

        if is_root:
            item[0].setData(node, Qt.UserRole)
        else:
            parent_node = parent.data(Qt.UserRole)
            item[0].setData(new_node(parent_node, desc.NodeId), Qt.UserRole)

        self.node_signal_dict[nodeid] = NodeSubscriptionSignal()
        self.node_signal_dict[nodeid].signal.connect(item[3].update_value)
        self.description_datatype_added.emit(node, item[4], item[5])
        if parent:
            return parent.appendRow(item)
        else:
            return self.appendRow(item)
