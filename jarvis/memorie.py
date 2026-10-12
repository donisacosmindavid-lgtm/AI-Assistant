"""Tine minte, intr-un fisier SQLite, pentru ce a sunat deja Jarvis si ce are de facut."""

import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

from jarvis.calendar_google import FUS_ORAR, Eveniment
from jarvis.config import RADACINA

FISIER_DB = RADACINA / "jarvis.db"

_TABELE = """
CREATE TABLE IF NOT EXISTS apeluri (
    cheie TEXT PRIMARY KEY,
    titlu TEXT NOT NULL,
    moment TEXT NOT NULL,
    rezultat TEXT NOT NULL
);
-- Apelurile care se numara la limite (fara reincercari si fara alerta de reautorizare).
CREATE TABLE IF NOT EXISTS istoric (
    moment TEXT NOT NULL
);
-- Anunturi oprite de orele de liniste, de spus cand acestea se termina.
CREATE TABLE IF NOT EXISTS amanate (
    cheie TEXT PRIMARY KEY,
    titlu TEXT NOT NULL,
    inceput TEXT NOT NULL,
    toata_ziua INTEGER NOT NULL,
    tip TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reincercari (
    id INTEGER PRIMARY KEY,
    scadent TEXT NOT NULL,
    mesaj TEXT NOT NULL
);
-- Emailurile deja tratate, ca sa nu fie judecate (si platite la AI) de doua ori.
CREATE TABLE IF NOT EXISTS emailuri_vazute (
    id TEXT PRIMARY KEY,
    moment TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stare (
    cheie TEXT PRIMARY KEY,
    valoare TEXT NOT NULL
);
"""


class Memorie:
    def __init__(self, fisier: Path = FISIER_DB):
        self._fisier = fisier
        with closing(self._conexiune()) as con, con:
            con.executescript(_TABELE)

    def _conexiune(self) -> sqlite3.Connection:
        return sqlite3.connect(self._fisier)

    def _scrie(self, sql: str, valori: tuple = ()) -> None:
        with closing(self._conexiune()) as con, con:
            con.execute(sql, valori)

    def _citeste(self, sql: str, valori: tuple = ()) -> list[tuple]:
        with closing(self._conexiune()) as con:
            return con.execute(sql, valori).fetchall()

    # --- pentru ce am sunat deja ---

    def a_sunat(self, cheie: str) -> bool:
        return bool(self._citeste("SELECT 1 FROM apeluri WHERE cheie = ?", (cheie,)))

    def noteaza(self, cheie: str, titlu: str, rezultat: str, moment: datetime) -> None:
        self._scrie(
            "INSERT OR REPLACE INTO apeluri (cheie, titlu, moment, rezultat) VALUES (?, ?, ?, ?)",
            (cheie, titlu, moment.isoformat(timespec="seconds"), rezultat),
        )

    # --- limita de apeluri ---

    def numara_apelul(self, moment: datetime) -> None:
        self._scrie("INSERT INTO istoric (moment) VALUES (?)", (moment.isoformat(),))

    def ultimul_apel(self) -> datetime | None:
        rand = self._citeste("SELECT MAX(moment) FROM istoric")[0][0]
        return datetime.fromisoformat(rand) if rand else None

    def apeluri_in_ziua(self, zi: date) -> int:
        momente = self._citeste("SELECT moment FROM istoric")
        return sum(
            datetime.fromisoformat(m).astimezone(FUS_ORAR).date() == zi for (m,) in momente
        )

    # --- anunturi amanate de orele de liniste ---

    def amana(self, cheie: str, ev: Eveniment) -> bool:
        """Intoarce True daca anuntul e nou (nu era deja amanat)."""
        if self._citeste("SELECT 1 FROM amanate WHERE cheie = ?", (cheie,)):
            return False
        self._scrie(
            "INSERT INTO amanate (cheie, titlu, inceput, toata_ziua, tip) VALUES (?, ?, ?, ?, ?)",
            (cheie, ev.titlu, ev.inceput.isoformat(), int(ev.toata_ziua), ev.tip),
        )
        return True

    def amanate(self) -> list[tuple[str, Eveniment]]:
        rezultat = []
        for cheie, titlu, inceput, toata_ziua, tip in self._citeste(
            "SELECT cheie, titlu, inceput, toata_ziua, tip FROM amanate ORDER BY inceput"
        ):
            cand = date.fromisoformat(inceput) if toata_ziua else datetime.fromisoformat(inceput)
            rezultat.append((cheie, Eveniment("", titlu, cand, bool(toata_ziua), None, tip)))
        return rezultat

    def sterge_amanat(self, cheie: str) -> None:
        self._scrie("DELETE FROM amanate WHERE cheie = ?", (cheie,))

    # --- reincercari ---

    def programeaza_reincercare(self, scadent: datetime, mesaj: str) -> None:
        self._scrie(
            "INSERT INTO reincercari (scadent, mesaj) VALUES (?, ?)",
            (scadent.isoformat(), mesaj),
        )

    def reincercari(self) -> list[tuple[int, datetime, str]]:
        return [
            (id_, datetime.fromisoformat(scadent), mesaj)
            for id_, scadent, mesaj in self._citeste(
                "SELECT id, scadent, mesaj FROM reincercari ORDER BY scadent"
            )
        ]

    def sterge_reincercare(self, id_: int) -> None:
        self._scrie("DELETE FROM reincercari WHERE id = ?", (id_,))

    # --- emailuri ---

    def email_vazut(self, id_: str) -> bool:
        return bool(self._citeste("SELECT 1 FROM emailuri_vazute WHERE id = ?", (id_,)))

    def noteaza_email(self, id_: str, moment: datetime) -> None:
        self._scrie(
            "INSERT OR REPLACE INTO emailuri_vazute (id, moment) VALUES (?, ?)",
            (id_, moment.isoformat(timespec="seconds")),
        )

    # --- stari simple (ex. alerta de reautorizare a fost data) ---

    def stare(self, cheie: str) -> str | None:
        randuri = self._citeste("SELECT valoare FROM stare WHERE cheie = ?", (cheie,))
        return randuri[0][0] if randuri else None

    def pune_stare(self, cheie: str, valoare: str) -> None:
        self._scrie("INSERT OR REPLACE INTO stare (cheie, valoare) VALUES (?, ?)", (cheie, valoare))

    def sterge_stare(self, cheie: str) -> None:
        self._scrie("DELETE FROM stare WHERE cheie = ?", (cheie,))
