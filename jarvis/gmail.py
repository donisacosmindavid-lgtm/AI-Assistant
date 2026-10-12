"""Legatura cu Gmail (doar citire) si cu "cutia postala" Pub/Sub prin care Gmail anunta emailurile noi."""

import base64
import time
from dataclasses import dataclass
from email.utils import parseaddr

import google_auth_httplib2
import httplib2
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from jarvis.calendar_google import SCOPE_GMAIL, SCOPE_PUBSUB, incarca_autorizarea

# Numele proiectului Google Cloud si ale celor doua lucruri create in Pub/Sub.
PROIECT = "proiectul-tau-google-cloud"  # ID-ul proiectului tau Google Cloud
SUBIECT_PUBSUB = f"projects/{PROIECT}/topics/jarvis-gmail"
ABONAMENT_PUBSUB = f"projects/{PROIECT}/subscriptions/jarvis-gmail-sub"

# Cat din textul unui email se citeste (si se trimite mai departe la clasificare).
CARACTERE_TEXT = 2000
# Cat asteapta o singura intrebare catre Pub/Sub inainte sa renunte.
SECUNDE_ASTEPTARE_SEMNAL = 70


class IstoricExpirat(Exception):
    """Gmail nu mai tine minte punctul de la care citeam; se reia de la momentul prezent."""


@dataclass(frozen=True)
class Email:
    id: str
    nume: str  # numele afisat al expeditorului (sau adresa, daca nu are nume)
    adresa: str
    subiect: str
    etichete: frozenset[str]  # etichetele Gmail: INBOX, CATEGORY_UPDATES, ...
    antete: dict[str, str]  # doar antetele care arata o trimitere automata
    text: str  # inceputul textului


def _gmail():
    return build(
        "gmail", "v1", credentials=incarca_autorizarea(SCOPE_GMAIL), cache_discovery=False
    )


def porneste_urmarirea() -> str:
    """Cere Gmail sa anunte in Pub/Sub emailurile noi din Inbox. Intoarce punctul curent din istoric.

    Abonarea expira dupa circa 7 zile, deci se repeta zilnic.
    """
    raspuns = (
        _gmail()
        .users()
        .watch(
            userId="me",
            body={
                "topicName": SUBIECT_PUBSUB,
                "labelIds": ["INBOX"],
                "labelFilterBehavior": "INCLUDE",
            },
        )
        .execute()
    )
    return str(raspuns["historyId"])


def asteapta_semnal(secunde: float = SECUNDE_ASTEPTARE_SEMNAL) -> bool:
    """Asteapta un anunt de la Gmail. True daca a sosit cel putin unul."""
    creds = incarca_autorizarea(SCOPE_PUBSUB)
    http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=secunde))
    abonamente = build("pubsub", "v1", http=http, cache_discovery=False).projects().subscriptions()
    try:
        raspuns = abonamente.pull(
            subscription=ABONAMENT_PUBSUB, body={"maxMessages": 20}
        ).execute()
    except TimeoutError:
        return False  # nimic nou in acest interval
    primite = raspuns.get("receivedMessages", [])
    if not primite:
        return False
    # Anuntul spune doar "s-a schimbat ceva"; emailurile se citesc apoi din istoricul Gmail.
    abonamente.acknowledge(
        subscription=ABONAMENT_PUBSUB, body={"ackIds": [m["ackId"] for m in primite]}
    ).execute()
    return True


def emailuri_noi(de_la: str) -> tuple[list[str], str]:
    """Identificatorii emailurilor sosite in Inbox dupa punctul dat si noul punct din istoric."""
    istoric = _gmail().users().history()
    gasite: list[str] = []
    pagina = None
    while True:
        try:
            raspuns = istoric.list(
                userId="me",
                startHistoryId=de_la,
                historyTypes=["messageAdded"],
                labelId="INBOX",
                pageToken=pagina,
            ).execute()
        except HttpError as e:
            if e.resp.status == 404:
                raise IstoricExpirat() from None
            raise
        for intrare in raspuns.get("history", []):
            for adaugat in intrare.get("messagesAdded", []):
                id_ = adaugat["message"]["id"]
                if id_ not in gasite:
                    gasite.append(id_)
        pagina = raspuns.get("nextPageToken")
        if not pagina:
            return gasite, str(raspuns.get("historyId", de_la))


def ultimele_emailuri(cate: int) -> list[str]:
    """Identificatorii celor mai recente emailuri din Inbox (pentru comanda de proba)."""
    raspuns = (
        _gmail().users().messages().list(userId="me", labelIds=["INBOX"], maxResults=cate).execute()
    )
    return [m["id"] for m in raspuns.get("messages", [])]


def _text_din(parte: dict) -> str:
    """Primul text simplu gasit in email (fara atasamente)."""
    if parte.get("filename"):
        return ""
    if parte.get("mimeType") == "text/plain":
        date = parte.get("body", {}).get("data")
        if date:
            return base64.urlsafe_b64decode(date).decode("utf-8", errors="replace")
    for sub in parte.get("parts", []):
        text = _text_din(sub)
        if text:
            return text
    return ""


def citeste_email(id_: str) -> Email | None:
    """Emailul cu identificatorul dat, sau None daca a fost sters intre timp."""
    try:
        m = _gmail().users().messages().get(userId="me", id=id_, format="full").execute()
    except HttpError as e:
        if e.resp.status == 404:
            return None
        raise
    antete = {a["name"].lower(): a["value"] for a in m["payload"].get("headers", [])}
    nume, adresa = parseaddr(antete.get("from", ""))
    text = _text_din(m["payload"]) or m.get("snippet", "")
    return Email(
        id=m["id"],
        nume=nume or adresa,
        adresa=adresa.lower(),
        subiect=antete.get("subject", "(fara subiect)"),
        etichete=frozenset(m.get("labelIds", [])),
        antete={
            nume_antet: antete[nume_antet]
            for nume_antet in ("list-unsubscribe", "list-id", "precedence", "auto-submitted")
            if nume_antet in antete
        },
        text=" ".join(text.split())[:CARACTERE_TEXT],
    )


def asteapta_intre_intrebari(inceput: float, minim: float = 3.0) -> None:
    """Daca Pub/Sub a raspuns imediat "nimic", nu-l intreba din nou in aceeasi secunda."""
    ramas = minim - (time.monotonic() - inceput)
    if ramas > 0:
        time.sleep(ramas)
