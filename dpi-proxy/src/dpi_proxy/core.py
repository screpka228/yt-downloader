"""Асинхронный локальный прокси с обходом DPI.

Пакет не зависит от интерфейса: только asyncio и стандартная библиотека.
Прокси слушает 127.0.0.1 и принимает SOCKS5 (без авторизации, CONNECT) и HTTP
(CONNECT и обычный GET). Для TLS-соединений к нужным доменам первый пакет
ClientHello режется так, что DPI не может прочитать имя сервера (SNI).
Сервер собирает пакет сам, поэтому соединение работает.
"""
import asyncio
import logging
import socket
import struct
import threading
import time
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlsplit

METHODS = ("none", "split", "tlsrec", "tlsrec+split")
DEFAULT_METHOD = "tlsrec+split"
TARGET_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "googlevideo.com",
    "ytimg.com",
    "ggpht.com",
    "youtubei.googleapis.com",
    "googleusercontent.com",
)
CONNECT_TIMEOUT = 10  # секунд на подключение к целевому серверу
FIRST_PACKET_TIMEOUT = 5  # секунд на ожидание первого пакета от клиента
SPLIT_DELAY = 0.01  # пауза между частями пакета, секунд
BUFFER = 65536

log = logging.getLogger("dpi_proxy")
log.addHandler(logging.NullHandler())


