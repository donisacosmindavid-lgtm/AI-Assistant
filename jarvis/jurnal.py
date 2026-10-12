"""Jurnalul lui Jarvis: pe ecran si in logs/jarvis.log (se roteste singur)."""

import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler

from jarvis.calendar_google import FUS_ORAR
from jarvis.config import RADACINA

DOSAR_JURNAL = RADACINA / "logs"
FISIER_JURNAL = DOSAR_JURNAL / "jarvis.log"


class _OraRomaniei(logging.Formatter):
    """Scrie ora Romaniei in jurnal, oricare ar fi fusul orar al calculatorului (serverul e in SUA)."""

    def formatTime(self, record, datefmt=None):
        return datetime.fromtimestamp(record.created, FUS_ORAR).strftime(datefmt)


def porneste_jurnalul() -> logging.Logger:
    jurnal = logging.getLogger("jarvis")
    if jurnal.handlers:
        return jurnal
    jurnal.setLevel(logging.INFO)
    forma = _OraRomaniei("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    DOSAR_JURNAL.mkdir(exist_ok=True)
    in_fisier = RotatingFileHandler(
        FISIER_JURNAL, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    in_fisier.setFormatter(forma)
    jurnal.addHandler(in_fisier)

    pe_ecran = logging.StreamHandler(sys.stdout)
    pe_ecran.setFormatter(forma)
    jurnal.addHandler(pe_ecran)
    return jurnal
