#! /usr/bin/env python3

import sys

from datetime import datetime
import logging

from PyQt5.QtCore import (
    pyqtSignal,
    QFile,
    QTimer,
    Qt,
    QObject,
    QSettings,
    QTextStream,
    QItemSelection,
    QCoreApplication,
)
from PyQt5.QtGui import QStandardItemModel, QStandardItem, QIcon
from PyQt5.QtWidgets import (
    QMainWindow,
    QMessageBox,
    QWidget,
    QApplication,
    QMenu,
    QDialog,
)

from asyncua import ua
from asyncua.sync import SyncNode

from uaclient.uaclient import UaClient
from uaclient.mainwindow_ui import Ui_MainWindow
from uaclient.connection_dialog import ConnectionDialog
from uaclient.application_certificate_dialog import ApplicationCertificateDialog
from uaclient.graphwidget import GraphUI
from uaclient.live_tree_model import LiveTreeModel

# must be here for resources even if not used
from uawidgets import resources  # noqa: F401
from uawidgets.attrs_widget import AttrsWidget
from uawidgets.tree_widget import TreeWidget
from uawidgets.refs_widget import RefsWidget
from uawidgets.utils import trycatchslot
from uawidgets.logger import QtHandler
from uawidgets.call_method_dialog import CallMethodDialog


logger = logging.getLogger(__name__)


class DataChangeHandler(QObject):

    def __init__(self, node_signal_dict):
        super(DataChangeHandler, self).__init__()
        self.node_signal_dict = node_signal_dict

    data_change_fired = pyqtSignal(object, str, str)

    def datachange_notification(self, node, val, data):
        if data.monitored_item.Value.SourceTimestamp:
            dato = data.monitored_item.Value.SourceTimestamp.isoformat()
        elif data.monitored_item.Value.ServerTimestamp:
            dato = data.monitored_item.Value.ServerTimestamp.isoformat()
        else:
            dato = datetime.now().isoformat()
        self.node_signal_dict[str(node)].signal.emit(node, val, dato)


class EventHandler(QObject):
    event_fired = pyqtSignal(object)

    def event_notification(self, event):
        self.event_fired.emit(event)


class EventUI(object):

    def __init__(self, window, uaclient):
        self.window = window
        self.uaclient = uaclient
        self._handler = EventHandler()
        self._subscribed_nodes = []  # FIXME: not really needed
        self.model = QStandardItemModel()
        self.window.ui.evView.setModel(self.model)
        self.window.ui.actionSubscribeEvent.triggered.connect(self._subscribe)
        self.window.ui.actionUnsubscribeEvents.triggered.connect(self._unsubscribe)
        # context menu
        self.window.addAction(self.window.ui.actionSubscribeEvent)
        self.window.addAction(self.window.ui.actionUnsubscribeEvents)
        self.window.addAction(self.window.ui.actionAddToGraph)
        self._handler.event_fired.connect(
            self._update_event_model, type=Qt.QueuedConnection
        )

        # accept drops
        self.model.canDropMimeData = self.canDropMimeData
        self.model.dropMimeData = self.dropMimeData

    def canDropMimeData(self, mdata, action, row, column, parent):
        return True

    def show_error(self, *args):
        self.window.show_error(*args)

    def dropMimeData(self, mdata, action, row, column, parent):
        node = self.uaclient.client.get_node(mdata.text())
        self._subscribe(node)
        return True

    def clear(self):
        self._subscribed_nodes = []
        self.model.clear()

    @trycatchslot
    def _subscribe(self, node=None):
        logger.info("Subscribing to %s", node)
        if not node:
            node = self.window.get_current_node()
            if node is None:
                return
        if node in self._subscribed_nodes:
            logger.info("already subscribed to event for node: %s", node)
            return
        logger.info("Subscribing to events for %s", node)
        self.window.ui.evDockWidget.raise_()
        try:
            self.uaclient.subscribe_events(node, self._handler)
        except Exception as ex:
            self.window.show_error(ex)
            raise
        else:
            self._subscribed_nodes.append(node)

    @trycatchslot
    def _unsubscribe(self):
        node = self.window.get_current_node()
        if node is None:
            return
        self._subscribed_nodes.remove(node)
        self.uaclient.unsubscribe_events(node)

    @trycatchslot
    def _update_event_model(self, event):
        self.model.appendRow([QStandardItem(str(event))])


