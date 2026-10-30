"""Тесты пакета dpi_proxy. Запуск: python -m unittest discover -s tests -v (из папки dpi-proxy)."""
import socket
import struct
import unittest

import requests

from dpi_proxy import DpiProxy, build_segments, find_sni, is_target, probe, split_tls_record


def make_client_hello(sni: str) -> bytes:
    """Собирает минимальный корректный TLS ClientHello с расширением server_name."""
    name = sni.encode("ascii")
    server_name = struct.pack(">BH", 0, len(name)) + name
    ext = struct.pack(">HH", 0x0000, len(server_name) + 2) + struct.pack(">H", len(server_name)) + server_name
    body = (
        b"\x03\x03"  # версия
        + bytes(32)  # random
        + b"\x00"  # session_id: пусто
        + struct.pack(">H", 2) + b"\x13\x01"  # один набор шифров
        + b"\x01\x00"  # сжатие: null
        + struct.pack(">H", len(ext)) + ext
    )
    handshake = b"\x01" + struct.pack(">I", len(body))[1:] + body
    return b"\x16\x03\x01" + struct.pack(">H", len(handshake)) + handshake


class SniTests(unittest.TestCase):
    def test_find_sni_returns_name_position(self):
        hello = make_client_hello("www.youtube.com")
        start, length = find_sni(hello)
        self.assertEqual(hello[start : start + length], b"www.youtube.com")

    def test_find_sni_rejects_non_tls(self):
        self.assertIsNone(find_sni(b"GET / HTTP/1.1\r\n\r\n"))
        self.assertIsNone(find_sni(b""))

    def test_find_sni_on_truncated_data(self):
        self.assertIsNone(find_sni(make_client_hello("a.example")[:20]))


class SplitTests(unittest.TestCase):
    def test_tls_record_split_keeps_payload(self):
        hello = make_client_hello("www.youtube.com")
        start, length = find_sni(hello)
        cut = start + length // 2
        first, second = split_tls_record(hello, cut)
        # Каждая запись имеет свой корректный заголовок
        self.assertEqual(first[:3], b"\x16\x03\x01")
        self.assertEqual(second[:3], b"\x16\x03\x01")
        self.assertEqual(struct.unpack(">H", first[3:5])[0], len(first) - 5)
        self.assertEqual(struct.unpack(">H", second[3:5])[0], len(second) - 5)
        # Склеенные тела совпадают с исходным телом
        self.assertEqual(first[5:] + second[5:], hello[5:])
        # Граница записей попадает внутрь имени сервера: часть имени в каждой записи
        self.assertTrue(first.endswith(hello[start : cut]))
        self.assertTrue(second[5:].startswith(hello[cut : start + length]))

    def test_build_segments_methods(self):
        hello = make_client_hello("www.youtube.com")
        self.assertEqual(build_segments(hello, "none"), [hello])
        split = build_segments(hello, "split")
        self.assertEqual(len(split), 2)
        self.assertEqual(split[0] + split[1], hello)
        tlsrec = build_segments(hello, "tlsrec")
        self.assertEqual(len(tlsrec), 1)
        both = build_segments(hello, "tlsrec+split")
        self.assertEqual(len(both), 2)
        self.assertEqual(both[0][:3], b"\x16\x03\x01")

    def test_non_tls_passes_through(self):
        data = b"hello"
        self.assertEqual(build_segments(data, "tlsrec+split"), [data])


class TargetTests(unittest.TestCase):
    def test_domains_and_subdomains(self):
        self.assertTrue(is_target("youtube.com", False))
        self.assertTrue(is_target("rr3---sn-abc.googlevideo.com", False))
        self.assertFalse(is_target("example.com", False))
        self.assertTrue(is_target("example.com", True))


class EndToEndTests(unittest.TestCase):
    """Сквозные тесты: прокси реально пересылает трафик к example.com."""

    @classmethod
    def setUpClass(cls):
        cls.proxy = DpiProxy(port=18080, method="tlsrec+split", all_hosts=True)
        cls.port = cls.proxy.start()

    @classmethod
    def tearDownClass(cls):
        cls.proxy.stop()

    def test_http_connect(self):
        response = requests.get(
            "https://example.com/",
            proxies={"https": f"http://127.0.0.1:{self.port}"},
            timeout=20,
        )
        self.assertEqual(response.status_code, 200)

    def test_socks5(self):
        response = requests.get(
            "https://example.com/",
            proxies={"https": f"socks5h://127.0.0.1:{self.port}"},
            timeout=20,
        )
        self.assertEqual(response.status_code, 200)

    def test_plain_http_get(self):
        response = requests.get(
            "http://example.com/",
            proxies={"http": f"http://127.0.0.1:{self.port}"},
            timeout=20,
        )
        self.assertEqual(response.status_code, 200)

    def test_probe_helper(self):
        results = probe(f"http://127.0.0.1:{self.port}", ["https://example.com/"], timeout=20)
        self.assertTrue(results[0][1])


class StartStopTests(unittest.TestCase):
    def test_busy_port_moves_to_next(self):
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.bind(("127.0.0.1", 18300))
        blocker.listen()
        try:
            proxy = DpiProxy(port=18300)
            port = proxy.start()
            self.assertNotEqual(port, 18300)
            proxy.stop()
        finally:
            blocker.close()

    def test_unknown_method_rejected(self):
        with self.assertRaises(ValueError):
            DpiProxy(method="magic")


if __name__ == "__main__":
    unittest.main()
