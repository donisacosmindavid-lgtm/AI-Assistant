"""Filtrul de emailuri si drumul unui email pana la apel.

Totul e fals: Gmail, Claude, apelurile si regulile. Baza de date e una temporara.
Rulare: python -m unittest -v
"""

import dataclasses
import logging
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import jarvis.serviciu as serviciu
from jarvis.apel import RezultatApel
from jarvis.calendar_google import FUS_ORAR
from jarvis.clasificare import EroareClasificare, Verdict
from jarvis.gmail import Email
from jarvis.memorie import Memorie
from jarvis.triere import DE_CLASIFICAT, IGNORAT, URGENT, triaza
from tests.test_recurent import REGULI as REGULI_CALENDAR

REGULI = dataclasses.replace(
    REGULI_CALENDAR,
    emailuri=True,
    expeditori_urgenti=(("noreply@dronework.example", "Work available"),),
    instructiune_email="mesaje de business si personale",
)


def email(id_="m1", nume="Ion Popescu", adresa="ion@firma.example", subiect="Oferta", etichete=("INBOX", "CATEGORY_PERSONAL"), antete=None):
    return Email(id_, nume, adresa, subiect, frozenset(etichete), antete or {}, "text")


class Triere(unittest.TestCase):
    def fel(self, **campuri):
        return triaza(email(**campuri), REGULI).fel

    def test_expeditor_urgent_cu_oferta_noua_e_urgent(self):
        self.assertEqual(
            self.fel(nume="DroneWork", adresa="noreply@dronework.example", subiect="Work available: Romania Wind Turbines",
                     etichete=("INBOX", "CATEGORY_UPDATES"), antete={"list-unsubscribe": "<x>"}),
            URGENT,
        )

    def test_reamintirea_platformei_nu_e_urgenta(self):
        self.assertEqual(
            self.fel(adresa="noreply@dronework.example", subiect="Reminder to bid on drone data order"), IGNORAT
        )

    def test_emailurile_automate_sunt_ignorate(self):
        cazuri = [
            dict(adresa="no-reply@livrari.example", subiect="Comanda ta e pe drum"),
            dict(adresa="notifications@magazin.example", subiect="Plata reusita"),
            dict(adresa="conturi@banca.example", subiect="Confirmare plata", etichete=("INBOX", "CATEGORY_UPDATES")),
            dict(adresa="hello@magazin.example", subiect="Cod de verificare: 123456", antete={"auto-submitted": "auto-generated"}),
            dict(adresa="echipa@platforma.example", subiect="Bine ai venit!", antete={"list-unsubscribe": "<mailto:x>"}),
            dict(adresa="oferte@magazin.example", subiect="Reduceri", etichete=("INBOX", "CATEGORY_PROMOTIONS")),
        ]
        for caz in cazuri:
            with self.subTest(caz["adresa"]):
                self.assertEqual(self.fel(**caz), IGNORAT)

    def test_emailul_scris_de_un_om_merge_la_clasificare(self):
        self.assertEqual(self.fel(), DE_CLASIFICAT)
        self.assertEqual(self.fel(adresa="info@firma-mica.example", subiect="Re: colaborare"), DE_CLASIFICAT)