class DataChangeSubscriptionManager(object):

    def __init__(self, window, uaclient):
        self.window = window
        self.uaclient = uaclient
        self._subscribed_nodes = []

    def clear(self):
        self._subscribed_nodes = []

    def show_error(self, *args):
        self.window.show_error(*args)

    @trycatchslot
    def _subscribe(self, node=None):
        if not isinstance(node, SyncNode):
            node = self.window.get_current_node()
            if node is None:
                return
        if node in self._subscribed_nodes:
            return
        try:
            self.uaclient.subscribe_datachange(node, self.window._subhandler)

        except Exception as ex:
            if type(ex) is ua.uaerrors.BadAttributeIdInvalid:
                return
            return ex

        self._subscribed_nodes.append(node)

    @trycatchslot
    def _unsubscribe(self, node):
        if node is None:
            node = self.window.get_current_node()
        try:
            self._subscribed_nodes.remove(node)
            self.uaclient.unsubscribe_datachange(node)
        except Exception as ex:
            if type(ex) is ValueError:
                return
            logger.error(ex)

    def _update_subscription_model(self, node, value, timestamp):
        i = 0
        while self.model.item(i):
            item = self.model.item(i)
            if item.data() == node:
                it = self.model.item(i, 1)
                it.setText(value)
                it_ts = self.model.item(i, 2)
                it_ts.setText(timestamp)
            i += 1


