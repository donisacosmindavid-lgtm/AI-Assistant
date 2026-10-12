"""Bucla principala: verifica periodic calendarul, asculta emailurile noi, decide si suna."""

import logging
import time
from datetime import datetime, timedelta

from jarvis import gmail
from jarvis.apel import VOCE_REZERVA, EroareApel, RezultatApel, suna
from jarvis.calendar_google import (
    FUS_ORAR,
    EroareAutorizare,
    Eveniment,
    evenimente_intre,
)
from jarvis.clasificare import EroareClasificare, clasifica
from jarvis.config import EroareConfig, incarca_config_twilio
from jarvis.decizie import Decizie, decide, mesaj_comun
from jarvis.jurnal import porneste_jurnalul
from jarvis.memorie import Memorie
from jarvis.reguli import EroareReguli, Reguli, incarca_reguli
from jarvis.triere import IGNORAT, URGENT, triaza

ZILE = ("Lu", "Ma", "Mi", "Jo", "Vi", "Sa", "Du")
# Cat asteapta pana la urmatoarea incercare daca regulile nu pot fi citite.
MINUTE_DUPA_EROARE = 15
# Pauzele dintre reincercari cand calendarul nu poate fi citit (retea, server Google).
PAUZE_RETEA_MINUTE = (1, 2, 4)
MESAJ_REAUTORIZARE = "Jarvis trebuie reautorizat."
ALERTA_REAUTORIZARE = "alerta_reautorizare"
# Unde a ramas citirea emailurilor si cand a fost reinnoita ultima oara abonarea la Gmail.
GMAIL_ISTORIC = "gmail_istoric"
GMAIL_URMARIRE = "gmail_urmarire"
TIPURI_EMAIL = ("email", "email_urgent")

# Un anunt: cheia sub care se tine minte + evenimentul (sau emailul) despre care e vorba.
Anunt = tuple[str, Eveniment]


def _cand(ev: Eveniment) -> str:
    zi = f"{ZILE[ev.inceput.weekday()]} {ev.inceput:%d.%m}"
    return f"{zi}, toata ziua" if ev.toata_ziua else f"{zi} {ev.inceput:%H:%M}"


def _descrie(ev: Eveniment) -> str:
    return f'"{ev.titlu}" ({_cand(ev)})'


def _descrie_email(email: gmail.Email) -> str:
    return f'Email de la {email.nume} <{email.adresa}>: "{email.subiect}"'


