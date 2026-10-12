"""Decide, pentru un eveniment, daca Jarvis suna acum si de ce."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time

from jarvis.calendar_google import FUS_ORAR, Eveniment
from jarvis.reguli import NUME_CULOARE, Reguli

_NASTERE_RO = re.compile(r"^\s*zi(?:ua)? de na[sș]tere\s*:?\s*(.+?)\s*$", re.IGNORECASE)
_NASTERE_EN = re.compile(r"^\s*(.+?)(?:'s|’s)\s+birthday\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Decizie:
    eveniment: Eveniment
    suna: bool
    stare: str  # eticheta scurta si stabila; nu contine minute, ca sa nu umple jurnalul
    motiv: str
    cheie: str | None = None  # sub ce cheie se tine minte apelul

    @property
    def e_zi_de_nastere(self) -> bool:
        return self.eveniment.tip == "birthday"


def _la_ora_fixa(
    ev: Eveniment,
    ora: time,
    fel: str,
    descriere: str,
    acum: datetime,
    deja_sunat: Callable[[str], bool],
) -> Decizie:
    azi = acum.date()
    if ev.inceput != azi:
        return Decizie(ev, False, "nu_azi", f"{descriere}, dar nu e azi")
    cheie = f"{fel}:{ev.id}:{azi.isoformat()}"
    if deja_sunat(cheie):
        return Decizie(ev, False, "deja_sunat", f"{descriere}; am sunat deja", cheie)
    if acum < datetime.combine(azi, ora, FUS_ORAR):
        return Decizie(ev, False, "asteapta_ora", f"{descriere}; sun azi la {ora:%H:%M}", cheie)
    return Decizie(ev, True, "sun", f"{descriere}; a trecut de {ora:%H:%M}", cheie)


def decide(
    ev: Eveniment,
    reguli: Reguli,
    acum: datetime,
    deja_sunat: Callable[[str], bool],
) -> Decizie:
    if ev.tip == "birthday":
        if not reguli.zile_nastere:
            return Decizie(ev, False, "oprit", "zi de nastere, dar apelurile pentru ele sunt oprite in reguli")
        return _la_ora_fixa(
            ev, reguli.ora_zile_nastere, "nastere", "zi de nastere", acum, deja_sunat
        )

    cerut = NUME_CULOARE[reguli.culoare_importanta]
    if ev.culoare != reguli.culoare_importanta:
        are = NUME_CULOARE.get(ev.culoare, "fara culoare proprie")
        return Decizie(ev, False, "neimportant", f"nu e important ({are}; se cere {cerut})")

    if ev.toata_ziua:
        return _la_ora_fixa(
            ev,
            reguli.ora_zi_intreaga,
            "zi",
            f"important ({cerut}), de o zi intreaga",
            acum,
            deja_sunat,
        )

    # Ora de inceput face parte din cheie: un eveniment mutat primeste un apel nou.
    cheie = f"eveniment:{ev.id}:{ev.inceput.isoformat()}"
    minute = (ev.inceput - acum).total_seconds() / 60
    if minute <= 0:
        return Decizie(ev, False, "a_inceput", f"important ({cerut}), dar a inceput deja", cheie)
    if deja_sunat(cheie):
        return Decizie(ev, False, "deja_sunat", f"important ({cerut}); am sunat deja", cheie)
    if minute > reguli.minute_inainte:
        return Decizie(
            ev,
            False,
            "prea_devreme",
            f"important ({cerut}), dar incepe peste {minute:.0f} min "
            f"(sun cu {reguli.minute_inainte} min inainte)",
            cheie,
        )
    return Decizie(ev, True, "sun", f"important ({cerut}), incepe in {minute:.0f} min", cheie)


def nume_sarbatorit(titlu: str) -> str:
    """Scoate numele din "Zi de nastere: X" sau "X's birthday"."""
    for tipar in (_NASTERE_RO, _NASTERE_EN):
        m = tipar.match(titlu)
        if m:
            return m.group(1)
    return titlu.strip()


_UNITATI = ("zero", "unu", "două", "trei", "patru", "cinci", "șase", "șapte", "opt", "nouă")
_INTRE_10_SI_19 = (
    "zece", "unsprezece", "douăsprezece", "treisprezece", "paisprezece",
    "cincisprezece", "șaisprezece", "șaptesprezece", "optsprezece", "nouăsprezece",
)
_ZECI = {2: "douăzeci", 3: "treizeci", 4: "patruzeci", 5: "cincizeci"}


def _in_cuvinte(n: int) -> str:
    """Numar intre 0 si 59, scris in cuvinte, cum se spune la ore si minute."""
    if n < 10:
        return _UNITATI[n]
    if n < 20:
        return _INTRE_10_SI_19[n - 10]
    zeci, unitati = divmod(n, 10)
    return _ZECI[zeci] if unitati == 0 else f"{_ZECI[zeci]} și {_UNITATI[unitati]}"


def ora_in_cuvinte(ora: int, minut: int) -> str:
    """Vocea citeste ciudat cifrele, asa ca ora se trimite scrisa in cuvinte."""
    text = f"ora {_in_cuvinte(ora)}"
    if minut == 0:
        return text
    if minut == 1:
        return f"{text} și un minut"
    if minut < 10:
        return f"{text} și {_in_cuvinte(minut)} minute"
    return f"{text} și {_in_cuvinte(minut)}"


def mesaj_eveniment(ev: Eveniment) -> str:
    if ev.toata_ziua:
        return f"Ai un eveniment important astăzi: {ev.titlu}."
    ora = ora_in_cuvinte(ev.inceput.hour, ev.inceput.minute)
    return f"Ai un eveniment important la {ora}: {ev.titlu}."


def mesaj_comun(evenimente: list[Eveniment], acum: datetime) -> str:
    """Un singur mesaj pentru unul sau mai multe anunturi spuse in acelasi apel."""
    parti = []
    for ev in evenimente:
        if ev.tip == "birthday":
            continue
        if ev.tip in ("email", "email_urgent"):
            parti.append(ev.titlu)  # la emailuri, titlul e deja propozitia de spus
        elif not ev.toata_ziua and ev.inceput <= acum:
            ora = ora_in_cuvinte(ev.inceput.hour, ev.inceput.minute)
            parti.append(
                f"În timpul orelor de liniște ai avut un eveniment important la {ora}: {ev.titlu}."
            )
        else:
            parti.append(mesaj_eveniment(ev))
    zile_nastere = [ev.titlu for ev in evenimente if ev.tip == "birthday"]
    if zile_nastere:
        parti.append(mesaj_zile_nastere(zile_nastere))
    return " ".join(parti)


def mesaj_zile_nastere(titluri: list[str]) -> str:
    nume = [nume_sarbatorit(t) for t in titluri]
    if len(nume) == 1:
        return f"Azi este ziua de naștere a: {nume[0]}."
    lista = ", ".join(nume[:-1]) + " și " + nume[-1]
    return f"Azi sunt {len(nume)} zile de naștere: {lista}."
