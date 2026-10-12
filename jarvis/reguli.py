"""Citeste reguli_importanta.md si spune clar ce e gresit si la ce linie."""

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

from jarvis.config import RADACINA

FISIER_REGULI = RADACINA / "reguli_importanta.md"

# Codurile de culoare ale evenimentelor din Google Calendar.
CULORI = {
    "lavender": "1",
    "sage": "2",
    "grape": "3",
    "flamingo": "4",
    "banana": "5",
    "tangerine": "6",
    "peacock": "7",
    "graphite": "8",
    "blueberry": "9",
    "basil": "10",
    "tomato": "11",
}
NUME_CULOARE = {cod: nume.capitalize() for nume, cod in CULORI.items()}

_GRESIT = object()  # tine locul unei valori care nu a putut fi citita
_LINIE = re.compile(r"^\s*-\s*([^:]+):\s*(.*?)\s*$")
_ORA = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class EroareReguli(Exception):
    """reguli_importanta.md lipseste sau are greseli."""


@dataclass(frozen=True)
class Reguli:
    culoare_importanta: str
    minute_inainte: int
    minute_intre_verificari: int
    calendare: tuple[str, ...]
    ora_zi_intreaga: time
    zile_nastere: bool
    ora_zile_nastere: time
    liniste: tuple[time, time] | None  # (de la, pana la); None = fara ore de liniste
    minute_intre_apeluri: int
    apeluri_pe_zi: int
    reincercare: bool
    minute_pana_la_reincercare: int
    emailuri: bool
    # (adresa sau bucata din adresa, cu ce trebuie sa inceapa subiectul; "" = orice subiect)
    expeditori_urgenti: tuple[tuple[str, str], ...]
    instructiune_email: str

    def in_liniste(self, moment: datetime) -> bool:
        if self.liniste is None:
            return False
        de_la, pana_la = self.liniste
        ora = moment.time()
        if de_la <= pana_la:
            return de_la <= ora < pana_la
        return ora >= de_la or ora < pana_la  # intervalul trece peste miezul noptii

    def sfarsit_liniste(self, moment: datetime) -> datetime:
        """Primul moment, dupa cel dat, la care se termina orele de liniste."""
        sfarsit = datetime.combine(moment.date(), self.liniste[1], moment.tzinfo)
        return sfarsit if sfarsit > moment else sfarsit + timedelta(days=1)


def _fara_diacritice(text: str) -> str:
    descompus = unicodedata.normalize("NFKD", text)
    return "".join(c for c in descompus if not unicodedata.combining(c))


def _cheie(text: str) -> str:
    return " ".join(_fara_diacritice(text).lower().strip("` ").split())


def _numar(v: str) -> int:
    if not v.isdigit() or int(v) < 1:
        raise ValueError("trebuie sa fie un numar intreg mai mare ca 0 (ex. 30)")
    return int(v)


def _ora(v: str) -> time:
    m = _ORA.match(v)
    if not m:
        raise ValueError("trebuie sa fie o ora de forma HH:MM (ex. 09:00)")
    return time(int(m.group(1)), int(m.group(2)))


def _da_nu(v: str) -> bool:
    v = _cheie(v)
    if v not in ("da", "nu"):
        raise ValueError("trebuie sa fie da sau nu")
    return v == "da"


def _liniste(v: str) -> tuple[time, time] | None:
    if _cheie(v) == "nu":
        return None
    capete = [c.strip() for c in v.replace("–", "-").split("-")]
    if len(capete) != 2:
        raise ValueError("trebuie sa fie de forma HH:MM-HH:MM (ex. 23:00-07:00) sau nu")
    de_la, pana_la = _ora(capete[0]), _ora(capete[1])
    if de_la == pana_la:
        raise ValueError("cele doua ore sunt egale; scrie nu daca nu vrei ore de liniste")
    return de_la, pana_la


