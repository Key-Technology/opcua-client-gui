import pytest

from uaclient.mainwindow import EventHandler
from uaclient.uaclient import UaClient
from unittest.mock import Mock
from asyncua.sync import Subscription, Client


@pytest.fixture
def server_node(server):
    yield server.nodes.server


@pytest.fixture
def window(server_node):
    yield Mock()


@pytest.fixture
def uaclient(url):
    uaclient = UaClient()
    uaclient.connect(url)
    yield uaclient
    uaclient.disconnect()


def test_subscribe_events(uaclient, server):
    handler = EventHandler()
    server_node = server.nodes.server
    assert not uaclient._event_sub
    handler = uaclient.subscribe_events(server_node, handler)
    assert isinstance(uaclient._event_sub, Subscription)
    assert handler == uaclient._subs_ev[server_node.nodeid]


def test_save_security_settings(uaclient, url):
    uaclient.security_mode = "Basic"
    uaclient.security_policy = "Default"
    uaclient.user_certificate_path = "path/to/cert"
    uaclient.user_private_key_path = "path/to/key"
    uaclient.save_security_settings(url)
    mysettings = uaclient.settings.value("security_settings", None)
    assert mysettings[url] == [
        uaclient.security_mode,
        uaclient.security_policy,
        uaclient.user_certificate_path,
        uaclient.user_private_key_path,
    ]


def test_load_security_settings(uaclient, url):
    mysettings = uaclient.settings.value("security_settings", None)
    mysettings[url] = [
        "Basic",
        "Default",
        "path/to/cert",
        "path/to/key",
    ]
    uaclient.settings.setValue("security_settings", mysettings)
    uaclient.load_security_settings(url)
    assert uaclient.security_mode == "Basic"
    assert uaclient.security_policy == "Default"
    assert uaclient.user_certificate_path == "path/to/cert"
    assert uaclient.user_private_key_path == "path/to/key"


def test_connect(uaclient, url):
    uaclient.connect(url)
    assert isinstance(uaclient.client, Client)
    assert uaclient.client.application_uri == uaclient.application_uri