class Window(QMainWindow):

    def __init__(self):
        QMainWindow.__init__(self)
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.setWindowIcon(QIcon(":/network.svg"))

        # fix stuff imposible to do in qtdesigner
        # remove dock titlebar for addressbar
        w = QWidget()
        self.ui.addrDockWidget.setTitleBarWidget(w)
        # tabify some docks
        self.tabifyDockWidget(self.ui.evDockWidget, self.ui.subDockWidget)
        self.tabifyDockWidget(self.ui.subDockWidget, self.ui.refDockWidget)
        self.tabifyDockWidget(self.ui.refDockWidget, self.ui.graphDockWidget)

        # we only show statusbar in case of errors
        self.ui.statusBar.hide()

        # setup QSettings for application and get a settings object
        QCoreApplication.setOrganizationName("FreeOpcUa")
        QCoreApplication.setApplicationName("OpcUaClient")
        self.settings = QSettings()

        self._address_list = self.settings.value(
            "address_list",
            [
                "opc.tcp://localhost:4840",
                "opc.tcp://localhost:53530/OPCUA/SimulationServer/",
            ],
        )
        print("ADR", self._address_list)
        self._address_list_max_count = int(
            self.settings.value("address_list_max_count", 10)
        )

        # init widgets
        for addr in self._address_list:
            self.ui.addrComboBox.insertItem(100, addr)

        self.uaclient = UaClient()

        self.node_signal_dict = {}
        self.setup_context_menu_tree()
        self.tree_ui = TreeWidget(self.ui.treeView)
        self.data_change_manager = DataChangeSubscriptionManager(self, self.uaclient)
        self.tree_ui.model = LiveTreeModel(
            self.uaclient, self.node_signal_dict, self.data_change_manager
        )
        self.tree_ui.model.setHorizontalHeaderLabels(
            ["DisplayName", "BrowseName", "NodeId", "Value", "Description", "DataType"]
        )
        self.tree_ui.view.setModel(self.tree_ui.model)

        self.tree_ui.error.connect(self.show_error)

        self.ui.treeView.selectionModel().currentChanged.connect(
            self._update_actions_state
        )
        self.refs_ui = RefsWidget(self.ui.refView)
        self.refs_ui.error.connect(self.show_error)
        self.attrs_ui = AttrsWidget(self.ui.attrView)
        self.attrs_ui.error.connect(self.show_error)

        self.event_ui = EventUI(self, self.uaclient)
        self.graph_ui = GraphUI(self, self.uaclient)

        self._subhandler = DataChangeHandler(self.node_signal_dict)
        self.ui.addrComboBox.currentTextChanged.connect(self._uri_changed)
        self._uri_changed(
            self.ui.addrComboBox.currentText()
        )  # force update for current value at startup

        self.ui.treeView.selectionModel().selectionChanged.connect(self.show_refs)
        self.ui.actionCopyPath.triggered.connect(self.tree_ui.copy_path)
        self.ui.actionCopyNodeId.triggered.connect(self.tree_ui.copy_nodeid)
        self.ui.actionCall.triggered.connect(self.call_method)

        self.ui.treeView.selectionModel().selectionChanged.connect(self.show_attrs)
        self.ui.attrRefreshButton.clicked.connect(self.show_attrs)

        self.resize(
            int(self.settings.value("main_window_width", 800)),
            int(self.settings.value("main_window_height", 600)),
        )
        data = self.settings.value("main_window_state", None)
        if data:
            self.restoreState(data)
        self.ui.connectButton.clicked.connect(self.connect)
        self.ui.disconnectButton.clicked.connect(self.disconnect)
        # self.ui.treeView.expanded.connect(self._fit)

        self.ui.actionConnect.triggered.connect(self.connect)
        self.ui.actionDisconnect.triggered.connect(self.disconnect)

        self.ui.connectOptionButton.clicked.connect(self.show_connection_dialog)
        self.ui.actionClient_Application_Certificate.triggered.connect(
            self.show_application_certificate_dialog
        )
        self.ui.actionDark_Mode.triggered.connect(self.dark_mode)

        self.tree_ui.model.description_datatype_added.connect(
            self.tree_ui.model.update_description_and_data_type
        )

        self.ui.treeView.expanded.connect(self.tree_ui.model.tree_expanded)
        self.attrs_ui.view.expanded.connect(self._attrs_item_expanded)
        self.ui.treeView.collapsed.connect(self.tree_ui.model.tree_collapsed)

    def _attrs_item_expanded(self, idx):
        if self.attrs_ui.current_node:
            nodeId = str(self.attrs_ui.current_node)
            if nodeId in self.node_signal_dict:
                self.node_signal_dict[nodeId].signal.connect(
                    self._attrs_reload_value_and_timestamp
                )

    def _remove_children(self, item):
        while item.hasChildren():
            if item.child(0):
                item.removeRow(0)
            else:
                break

    def _attrs_reload_value_and_timestamp(self, node, value, timestamp):
        if self.attrs_ui.current_node == node:
            parent_value = self.attrs_ui.model.findItems("Value")[0]
            child_value = parent_value.child(0)
            child_value.setText("Value")
            if isinstance(value, list):
                self._remove_children(child_value)
                self.attrs_ui._show_list(
                    child_value,
                    value,
                    parent_value.child(0, 1).data(Qt.UserRole).uatype,
                )
            elif (
                parent_value.child(0, 1).data(Qt.UserRole).uatype
                == ua.VariantType.ExtensionObject
            ):
                self._remove_children(child_value)
                self.attrs_ui._show_ext_obj(child_value, value)
            else:
                parent_value.child(0, 1).setText(str(value))
            parent_value.child(2, 1).setText(timestamp)

    def _uri_changed(self, uri):
        self.uaclient.load_security_settings(uri)

    def show_connection_dialog(self):
        dia = ConnectionDialog(self, self.ui.addrComboBox.currentText())
        dia.security_mode = self.uaclient.security_mode
        dia.security_policy = self.uaclient.security_policy
        dia.certificate_path = self.uaclient.user_certificate_path
        dia.private_key_path = self.uaclient.user_private_key_path
        ret = dia.exec_()
        if ret:
            self.uaclient.security_mode = dia.security_mode
            self.uaclient.security_policy = dia.security_policy
            self.uaclient.user_certificate_path = dia.certificate_path
            self.uaclient.user_private_key_path = dia.private_key_path

    def show_application_certificate_dialog(self):
        dia = ApplicationCertificateDialog(self)
        dia.certificate_path = self.uaclient.application_certificate_path
        dia.private_key_path = self.uaclient.application_private_key_path
        ret = dia.exec_()
        if ret == QDialog.Accepted:
            self.uaclient.application_certificate_path = dia.certificate_path
            self.uaclient.application_private_key_path = dia.private_key_path
        self.uaclient.save_application_certificate_settings()

    @trycatchslot
    def show_refs(self, selection):
        if isinstance(selection, QItemSelection):
            if not selection.indexes():  # no selection
                return

        node = self.get_current_node()
        if node:
            self.refs_ui.show_refs(node)

    @trycatchslot
    def show_attrs(self, selection):
        if isinstance(selection, QItemSelection):
            if not selection.indexes():  # no selection
                return

        node = self.get_current_node()
        if node:
            self.attrs_ui.show_attrs(node)

    def show_error(self, msg):
        logger.warning("showing error: %s")
        self.ui.statusBar.show()
        self.ui.statusBar.setStyleSheet(
            "QStatusBar { background-color : red; color : black; }"
        )
        self.ui.statusBar.showMessage(str(msg))
        QTimer.singleShot(1500, self.ui.statusBar.hide)

    def get_current_node(self, idx=None):
        return self.tree_ui.get_current_node(idx)

    def get_uaclient(self):
        return self.uaclient

    @trycatchslot
    def connect(self):
        uri = self.ui.addrComboBox.currentText()
        uri = uri.strip()
        try:
            self.uaclient.connect(uri)
        except Exception as ex:
            self.show_error(ex)
            raise

        self._update_address_list(uri)
        self.tree_ui.set_root_node(self.uaclient.client.nodes.root)
        self.ui.treeView.setFocus()
        self.load_current_node()

    def _update_address_list(self, uri):
        if uri == self._address_list[0]:
            return
        if uri in self._address_list:
            self._address_list.remove(uri)
        self._address_list.insert(0, uri)
        if len(self._address_list) > self._address_list_max_count:
            self._address_list.pop(-1)

    def disconnect(self):
        try:
            self.uaclient.disconnect()
        except Exception as ex:
            self.show_error(ex)
            raise
        finally:
            self.save_current_node()
            self.tree_ui.clear()
            self.refs_ui.clear()
            self.attrs_ui.clear()
            self.data_change_manager.clear()
            self.event_ui.clear()

    def closeEvent(self, event):
        self.tree_ui.save_state()
        self.attrs_ui.save_state()
        self.refs_ui.save_state()
        self.settings.setValue("main_window_width", self.size().width())
        self.settings.setValue("main_window_height", self.size().height())
        self.settings.setValue("main_window_state", self.saveState())
        self.settings.setValue("address_list", self._address_list)
        self.disconnect()
        event.accept()

    def save_current_node(self):
        current_node = self.tree_ui.get_current_node()
        if current_node:
            mysettings = self.settings.value("current_node", None)
            if mysettings is None:
                mysettings = {}
            uri = self.ui.addrComboBox.currentText()
            mysettings[uri] = current_node.nodeid.to_string()
            self.settings.setValue("current_node", mysettings)

    def load_current_node(self):
        mysettings = self.settings.value("current_node", None)
        if mysettings is None:
            return
        uri = self.ui.addrComboBox.currentText()
        if uri in mysettings:
            nodeid = ua.NodeId.from_string(mysettings[uri])
            node = self.uaclient.client.get_node(nodeid)
            self.tree_ui.expand_to_node(node)

    def setup_context_menu_tree(self):
        self.ui.treeView.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ui.treeView.customContextMenuRequested.connect(
            self._show_context_menu_tree
        )
        self._contextMenu = QMenu()
        self.addAction(self.ui.actionCopyPath)
        self.addAction(self.ui.actionCopyNodeId)
        self._contextMenu.addSeparator()
        self._contextMenu.addAction(self.ui.actionCall)
        self._contextMenu.addSeparator()

    def addAction(self, action):
        self._contextMenu.addAction(action)

    @trycatchslot
    def _update_actions_state(self, current, previous):
        node = self.get_current_node(current)
        self.ui.actionCall.setEnabled(False)
        if node:
            if node.read_node_class() == ua.NodeClass.Method:
                self.ui.actionCall.setEnabled(True)

    def _show_context_menu_tree(self, position):
        node = self.tree_ui.get_current_node()
        if node:
            self._contextMenu.exec_(self.ui.treeView.viewport().mapToGlobal(position))

    def call_method(self):
        node = self.get_current_node()
        dia = CallMethodDialog(self, self.uaclient.client, node)
        dia.show()

    def dark_mode(self):
        self.settings.setValue("dark_mode", self.ui.actionDark_Mode.isChecked())

        msg = QMessageBox()
        msg.setIcon(QMessageBox.Information)
        msg.setText("Restart for changes to take effect")
        msg.exec_()


def main():
    app = QApplication(sys.argv)
    client = Window()
    handler = QtHandler(client.ui.logTextEdit)
    logging.getLogger().addHandler(handler)
    logging.getLogger("uaclient").setLevel(logging.INFO)
    logging.getLogger("uawidgets").setLevel(logging.INFO)
    # logging.getLogger("opcua").setLevel(logging.INFO)  # to enable logging of ua client library

    # set stylesheet
    if QSettings().value("dark_mode", "false") == "true":
        file = QFile(":/dark.qss")
        file.open(QFile.ReadOnly | QFile.Text)
        stream = QTextStream(file)
        app.setStyleSheet(stream.readAll())

    client.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
