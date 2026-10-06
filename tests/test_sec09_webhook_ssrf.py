"""SEC-09: webhook SSRF guard must reject every non-public resolved address."""

import socket

import pytest

from services import webhooks


def _fake_resolver(*addrs):
    def fake(host, port, *a, **k):
        return [(socket.AF_INET6 if ":" in x else socket.AF_INET, socket.SOCK_STREAM, 6, "", (x, port))
                for x in addrs]
    return fake


@pytest.mark.parametrize("addr", [
    "100.64.0.1", "100.100.100.200", "100.127.255.254",   # CGNAT
    "10.0.0.1", "172.16.5.5", "192.168.1.1", "127.0.0.1", "169.254.169.254",
    "0.0.0.0", "224.0.0.1", "240.0.0.1", "192.0.0.8", "198.18.0.1",
    "::1", "::", "fe80::1", "fc00::1", "ff02::1",
    "::ffff:127.0.0.1", "::ffff:100.100.100.200", "::ffff:10.0.0.1",
    "2002:7f00:0001::1",            # 6to4 embedding 127.0.0.1
    "64:ff9b::a00:1",               # NAT64 embedding 10.0.0.1
])
def test_non_public_addresses_rejected(addr, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_resolver(addr))
    assert webhooks._resolve_safe_ips("https://hook.example.com/x") is None


def test_any_private_address_among_several_rejects(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_resolver("8.8.8.8", "100.64.0.9"))
    assert webhooks._resolve_safe_ips("https://hook.example.com/x") is None


@pytest.mark.parametrize("addr", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111", "::ffff:8.8.8.8"])
def test_public_addresses_allowed(addr, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_resolver(addr))
    assert webhooks._resolve_safe_ips("https://hook.example.com/x") == [addr]
