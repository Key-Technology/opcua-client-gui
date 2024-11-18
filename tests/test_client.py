
import pytest

from asyncua.sync import Server

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest

from uaclient.mainwindow import Window


class TestClient:
    @pytest.fixture
    def resources(self, qtbot):
        self.server = Server()
        url = "opc.tcp://localhost:48400/freeopcua/server/"
        self.server.set_endpoint(url)
        self.server.start()
        self.client = Window()
        qtbot.addWidget = self.client
        self.client.ui.addrComboBox.setCurrentText(url)
        self.client.connect()
        yield
        self.client.disconnect()
        self.server.stop()

    def get_attr_value(self, text):
        idxlist = self.client.attrs_ui.model.match(self.client.attrs_ui.model.index(0, 0), Qt.DisplayRole, text,  1, Qt.MatchExactly | Qt.MatchRecursive)
        idx = idxlist[0]
        idx = idx.sibling(idx.row(), 1)
        item = self.client.attrs_ui.model.itemFromIndex(idx)
        return item.data(Qt.UserRole).value

    def test_select_objects(self, resources):
        objects = self.server.nodes.objects
        self.client.tree_ui.expand_to_node(objects)
        assert objects == self.client.tree_ui.get_current_node()
        assert self.client.attrs_ui.model.rowCount() >  6
        assert self.client.refs_ui.model.rowCount() > 1

        data = self.get_attr_value("NodeId")
        assert data == objects.nodeid

    def test_select_server_node(self, resources):
        server_node = self.server.nodes.server
        self.client.tree_ui.expand_to_node(server_node)
        assert server_node ==  self.client.tree_ui.get_current_node()
        assert self.client.attrs_ui.model.rowCount() > 6
        assert self.client.refs_ui.model.rowCount() > 10

        data = self.get_attr_value("NodeId")
        assert data == server_node.nodeid
