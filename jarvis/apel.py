"""Apelul robotic: Twilio suna mobilul meu si citeste un mesaj in romana."""

import time
from dataclasses import dataclass

from requests.exceptions import RequestException
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

from jarvis.config import ConfigTwilio

LIMBA = "ro-RO"
# Voce de barbat ElevenLabs ("George"), aleasa la proba din Pasul 1. E "public beta"
# la Twilio: poate fi schimbata sau scoasa fara anunt.
VOCE = "ElevenLabs.JBFqnCBsd6RMkjVDRZzb"
# Voce de rezerva (femeie, Google), daca cea de sus nu mai e disponibila.
VOCE_REZERVA = "Google.ro-RO-Wavenet-B"
REPETARI = 2

# Stari in care apelul s-a incheiat si nu se mai schimba.
STARI_FINALE = {"completed", "busy", "no-answer", "failed", "canceled"}
# Stari in care nu am auzit mesajul si merita o reincercare.
STARI_NEPRELUAT = {"busy", "no-answer", "failed", "canceled"}

EXPLICATII = {
    "completed": "apelul a fost preluat si s-a incheiat normal",
    "busy": "ocupat (sau apel respins)",
    "no-answer": "nu a raspuns nimeni",
    "failed": "apelul nu a putut fi efectuat",
    "canceled": "apelul a fost anulat",
}


class EroareApel(Exception):
    """Twilio a refuzat apelul sau nu a putut fi contactat."""


@dataclass(frozen=True)
class RezultatApel:
    sid: str
    stare: str
    durata_secunde: int | None
    # Codurile de eroare raportate de Twilio in timpul apelului (ex. voce indisponibila).
    erori_twilio: tuple[str, ...] = ()

    @property
    def explicatie(self) -> str:
        return EXPLICATII.get(self.stare, "nu stiu cum s-a incheiat apelul")

    @property
    def nepreluat(self) -> bool:
        return self.stare in STARI_NEPRELUAT

    @property
    def fara_sunet(self) -> bool:
        """Apel preluat, dar in care vocea n-a apucat sa spuna nimic.

        Asa arata o voce pe care Twilio n-o mai are: apelul se incheie in 0-1 secunde,
        fara nicio eroare raportata (verificat pe un apel real cu o voce inexistenta).
        """
        if self.erori_twilio:
            return True
        return self.stare == "completed" and self.durata_secunde is not None and self.durata_secunde <= 1


def construieste_twiml(mesaj: str, voce: str = VOCE) -> str:
    raspuns = VoiceResponse()
    for i in range(REPETARI):
        if i:
            raspuns.pause(length=1)
        raspuns.say(mesaj, language=LIMBA, voice=voce)
    return str(raspuns)


def _ascunde(text: str, secrete: list[str]) -> str:
    for secret in secrete:
        text = text.replace(secret, "***")
        text = text.replace(secret.lstrip("+"), "***")
    return text


def suna(
    config: ConfigTwilio, mesaj: str, voce: str = VOCE, asteapta_secunde: int = 90
) -> RezultatApel:
    """Porneste apelul si asteapta pana se incheie (cel mult asteapta_secunde)."""
    client = Client(config.account_sid, config.auth_token)
    try:
        apel = client.calls.create(
            to=config.numar_meu,
            from_=config.numar_twilio,
            twiml=construieste_twiml(mesaj, voce),
        )
    except TwilioRestException as e:
        raise EroareApel(
            f"Twilio a refuzat cererea (cod {e.code}, HTTP {e.status}): "
            f"{_ascunde(str(e.msg), config.secrete())}"
        ) from None
    except RequestException as e:
        raise EroareApel(f"Nu am putut contacta Twilio ({type(e).__name__}).") from None

    # De aici apelul exista deja: o eroare la urmarirea lui nu trebuie sa duca la un al doilea apel.
    sid, stare, durata, erori = apel.sid, apel.status, None, ()
    try:
        limita = time.monotonic() + asteapta_secunde
        while apel.status not in STARI_FINALE and time.monotonic() < limita:
            time.sleep(3)
            apel = client.calls(sid).fetch()
        stare = apel.status
        durata = int(apel.duration) if apel.duration else None
        time.sleep(3)  # erorile apar in Twilio cu cateva secunde intarziere
        erori = tuple(
            str(n.error_code) for n in client.calls(sid).notifications.list(limit=10)
        )
    except (TwilioRestException, RequestException):
        if stare not in STARI_FINALE:
            stare = "necunoscut"
    return RezultatApel(sid=sid, stare=stare, durata_secunde=durata, erori_twilio=erori)