class DrumulUnuiEmail(unittest.TestCase):
    def setUp(self):
        dosar = tempfile.TemporaryDirectory()
        self.addCleanup(dosar.cleanup)
        self.memorie = Memorie(Path(dosar.name) / "test.db")
        self.memorie.pune_stare(serviciu.GMAIL_ISTORIC, "100")
        self.casuta: dict[str, Email] = {}
        self.apeluri: list[str] = []
        self.la_claude: list[str] = []
        self.verdict = Verdict(True, "client", "Iti cere o oferta de pret pana vineri.")
        self.claude_merge = True

        def clasifica_fals(e, instructiune):
            self.la_claude.append(e.id)
            if not self.claude_merge:
                raise EroareClasificare("fara credit")
            return self.verdict

        def suna_fals(config, mesaj, **_):
            self.apeluri.append(mesaj)
            return RezultatApel("CAfals", "completed", 8)

        fals = mock.MagicMock()
        fals.Email = Email
        fals.IstoricExpirat = serviciu.gmail.IstoricExpirat
        fals.porneste_urmarirea.return_value = "100"
        fals.emailuri_noi.side_effect = lambda de_la: (list(self.casuta), "200")
        fals.citeste_email.side_effect = lambda id_: self.casuta.get(id_)

        jurnal_mut = logging.getLogger("jarvis.test")
        jurnal_mut.addHandler(logging.NullHandler())
        jurnal_mut.propagate = False
        for nume, inlocuitor in [
            ("gmail", fals),
            ("incarca_reguli", lambda: REGULI),
            ("incarca_config_twilio", lambda: None),
            ("clasifica", clasifica_fals),
            ("suna", suna_fals),
        ]:
            petic = mock.patch.object(serviciu, nume, inlocuitor)
            petic.start()
            self.addCleanup(petic.stop)
        self.sv = serviciu.Serviciu(False, self.memorie, asteapta=lambda s: None, jurnal=jurnal_mut)

    def la(self, ora, minut=0):
        return datetime(2026, 10, 12, ora, minut, tzinfo=FUS_ORAR)

    def test_expeditor_urgent_suna_si_noaptea_fara_claude(self):
        self.casuta["g1"] = email("g1", "DroneWork", "noreply@dronework.example", "Work available: Wind Turbines")
        self.sv.verifica_emailuri(self.la(2, 30))
        self.assertEqual(self.apeluri, ["Email urgent de la DroneWork: Work available: Wind Turbines."])
        self.assertEqual(self.la_claude, [])

    def test_expeditor_urgent_trece_peste_limita_de_apeluri(self):
        for minut in range(10):
            self.memorie.numara_apelul(self.la(11, 50 + minut // 2))
        self.casuta["g1"] = email("g1", "DroneWork", "noreply@dronework.example", "Work available: X")
        self.sv.verifica_emailuri(self.la(12))
        self.assertEqual(len(self.apeluri), 1)

    def test_emailul_automat_nu_ajunge_la_claude_si_nu_suna(self):
        self.casuta["b1"] = email("b1", "Livrari Rapide", "no-reply@livrari.example", "Comanda ta e pe drum")
        self.sv.verifica_emailuri(self.la(12))
        self.assertEqual((self.apeluri, self.la_claude), ([], []))

    def test_emailul_important_suna_cu_rezumat_o_singura_data(self):
        self.casuta["m1"] = email("m1")
        self.sv.verifica_emailuri(self.la(12))
        self.sv.verifica_emailuri(self.la(12, 1))
        self.assertEqual(
            self.apeluri, ["Ai un email important de la Ion Popescu. Iti cere o oferta de pret pana vineri."]
        )
        self.assertEqual(self.la_claude, ["m1"])

    def test_emailul_neimportant_nu_suna(self):
        self.verdict = Verdict(False, "newsletter", "")
        self.casuta["m1"] = email("m1")
        self.sv.verifica_emailuri(self.la(12))
        self.assertEqual(self.apeluri, [])

    def test_emailul_de_noapte_se_spune_la_sfarsitul_orelor_de_liniste(self):
        self.casuta["m1"] = email("m1")
        treziri = self.sv.verifica_emailuri(self.la(3))
        self.assertEqual(self.apeluri, [])
        self.assertIn(self.la(7), treziri)
        self.casuta.clear()
        self.sv.verifica_emailuri(self.la(7))
        self.assertEqual(len(self.apeluri), 1)

    def test_daca_claude_nu_merge_emailul_se_reia(self):
        self.claude_merge = False
        self.casuta["m1"] = email("m1")
        self.sv.verifica_emailuri(self.la(12))
        self.assertEqual(self.apeluri, [])
        self.assertEqual(self.memorie.stare(serviciu.GMAIL_ISTORIC), "100")
        self.claude_merge = True
        self.sv.verifica_emailuri(self.la(12, 15))
        self.assertEqual(len(self.apeluri), 1)


if __name__ == "__main__":
    unittest.main()
