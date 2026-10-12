"""Doua aparitii ale aceluiasi eveniment recurent sunt tratate ca evenimente separate.

Totul e fals: calendarul, apelurile si regulile. Baza de date e una temporara,
iar jurnalul nu scrie nicaieri. Rulare: python -m unittest -v
"""

import logging
import tempfile
import unittest
from datetime import datetime, time
from pathlib import Path
from unittest import mock

import jarvis.serviciu as serviciu
from jarvis.apel import RezultatApel
from jarvis.calendar_google import FUS_ORAR, _din_raspuns
from jarvis.decizie import decide
from jarvis.memorie import Memorie
from jarvis.reguli import Reguli

REGULI = Reguli(
    culoare_importanta="11",
    minute_inainte=30,
    minute_intre_verificari=15,
    calendare=("primary",),
    ora_zi_intreaga=time(9, 0),
    zile_nastere=True,
    ora_zile_nastere=time(18, 0),
    liniste=(time(23, 0), time(7, 0)),
    minute_intre_apeluri=15,
    apeluri_pe_zi=10,
    reincercare=True,
    minute_pana_la_reincercare=5,
    emailuri=False,
    expeditori_urgenti=(),
    instructiune_email="",
)


def aparitie(zi: int, id_: str | None = None) -> dict:
    """O aparitie a sedintei saptamanale de marti, 10:00, asa cum o trimite Google."""
    return {
        "id": id_ or f"sedinta123_202610{zi:02d}T070000Z",
        "recurringEventId": "sedinta123",
        "summary": "Ședință săptămânală",
        "colorId": "11",
        "eventType": "default",
        "start": {"dateTime": f"2026-10-{zi:02d}T10:00:00+03:00"},
        "end": {"dateTime": f"2026-10-{zi:02d}T11:00:00+03:00"},
    }


def la(zi: int, ora: int, minut: int) -> datetime:
    return datetime(2026, 10, zi, ora, minut, tzinfo=FUS_ORAR)


class EvenimentRecurent(unittest.TestCase):
    def setUp(self):
        dosar = tempfile.TemporaryDirectory()
        self.addCleanup(dosar.cleanup)
        self.memorie = Memorie(Path(dosar.name) / "test.db")

    def test_fiecare_aparitie_are_cheia_ei(self):
        prima, a_doua = _din_raspuns(aparitie(6)), _din_raspuns(aparitie(13))
        d1 = decide(prima, REGULI, la(6, 9, 40), self.memorie.a_sunat)
        d2 = decide(a_doua, REGULI, la(13, 9, 40), self.memorie.a_sunat)
        self.assertTrue(d1.suna)
        self.assertTrue(d2.suna)
        self.assertNotEqual(d1.cheie, d2.cheie)

    def test_apelul_pentru_prima_nu_o_blocheaza_pe_a_doua(self):
        prima, a_doua = _din_raspuns(aparitie(6)), _din_raspuns(aparitie(13))
        d1 = decide(prima, REGULI, la(6, 9, 40), self.memorie.a_sunat)
        self.memorie.noteaza(d1.cheie, prima.titlu, "completed", la(6, 9, 40))

        self.assertEqual(decide(prima, REGULI, la(6, 9, 45), self.memorie.a_sunat).stare, "deja_sunat")
        self.assertEqual(decide(a_doua, REGULI, la(13, 9, 40), self.memorie.a_sunat).stare, "sun")

    def test_separate_chiar_daca_ar_avea_acelasi_id(self):
        # Cazul cel mai rau: Google ar trimite acelasi id pentru ambele aparitii.
        prima = _din_raspuns(aparitie(6, id_="sedinta123"))
        a_doua = _din_raspuns(aparitie(13, id_="sedinta123"))
        d1 = decide(prima, REGULI, la(6, 9, 40), self.memorie.a_sunat)
        self.memorie.noteaza(d1.cheie, prima.titlu, "completed", la(6, 9, 40))

        self.assertEqual(decide(a_doua, REGULI, la(13, 9, 40), self.memorie.a_sunat).stare, "sun")

    def test_serviciul_suna_o_data_pentru_fiecare_aparitie(self):
        in_calendar: list[dict] = []
        apeluri: list[str] = []

        def calendar_fals(inceput, sfarsit, calendar):
            return [_din_raspuns(e) for e in in_calendar]

        def suna_fals(config, mesaj, **_):
            apeluri.append(mesaj)
            return RezultatApel("CAfals", "completed", 8)

        jurnal_mut = logging.getLogger("jarvis.test")
        jurnal_mut.addHandler(logging.NullHandler())
        jurnal_mut.propagate = False

        with (
            mock.patch.object(serviciu, "incarca_reguli", return_value=REGULI),
            mock.patch.object(serviciu, "evenimente_intre", calendar_fals),
            mock.patch.object(serviciu, "incarca_config_twilio", return_value=None),
            mock.patch.object(serviciu, "suna", suna_fals),
        ):
            sv = serviciu.Serviciu(
                False, self.memorie, asteapta=lambda secunde: None, jurnal=jurnal_mut
            )

            in_calendar[:] = [aparitie(6)]
            sv.verifica(la(6, 9, 40))
            self.assertEqual(len(apeluri), 1, "prima aparitie trebuie anuntata")
            sv.verifica(la(6, 9, 55))
            self.assertEqual(len(apeluri), 1, "aceeasi aparitie nu se anunta de doua ori")

            in_calendar[:] = [aparitie(13)]
            sv.verifica(la(13, 9, 40))
            self.assertEqual(len(apeluri), 2, "a doua aparitie trebuie anuntata si ea")
            sv.verifica(la(13, 9, 55))
            self.assertEqual(len(apeluri), 2)

        self.assertEqual(
            apeluri,
            ["Ai un eveniment important la ora zece: Ședință săptămânală."] * 2,
        )


if __name__ == "__main__":
    unittest.main()
