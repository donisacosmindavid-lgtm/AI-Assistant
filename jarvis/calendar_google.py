"""Legatura cu Google Calendar (doar citire)."""

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from jarvis.config import RADACINA

SCOPE_CALENDAR = "https://www.googleapis.com/auth/calendar.readonly"
SCOPE_GMAIL = "https://www.googleapis.com/auth/gmail.readonly"
# Pentru "cutia postala" Pub/Sub prin care Gmail anunta ca a sosit un email.
SCOPE_PUBSUB = "https://www.googleapis.com/auth/pubsub"
SCOPES = [SCOPE_CALENDAR, SCOPE_GMAIL, SCOPE_PUBSUB]
FUS_ORAR = ZoneInfo("Europe/Bucharest")

FISIER_CLIENT = RADACINA / "credentials.json"
FISIER_TOKEN = RADACINA / "token.json"


class EroareAutorizare(Exception):
    """Autorizarea Google lipseste, a expirat sau a fost revocata."""

    def __init__(self, mesaj: str, a_expirat: bool = False):
        super().__init__(mesaj)
        # True cand a mers si s-a stricat (expirata/revocata): merita un apel de alerta.
        self.a_expirat = a_expirat


@dataclass(frozen=True)
class Eveniment:
    id: str
    titlu: str
    inceput: datetime | date
    toata_ziua: bool
    culoare: str | None
    # "default" pentru evenimente obisnuite, "birthday" pentru zile de nastere.
    # Emailurile de anuntat folosesc aceeasi forma: tip "email" sau "email_urgent",
    # iar titlul e chiar propozitia de spus la telefon.
    tip: str


def autorizeaza() -> None:
    """Prima autorizare: deschide browserul si salveaza token.json."""
    if not FISIER_CLIENT.exists():
        raise EroareAutorizare(
            f"Nu gasesc {FISIER_CLIENT.name} in {RADACINA}. "
            "Se descarca din Google Cloud Console (clientul OAuth de tip Desktop app)."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(FISIER_CLIENT), SCOPES)
    # Fara mesajul implicit: acela afiseaza adresa de autorizare, care contine ID-ul clientului.
    creds = flow.run_local_server(port=0, authorization_prompt_message="")
    FISIER_TOKEN.write_text(creds.to_json(), encoding="utf-8")


def incarca_autorizarea(*necesare: str) -> Credentials:
    """Autorizarea salvata, verificata ca are permisiunile cerute (implicit: calendarul)."""
    necesare = necesare or (SCOPE_CALENDAR,)
    if not FISIER_TOKEN.exists():
        raise EroareAutorizare(
            "Jarvis nu e inca autorizat la Google. Ruleaza: python -m jarvis autorizare"
        )
    # Fara lista de permisiuni: se folosesc cele acordate la autorizare, scrise in fisier.
    # Asa, un token mai vechi (doar calendar) merge in continuare pentru calendar.
    creds = Credentials.from_authorized_user_file(str(FISIER_TOKEN))
    if not set(necesare) <= set(creds.scopes or []):
        raise EroareAutorizare(
            "Autorizarea Google de acum nu include permisiunile pentru email. "
            "Ruleaza din nou: python -m jarvis autorizare"
        )
    if creds.valid:
        return creds
    if not creds.refresh_token:
        raise EroareAutorizare(
            "Autorizarea Google nu poate fi reinnoita. "
            "Ruleaza din nou: python -m jarvis autorizare",
            a_expirat=True,
        )
    try:
        creds.refresh(Request())
    except RefreshError:
        raise EroareAutorizare(
            "Autorizarea Google a expirat sau a fost revocata (invalid_grant). "
            "Ruleaza din nou: python -m jarvis autorizare",
            a_expirat=True,
        ) from None
    FISIER_TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _din_raspuns(e: dict) -> Eveniment:
    start = e["start"]
    toata_ziua = "date" in start
    if toata_ziua:
        inceput = date.fromisoformat(start["date"])
    else:
        inceput = datetime.fromisoformat(start["dateTime"]).astimezone(FUS_ORAR)
    return Eveniment(
        id=e["id"],
        titlu=e.get("summary", "(fara titlu)"),
        inceput=inceput,
        toata_ziua=toata_ziua,
        culoare=e.get("colorId"),
        tip=e.get("eventType", "default"),
    )


def _serviciu():
    return build(
        "calendar", "v3", credentials=incarca_autorizarea(), cache_discovery=False
    )


def evenimente_intre(
    inceput: datetime, sfarsit: datetime, calendar: str = "primary"
) -> list[Eveniment]:
    """Evenimentele care se suprapun cu intervalul dat (inclusiv cele de o zi intreaga)."""
    serviciu = _serviciu()
    rezultat: list[Eveniment] = []
    pagina = None
    while True:
        raspuns = (
            serviciu.events()
            .list(
                calendarId=calendar,
                timeMin=inceput.isoformat(),
                timeMax=sfarsit.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                pageToken=pagina,
            )
            .execute()
        )
        rezultat += [_din_raspuns(e) for e in raspuns.get("items", [])]
        pagina = raspuns.get("nextPageToken")
        if not pagina:
            return rezultat


def urmatoarele_evenimente(cate: int = 10, calendar: str = "primary") -> list[Eveniment]:
    """Urmatoarele evenimente; cele recurente vin ca aparitii separate."""
    serviciu = _serviciu()
    raspuns = (
        serviciu.events()
        .list(
            calendarId=calendar,
            timeMin=datetime.now(FUS_ORAR).isoformat(),
            maxResults=cate,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return [_din_raspuns(e) for e in raspuns.get("items", [])]