def configure_file_logging(path: Path, max_bytes: int = 512 * 1024, backups: int = 2) -> None:
    """Пишет лог в файл с ограничением размера. Вызывать один раз."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


# ---------- Разбор и разрезание TLS ----------


def find_sni(data: bytes) -> tuple[int, int] | None:
    """Ищет имя сервера (SNI) в TLS ClientHello.

    Возвращает (смещение, длину) имени внутри data или None, если это не ClientHello.
    """
    try:
        if len(data) < 6 or data[0] != 0x16 or data[5] != 0x01:
            return None
        pos = 9  # 5 байт заголовка записи + 4 байта заголовка рукопожатия
        pos += 2 + 32  # версия и random
        pos += 1 + data[pos]  # session_id
        (cipher_len,) = struct.unpack_from(">H", data, pos)
        pos += 2 + cipher_len
        pos += 1 + data[pos]  # методы сжатия
        (ext_total,) = struct.unpack_from(">H", data, pos)
        pos += 2
        end = min(pos + ext_total, len(data))
        while pos + 4 <= end:
            ext_type, ext_len = struct.unpack_from(">HH", data, pos)
            pos += 4
            if ext_type == 0x0000:  # server_name: список(2), тип имени(1), длина(2), имя
                (name_len,) = struct.unpack_from(">H", data, pos + 3)
                name_start = pos + 5
                if name_len > 0 and name_start + name_len <= len(data):
                    return name_start, name_len
                return None
            pos += ext_len
    except (IndexError, struct.error):
        return None
    return None


def split_tls_record(data: bytes, cut: int) -> list[bytes] | None:
    """Делит одну TLS-запись на две записи с границей в позиции cut (смещение в data).

    Возвращает None, если data не является одной полной записью или cut вне тела записи.
    """
    if len(data) < 5 or data[0] != 0x16:
        return None
    (length,) = struct.unpack_from(">H", data, 3)
    if len(data) != 5 + length:
        return None
    p = cut - 5  # граница внутри тела записи
    if not 0 < p < length:
        return None
    head = data[0:3]  # тип записи и версия TLS
    first = head + struct.pack(">H", p) + data[5 : 5 + p]
    second = head + struct.pack(">H", length - p) + data[5 + p :]
    return [first, second]


def build_segments(data: bytes, method: str) -> list[bytes]:
    """Режет первый пакет клиента на части для отправки.

    Если метод не задан, SNI не найден или пакет не удалось разрезать, возвращает пакет целиком.
    """
    sni = find_sni(data)
    if method == "none" or sni is None:
        return [data]
    start, length = sni
    cut = start + length // 2  # разрез посередине имени сервера
    if method == "split":
        return [data[:cut], data[cut:]]
    records = split_tls_record(data, cut)
    if records is None:
        return [data]
    if method == "tlsrec":
        return [b"".join(records)]
    if method == "tlsrec+split":
        return records  # две записи, отправляются двумя TCP-сегментами
    return [data]


def is_target(host: str, all_hosts: bool) -> bool:
    """Нужно ли обходить DPI для этого хоста."""
    if all_hosts:
        return True
    host = host.lower().rstrip(".")
    return any(host == domain or host.endswith("." + domain) for domain in TARGET_DOMAINS)


def find_free_port(start: int, attempts: int = 50) -> int:
    """Первый свободный порт на 127.0.0.1, начиная с start."""
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise OSError(f"нет свободного порта, начиная с {start}")


# ---------- Сервер ----------


@dataclass
class _Request:
    host: str
    port: int
    kind: str  # "socks", "connect" или "plain"
    prefix: bytes  # для plain: переписанная голова HTTP-запроса


def _parse_http_head(head: bytes) -> _Request | None:
    line_end = head.index(b"\r\n")
    method, target, version = head[:line_end].decode("latin-1").split(" ", 2)
    if method.upper() == "CONNECT":
        host, _, port = target.rpartition(":")
        return _Request(host.strip("[]"), int(port or 443), "connect", b"")
    parts = urlsplit(target)
    if not parts.hostname:
        return None
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    rewritten = f"{method} {path} {version}".encode("latin-1") + head[line_end:]
    return _Request(parts.hostname, parts.port or 80, "plain", rewritten)


async def _send_segments(writer: asyncio.StreamWriter, segments: list[bytes], method: str) -> None:
    for index, segment in enumerate(segments):
        writer.write(segment)
        await writer.drain()
        if index < len(segments) - 1 and method in ("split", "tlsrec+split"):
            await asyncio.sleep(SPLIT_DELAY)


async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await src.read(BUFFER)
            if not data:
                break
            dst.write(data)
            await dst.drain()
    except (OSError, ConnectionError):
        pass
    finally:
        dst.close()


class DpiProxy:
    """Прокси, который работает в своём потоке с собственным циклом asyncio.

    Использование:
        proxy = DpiProxy(port=1080, method="tlsrec+split")
        proxy.start()          # возвращает фактический порт
        ...
        proxy.stop()
    Метод и all_hosts можно менять на ходу: новые соединения используют новые значения.
    """

    def __init__(self, port: int = 1080, method: str = DEFAULT_METHOD, all_hosts: bool = False):
        if method not in METHODS:
            raise ValueError(f"неизвестный метод обхода: {method}")
        self.preferred_port = port
        self.port: int | None = None
        self.method = method
        self.all_hosts = all_hosts
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._server: asyncio.base_events.Server | None = None

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self) -> int:
        if self.running:
            return self.port
        self.port = find_free_port(self.preferred_port)
        ready = threading.Event()
        errors: list[Exception] = []

        def run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            try:
                server = loop.run_until_complete(
                    asyncio.start_server(self._handle, "127.0.0.1", self.port)
                )
            except OSError as exc:
                errors.append(exc)
                ready.set()
                loop.close()
                return
            self._server = server
            ready.set()
            loop.run_forever()
            server.close()
            loop.run_until_complete(server.wait_closed())
            loop.close()

        self._thread = threading.Thread(target=run, name="dpi-proxy", daemon=True)
        self._thread.start()
        ready.wait(5)
        if errors or not self.running:
            reason = errors[0] if errors else "таймаут запуска"
            self._server = None
            raise OSError(f"не удалось запустить прокси на порту {self.port}: {reason}")
        log.info("прокси запущен на 127.0.0.1:%s, метод %s", self.port, self.method)
        return self.port

    def stop(self) -> None:
        if not self.running:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(5)
        self._server = None
        self._loop = None
        log.info("прокси остановлен")

    # ----- обработка клиента -----

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        upstream: asyncio.StreamWriter | None = None
        try:
            request = await asyncio.wait_for(self._read_request(reader, writer), CONNECT_TIMEOUT)
            if request is None:
                return
            try:
                up_reader, up_writer = await asyncio.wait_for(
                    asyncio.open_connection(request.host, request.port), CONNECT_TIMEOUT
                )
            except (OSError, asyncio.TimeoutError) as exc:
                log.warning("%s -> %s:%s: не удалось подключиться (%s)", peer, request.host, request.port, exc)
                self._reply_failure(writer, request.kind)
                return
            upstream = up_writer
            log.info("%s -> %s:%s (%s)", peer, request.host, request.port, request.kind)

            if request.kind == "plain":
                up_writer.write(request.prefix)
                await up_writer.drain()
            else:
                self._reply_success(writer, request.kind)
                await writer.drain()
                await self._relay_first_packet(reader, up_writer, request.host, peer)

            await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))
        except asyncio.TimeoutError:
            log.info("%s: таймаут", peer)
        except (OSError, ValueError, asyncio.IncompleteReadError, UnicodeError) as exc:
            log.info("%s: ошибка соединения (%s)", peer, exc)
        finally:
            writer.close()
            if upstream is not None:
                upstream.close()

    async def _read_request(self, reader, writer) -> _Request | None:
        first = await reader.readexactly(1)
        if first == b"\x05":
            return await self._socks5_handshake(reader, writer)
        head = first + await reader.readuntil(b"\r\n\r\n")
        return _parse_http_head(head)

    async def _socks5_handshake(self, reader, writer) -> _Request | None:
        nmethods = (await reader.readexactly(1))[0]
        await reader.readexactly(nmethods)
        writer.write(b"\x05\x00")  # без авторизации
        await writer.drain()
        _ver, cmd, _rsv, atyp = await reader.readexactly(4)
        if cmd != 0x01:  # поддерживаем только CONNECT
            writer.write(bytes([5, 0x07, 0, 1, 0, 0, 0, 0, 0, 0]))
            return None
        if atyp == 0x01:
            host = socket.inet_ntop(socket.AF_INET, await reader.readexactly(4))
        elif atyp == 0x04:
            host = socket.inet_ntop(socket.AF_INET6, await reader.readexactly(16))
        elif atyp == 0x03:
            length = (await reader.readexactly(1))[0]
            host = (await reader.readexactly(length)).decode("utf-8", "replace")
        else:
            writer.write(bytes([5, 0x08, 0, 1, 0, 0, 0, 0, 0, 0]))
            return None
        (port,) = struct.unpack(">H", await reader.readexactly(2))
        return _Request(host, port, "socks", b"")

    @staticmethod
    def _reply_success(writer, kind: str) -> None:
        if kind == "socks":
            writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        else:
            writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")

    @staticmethod
    def _reply_failure(writer, kind: str) -> None:
        if kind == "socks":
            writer.write(bytes([5, 0x04, 0, 1, 0, 0, 0, 0, 0, 0]))
        else:
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")

    async def _relay_first_packet(self, reader, up_writer, host: str, peer) -> None:
        """Читает первый пакет клиента и при необходимости режет ClientHello."""
        try:
            first = await asyncio.wait_for(reader.read(BUFFER), FIRST_PACKET_TIMEOUT)
        except asyncio.TimeoutError:
            return  # клиент молчит (не TLS): дальше просто пересылаем байты
        if not first:
            return
        target = host
        sni = find_sni(first)
        if sni is not None:
            target = first[sni[0] : sni[0] + sni[1]].decode("ascii", "replace")
        if first[0] == 0x16 and self.method != "none" and is_target(target, self.all_hosts):
            segments = build_segments(first, self.method)
            log.info("%s -> %s: обход DPI методом %s, частей: %d", peer, target, self.method, len(segments))
            await _send_segments(up_writer, segments, self.method)
        else:
            up_writer.write(first)
            await up_writer.drain()


# ---------- Проверка соединения ----------


def probe(proxy: str, urls: list[str], timeout: float = 10) -> list[tuple[str, bool, int, str]]:
    """Запрашивает urls через прокси. Возвращает список (url, успех, мс, пояснение).

    Требует пакет requests (установите extra [probe]).
    """
    import requests

    proxies = {"http": proxy, "https": proxy} if proxy else None  # без прокси — напрямую
    results = []
    for url in urls:
        started = time.monotonic()
        try:
            response = requests.get(url, proxies=proxies, timeout=timeout)
            ms = int((time.monotonic() - started) * 1000)
            results.append((url, response.status_code < 400, ms, f"HTTP {response.status_code}"))
        except requests.RequestException as exc:
            ms = int((time.monotonic() - started) * 1000)
            results.append((url, False, ms, type(exc).__name__))
    return results