def _urgenti(v: str) -> tuple[tuple[str, str], ...]:
    if _cheie(v) == "nu":
        return ()
    rezultat = []
    for bucata in v.split(","):
        adresa, _, subiect = bucata.partition("|")
        adresa = adresa.strip("` ").lower()
        if "." not in adresa:
            raise ValueError(
                'fiecare expeditor trebuie sa fie o adresa sau un domeniu (ex. noreply@dronework.example), '
                'optional urmat de | si inceputul subiectului; scrie nu daca nu ai niciunul'
            )
        rezultat.append((adresa, subiect.strip("` ")))
    return tuple(rezultat)


def _text(v: str) -> str:
    if len(v) < 10:
        raise ValueError("scrie o propozitie care descrie ce e important")
    return v


def _culoare(v: str) -> str:
    cod = CULORI.get(_cheie(v))
    if cod is None:
        permise = ", ".join(n.capitalize() for n in CULORI)
        raise ValueError(f"culoare necunoscuta. Culori posibile: {permise}")
    return cod


def _calendare(v: str) -> tuple[str, ...]:
    nume = [n.strip("` ") for n in v.split(",") if n.strip("` ")]
    if not nume:
        raise ValueError("scrie cel putin un calendar (ex. principal)")
    return tuple("primary" if _cheie(n) == "principal" else n for n in nume)


# numele regulii din fisier -> (campul din Reguli, cum se citeste valoarea)
_REGULI = {
    "culoare eveniment important": ("culoare_importanta", _culoare),
    "minute inainte de eveniment": ("minute_inainte", _numar),
    "minute intre verificari": ("minute_intre_verificari", _numar),
    "calendare": ("calendare", _calendare),
    "ora apel pentru zi intreaga": ("ora_zi_intreaga", _ora),
    "apel pentru zile de nastere": ("zile_nastere", _da_nu),
    "ora apel pentru zile de nastere": ("ora_zile_nastere", _ora),
    "ore de liniste": ("liniste", _liniste),
    "minute intre apeluri": ("minute_intre_apeluri", _numar),
    "apeluri pe zi": ("apeluri_pe_zi", _numar),
    "reincercare daca nu raspund": ("reincercare", _da_nu),
    "minute pana la reincercare": ("minute_pana_la_reincercare", _numar),
    "apel pentru emailuri": ("emailuri", _da_nu),
    "expeditori urgenti": ("expeditori_urgenti", _urgenti),
    "ce e important la email": ("instructiune_email", _text),
}


def incarca_reguli(fisier: Path = FISIER_REGULI) -> Reguli:
    if not fisier.exists():
        raise EroareReguli(f"Nu gasesc fisierul de reguli: {fisier}")

    valori: dict[str, object] = {}
    linii: dict[str, int] = {}
    probleme: list[str] = []

    for nr, linie in enumerate(fisier.read_text(encoding="utf-8").splitlines(), 1):
        m = _LINIE.match(linie)
        if not m:
            continue
        nume, valoare = _cheie(m.group(1)), m.group(2).strip()
        if nume not in _REGULI:
            probleme.append(f'linia {nr}: nu cunosc regula "{m.group(1).strip()}"')
            continue
        camp, citeste = _REGULI[nume]
        if camp in valori:
            probleme.append(
                f'linia {nr}: regula "{nume}" apare de doua ori (si la linia {linii[camp]})'
            )
            continue
        linii[camp] = nr
        try:
            valori[camp] = citeste(valoare)
        except ValueError as e:
            probleme.append(f'linia {nr}: "{nume}: {valoare}" - {e}')
            valori[camp] = _GRESIT

    for nume, (camp, _) in _REGULI.items():
        if camp not in valori:
            probleme.append(f'lipseste regula "{nume}"')

    inainte = valori.get("minute_inainte")
    interval = valori.get("minute_intre_verificari")
    if isinstance(inainte, int) and isinstance(interval, int) and inainte <= interval:
        probleme.append(
            f'linia {linii["minute_inainte"]}: "minute inainte de eveniment" ({inainte}) '
            f'trebuie sa fie mai mare decat "minute intre verificari" ({interval}), '
            "altfel Jarvis poate rata evenimente"
        )

    if probleme:
        raise EroareReguli(
            f"Greseli in {fisier.name}:\n" + "\n".join(f"  - {p}" for p in probleme)
        )
    return Reguli(**valori)
