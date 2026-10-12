"""Primul filtru pentru emailuri, fara AI: urgent, ignorat sau de trimis la clasificare."""

import re
from dataclasses import dataclass

from jarvis.gmail import Email
from jarvis.reguli import Reguli

URGENT = "urgent"
IGNORAT = "ignorat"
DE_CLASIFICAT = "de_clasificat"

_CATEGORII_IGNORATE = {
    "CATEGORY_PROMOTIONS": "reclama (categoria Promotii din Gmail)",
    "CATEGORY_SOCIAL": "retea sociala (categoria Social din Gmail)",
    "CATEGORY_FORUMS": "forum sau lista de discutii (categoria Forumuri din Gmail)",
    "CATEGORY_UPDATES": "trimis automat (categoria Actualizari din Gmail)",
}
# Adrese de la care nu scrie un om: noreply@, notifications@, mailer-daemon@ ...
_ADRESA_AUTOMATA = re.compile(
    r"^(no[-_.]?reply|do[-_.]?not[-_.]?reply|notifications?|notify|alerts?|"
    r"newsletter|mailer[-_.]?daemon|bounces?|postmaster|automated)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Triere:
    fel: str
    motiv: str


def triaza(email: Email, reguli: Reguli) -> Triere:
    for adresa, inceput_subiect in reguli.expeditori_urgenti:
        if adresa in email.adresa and email.subiect.lower().startswith(inceput_subiect.lower()):
            return Triere(URGENT, "expeditor urgent din reguli")

    if email.etichete & {"SENT", "DRAFT", "SPAM", "TRASH"}:
        return Triere(IGNORAT, "nu e un email primit")
    for categorie, motiv in _CATEGORII_IGNORATE.items():
        if categorie in email.etichete:
            return Triere(IGNORAT, motiv)

    if _ADRESA_AUTOMATA.match(email.adresa):
        return Triere(IGNORAT, "trimis automat (adresa de tip noreply)")
    if "list-unsubscribe" in email.antete or "list-id" in email.antete:
        return Triere(IGNORAT, "trimis in masa (are antet de dezabonare)")
    if email.antete.get("precedence", "").lower() in ("bulk", "list", "junk"):
        return Triere(IGNORAT, "trimis in masa")
    if email.antete.get("auto-submitted", "no").lower() != "no":
        return Triere(IGNORAT, "raspuns automat")

    return Triere(DE_CLASIFICAT, "pare scris de un om")
