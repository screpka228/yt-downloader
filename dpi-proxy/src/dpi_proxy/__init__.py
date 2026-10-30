"""Локальный прокси с обходом DPI. Публичный интерфейс пакета."""
from .core import (
    DEFAULT_METHOD,
    METHODS,
    TARGET_DOMAINS,
    DpiProxy,
    build_segments,
    configure_file_logging,
    find_free_port,
    find_sni,
    is_target,
    probe,
    split_tls_record,
)

__all__ = [
    "DEFAULT_METHOD",
    "METHODS",
    "TARGET_DOMAINS",
    "DpiProxy",
    "build_segments",
    "configure_file_logging",
    "find_free_port",
    "find_sni",
    "is_target",
    "probe",
    "split_tls_record",
]
__version__ = "0.1.0"