class Serviciu:
    def __init__(
        self,
        proba: bool,
        memorie: Memorie | None = None,
        asteapta=time.sleep,
        jurnal: logging.Logger | None = None,
    ):
        self.proba = proba
        self.jurnal = jurnal or porneste_jurnalul()
        self.memorie = memorie or Memorie()
        self._asteapta = asteapta
        # Ce s-a scris deja in jurnal, ca sa nu repetam acelasi rand la fiecare verificare.
        self._ultima_stare: dict[tuple, str] = {}
        self._deja_scris: set[tuple] = set()

    # --- jurnal ---

    def _scrie_decizia(self, d: Decizie) -> None:
        ev = d.eveniment
        cine = (ev.id, str(ev.inceput))
        if self._ultima_stare.get(cine) == d.stare:
            return
        self._ultima_stare[cine] = d.stare
        verdict = "SUN" if d.suna else "NU SUN"
        self.jurnal.info("%s -> %s: %s", _descrie(ev), verdict, d.motiv)

    def _scrie_o_data(self, cine: tuple, mesaj: str, *valori, nivel=logging.INFO) -> None:
        if cine not in self._deja_scris:
            self._deja_scris.add(cine)
            self.jurnal.log(nivel, mesaj, *valori)

    # --- apel ---

    def _apeleaza(self, mesaj: str) -> RezultatApel | None:
        """Suna (cu vocea de rezerva daca cea principala da eroare). None = nu s-a sunat."""
        if self.proba:
            self.jurnal.info('  PROBA, nu sun. Mesajul ar fi fost: "%s"', mesaj)
            return None
        try:
            config = incarca_config_twilio()
            rezultat = suna(config, mesaj)
            if rezultat.fara_sunet:
                self.jurnal.warning(
                    "  Apelul s-a incheiat fara ca mesajul sa fie citit (%s s, erori Twilio: %s). "
                    "Vocea principala pare indisponibila; sun din nou cu vocea de rezerva.",
                    rezultat.durata_secunde,
                    ", ".join(rezultat.erori_twilio) or "niciuna",
                )
                rezultat = suna(config, mesaj, voce=VOCE_REZERVA)
        except (EroareConfig, EroareApel) as e:
            self.jurnal.error("  Apelul nu a pornit: %s", e)
            return None
        durata = f", {rezultat.durata_secunde} s" if rezultat.durata_secunde is not None else ""
        self.jurnal.info(
            '  Apel: %s (%s%s). Mesaj: "%s"', rezultat.stare, rezultat.explicatie, durata, mesaj
        )
        return rezultat

    def _pastreaza_emailurile(self, anunturi: list[Anunt]) -> None:
        """Un email nu mai apare la verificarea urmatoare (ca un eveniment), deci se tine minte."""
        if self.proba:
            return
        for cheie, ev in anunturi:
            if ev.tip in TIPURI_EMAIL:
                self.memorie.amana(cheie, ev)

    def _anunta(
        self,
        anunturi: list[Anunt],
        reguli: Reguli,
        acum: datetime,
        treziri: list[datetime],
        fara_limite: bool = False,
    ) -> bool:
        """Un apel pentru anunturile date, daca limitele permit. True = s-a sunat."""
        chei = tuple(cheie for cheie, _ in anunturi)
        if not fara_limite:
            if self.memorie.apeluri_in_ziua(acum.date()) >= reguli.apeluri_pe_zi:
                self._scrie_o_data(
                    ("zi", chei),
                    "  NU SUN: am atins limita de %d apeluri pe zi.",
                    reguli.apeluri_pe_zi,
                )
                for cheie in chei:
                    self.memorie.sterge_amanat(cheie)
                return False
            ultimul = self.memorie.ultimul_apel()
            if ultimul is not None:
                liber_la = ultimul + timedelta(minutes=reguli.minute_intre_apeluri)
                if acum < liber_la:
                    self._scrie_o_data(
                        ("interval", chei),
                        "  AMANAT pana la %s: cel mult un apel la %d minute.",
                        f"{liber_la.astimezone(FUS_ORAR):%H:%M}",
                        reguli.minute_intre_apeluri,
                    )
                    self._pastreaza_emailurile(anunturi)
                    treziri.append(liber_la)
                    return False

        mesaj = mesaj_comun([ev for _, ev in anunturi], acum)
        rezultat = self._apeleaza(mesaj)
        if rezultat is None:
            self._pastreaza_emailurile(anunturi)
            return False
        self.memorie.numara_apelul(acum)
        for cheie, ev in anunturi:
            self.memorie.noteaza(cheie, ev.titlu, rezultat.stare, acum)
            self.memorie.sterge_amanat(cheie)
        if rezultat.nepreluat and reguli.reincercare:
            scadent = acum + timedelta(minutes=reguli.minute_pana_la_reincercare)
            self.memorie.programeaza_reincercare(scadent, mesaj)
            treziri.append(scadent)
            self.jurnal.info("  Nu ai raspuns. Mai incerc o data la %s.", f"{scadent:%H:%M}")
        return True

    def _anunturi(
        self, de_anuntat: list[Anunt], reguli: Reguli, acum: datetime, treziri: list[datetime]
    ) -> int:
        """Face apelurile pentru anunturile noi si pentru cele ramase de data trecuta."""
        amanate = self.memorie.amanate()
        chei_amanate = {cheie for cheie, _ in amanate}
        toate = amanate + [a for a in de_anuntat if a[0] not in chei_amanate]
        urgente = [a for a in toate if a[1].tip == "email_urgent"]
        restul = [a for a in toate if a[1].tip != "email_urgent"]

        apeluri = 0
        if urgente:
            # Expeditorii urgenti trec peste orele de liniste si peste limitele de apeluri.
            apeluri += self._anunta(urgente, reguli, acum, treziri, fara_limite=True)
        if not restul:
            return apeluri

        if reguli.in_liniste(acum):
            sfarsit = reguli.sfarsit_liniste(acum)
            for cheie, ev in restul:
                if self.proba or self.memorie.amana(cheie, ev):
                    self._scrie_o_data(
                        ("liniste", cheie),
                        "  AMANAT pana la %s: ore de liniste.",
                        f"{sfarsit:%H:%M}",
                    )
            treziri.append(sfarsit)
            return apeluri

        if any(cheie in chei_amanate for cheie, _ in restul):
            # Tot ce a ramas de spus, plus ce e nou, intr-un singur apel.
            self.jurnal.info("Am %d anunturi de spus; le spun intr-un singur apel.", len(restul))
            return apeluri + self._anunta(restul, reguli, acum, treziri)

        grupuri = [[a] for a in restul if a[1].tip not in ("birthday", "email")]
        for tip in ("birthday", "email"):
            grup = [a for a in restul if a[1].tip == tip]
            if grup:
                grupuri.append(grup)
        for grup in grupuri:
            apeluri += self._anunta(grup, reguli, acum, treziri)
        return apeluri

    # --- calendar ---

    def _reincercari(self, reguli: Reguli, acum: datetime, treziri: list[datetime]) -> None:
        for id_, scadent, mesaj in self.memorie.reincercari():
            if scadent > acum:
                treziri.append(scadent)
                continue
            if self.proba:
                continue
            self.memorie.sterge_reincercare(id_)
            if reguli.in_liniste(acum) and not mesaj.startswith("Email urgent"):
                self.jurnal.info("Reincercarea a picat in orele de liniste; renunt la ea.")
                continue
            self.jurnal.info("Reincercare (nu ai raspuns la apelul anterior):")
            rezultat = self._apeleaza(mesaj)
            if rezultat is not None and rezultat.nepreluat:
                self.jurnal.info("  Tot fara raspuns. Nu mai incerc pentru acest anunt.")

    def _citeste_calendarul(self, reguli: Reguli, acum: datetime) -> list[Eveniment]:
        pana = acum + timedelta(minutes=reguli.minute_inainte + reguli.minute_intre_verificari)
        for pauza in (*PAUZE_RETEA_MINUTE, None):
            try:
                return [
                    ev for cal in reguli.calendare for ev in evenimente_intre(acum, pana, cal)
                ]
            except EroareAutorizare:
                raise
            except Exception as e:
                if pauza is None:
                    raise
                self.jurnal.warning(
                    "Nu am putut citi calendarul (%s). Reincerc peste %d min.",
                    type(e).__name__,
                    pauza,
                )
                self._asteapta(pauza * 60)

    def _alerta_reautorizare(
        self, eroare: EroareAutorizare, reguli: Reguli, acum: datetime, treziri: list[datetime]
    ) -> None:
        if ("autorizare",) not in self._deja_scris:
            self._deja_scris.add(("autorizare",))
            self.jurnal.error(
                "%s\nPana atunci Jarvis nu poate citi calendarul si nu te poate anunta de nimic.",
                eroare,
            )
        if not eroare.a_expirat or self.memorie.stare(ALERTA_REAUTORIZARE):
            return
        if reguli.in_liniste(acum):
            treziri.append(reguli.sfarsit_liniste(acum))
            return
        self.jurnal.info("Te sun o singura data ca sa stii ca Jarvis trebuie reautorizat.")
        if self._apeleaza(MESAJ_REAUTORIZARE) is not None:
            self.memorie.pune_stare(ALERTA_REAUTORIZARE, acum.isoformat())

    def verifica(self, acum: datetime | None = None) -> datetime:
        """O verificare completa a calendarului. Intoarce momentul urmatoarei verificari."""
        acum = acum or datetime.now(FUS_ORAR)
        try:
            reguli = incarca_reguli()
        except EroareReguli as e:
            self.jurnal.error("%s\nNu sun pana nu e reparat fisierul de reguli.", e)
            return acum + timedelta(minutes=MINUTE_DUPA_EROARE)

        treziri = [acum + timedelta(minutes=reguli.minute_intre_verificari)]
        self._reincercari(reguli, acum, treziri)

        try:
            evenimente = self._citeste_calendarul(reguli, acum)
        except EroareAutorizare as e:
            self._alerta_reautorizare(e, reguli, acum, treziri)
            return min(treziri)
        except Exception as e:
            self.jurnal.error(
                "Nu am reusit sa citesc calendarul (%s: %s). Incerc din nou la urmatoarea verificare.",
                type(e).__name__,
                e,
            )
            return min(treziri)
        self._deja_scris.discard(("autorizare",))
        if not self.proba:
            self.memorie.sterge_stare(ALERTA_REAUTORIZARE)

        de_anuntat: list[Anunt] = []
        for ev in evenimente:
            try:
                d = decide(ev, reguli, acum, self.memorie.a_sunat)
                self._scrie_decizia(d)
                if d.suna:
                    de_anuntat.append((d.cheie, ev))
            except Exception:
                self.jurnal.exception('Eroare la evenimentul "%s"; trec mai departe.', ev.titlu)

        apeluri = 0
        try:
            apeluri = self._anunturi(de_anuntat, reguli, acum, treziri)
        except Exception:
            self.jurnal.exception("Eroare la anuntare; incerc din nou la urmatoarea verificare.")

        self.jurnal.info(
            "Verificare terminata: %d evenimente in urmatoarele %d min, %d apeluri.",
            len(evenimente),
            reguli.minute_inainte + reguli.minute_intre_verificari,
            apeluri,
        )
        return min(treziri)

    # --- emailuri ---

    def _punct_de_pornire(self, acum: datetime) -> str | None:
        """De unde se citesc emailurile noi; reinnoieste zilnic abonarea la anunturile Gmail."""
        punct = self.memorie.stare(GMAIL_ISTORIC)
        if self.proba:
            return punct
        reinnoita = self.memorie.stare(GMAIL_URMARIRE)
        veche = reinnoita is None or acum - datetime.fromisoformat(reinnoita) > timedelta(days=1)
        if punct is None or veche:
            curent = gmail.porneste_urmarirea()
            self.memorie.pune_stare(GMAIL_URMARIRE, acum.isoformat())
            if punct is None:
                self.memorie.pune_stare(GMAIL_ISTORIC, curent)
                self.jurnal.info("Urmaresc emailurile noi din Gmail, de acum inainte.")
                punct = curent
        return punct

    def _judeca_emailul(self, id_: str, reguli: Reguli, acum: datetime) -> Anunt | None:
        email = gmail.citeste_email(id_)
        if email is None:
            return None  # sters intre timp
        triere = triaza(email, reguli)
        if triere.fel == IGNORAT:
            self.jurnal.info("%s -> IGNORAT: %s", _descrie_email(email), triere.motiv)
            return None
        if triere.fel == URGENT:
            self.jurnal.info("%s -> SUN (urgent): %s", _descrie_email(email), triere.motiv)
            text, tip = f"Email urgent de la {email.nume}: {email.subiect}.", "email_urgent"
        else:
            verdict = clasifica(email, reguli.instructiune_email)
            self.jurnal.info(
                "%s -> %s (Claude): %s",
                _descrie_email(email),
                "SUN" if verdict.important else "NU SUN",
                verdict.motiv,
            )
            if not verdict.important:
                return None
            text, tip = f"Ai un email important de la {email.nume}. {verdict.rezumat}", "email"
        return f"email:{email.id}", Eveniment(email.id, text, acum, False, None, tip)

    def verifica_emailuri(self, acum: datetime | None = None) -> list[datetime]:
        """Trateaza emailurile sosite de la ultima verificare. Intoarce momentele la care e ceva de facut."""
        acum = acum or datetime.now(FUS_ORAR)
        treziri: list[datetime] = []
        try:
            reguli = incarca_reguli()
        except EroareReguli:
            return treziri  # greseala e deja scrisa in jurnal de verificarea calendarului
        if not reguli.emailuri:
            return treziri

        try:
            punct = self._punct_de_pornire(acum)
            if punct is None:
                return treziri
            try:
                ids, punct_nou = gmail.emailuri_noi(punct)
            except gmail.IstoricExpirat:
                self.jurnal.warning(
                    "Gmail nu mai tine minte de unde ramasesem; reiau de la emailurile de acum inainte."
                )
                if not self.proba:
                    self.memorie.pune_stare(GMAIL_ISTORIC, gmail.porneste_urmarirea())
                return treziri
        except EroareAutorizare as e:
            self._scrie_o_data(("email", "autorizare"), "Emailuri: %s", e, nivel=logging.ERROR)
            return treziri
        except Exception as e:
            self.jurnal.error("Nu am putut citi emailurile noi (%s: %s).", type(e).__name__, e)
            return treziri
        self._deja_scris.discard(("email", "autorizare"))

        de_anuntat: list[Anunt] = []
        toate_tratate = True
        for id_ in ids:
            if self.memorie.email_vazut(id_):
                continue
            try:
                anunt = self._judeca_emailul(id_, reguli, acum)
            except (EroareClasificare, EroareConfig) as e:
                # Emailul ramane netratat si se reia la verificarea urmatoare.
                toate_tratate = False
                self._scrie_o_data(("email", "clasificare", str(e)), "Emailuri: %s", e, nivel=logging.ERROR)
                continue
            except Exception:
                toate_tratate = False
                self.jurnal.exception("Eroare la un email; il reiau la verificarea urmatoare.")
                continue
            if anunt:
                de_anuntat.append(anunt)
            if not self.proba:
                self.memorie.noteaza_email(id_, acum)
        if toate_tratate:
            self._deja_scris = {c for c in self._deja_scris if c[:2] != ("email", "clasificare")}
            if not self.proba:
                self.memorie.pune_stare(GMAIL_ISTORIC, punct_nou)

        if de_anuntat or self.memorie.amanate():
            try:
                self._anunturi(de_anuntat, reguli, acum, treziri)
            except Exception:
                self.jurnal.exception("Eroare la anuntarea unui email.")
        return treziri

    def _asculta_emailuri_pana_la(self, pana_la: datetime) -> None:
        """Sta cu ochii pe anunturile Gmail pana la urmatoarea verificare a calendarului."""
        while True:
            ramas = (pana_la - datetime.now(FUS_ORAR)).total_seconds()
            if ramas <= 0:
                return
            try:
                active = incarca_reguli().emailuri
            except EroareReguli:
                active = False
            if not active or ramas < 5:
                self._asteapta(ramas)
                return
            inceput = time.monotonic()
            try:
                semnal = gmail.asteapta_semnal(min(ramas, gmail.SECUNDE_ASTEPTARE_SEMNAL))
            except EroareAutorizare as e:
                self._scrie_o_data(("email", "autorizare"), "Emailuri: %s", e, nivel=logging.ERROR)
                self._asteapta(ramas)
                return
            except Exception as e:
                self._scrie_o_data(
                    ("email", "ascultare"),
                    "Nu pot asculta anunturile Gmail (%s: %s). Verific emailurile la fiecare "
                    "verificare a calendarului pana se repara.",
                    type(e).__name__,
                    e,
                    nivel=logging.WARNING,
                )
                self._asteapta(min(ramas, 60))
                continue
            self._deja_scris.discard(("email", "ascultare"))
            if semnal:
                treziri = self.verifica_emailuri()
                pana_la = min([pana_la, *treziri])
            else:
                gmail.asteapta_intre_intrebari(inceput)

    def ruleaza(self) -> None:
        self.jurnal.info(
            "Jarvis a pornit%s.", " in mod de PROBA (nu suna)" if self.proba else ""
        )
        try:
            while True:
                urmatoarea = self.verifica()
                # Plasa de siguranta: emailurile se verifica si aici, nu doar la anuntul Gmail.
                urmatoarea = min([urmatoarea, *self.verifica_emailuri()])
                self._asculta_emailuri_pana_la(urmatoarea)
        except KeyboardInterrupt:
            self.jurnal.info("Jarvis a fost oprit.")
