"""Citeste cheile din .env si verifica doar forma lor (valorile nu se afiseaza niciodata)."""

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RADACINA = Path(__file__).resolve().parent.parent
FISIER_ENV = RADACINA / ".env"

_TELEFON = re.compile(r"^\+\d{8,15}$")
_SID = re.compile(r"^AC[0-9a-fA-F]{32}$")


class EroareConfig(Exception):
    """Lipseste ceva din .env sau are o forma gresita."""


@dataclass(frozen=True)
class ConfigTwilio:
    account_sid: str
    auth_token: str
    numar_twilio: str
    numar_meu: str

    def secrete(self) -> list[str]:
        return [self.account_sid, self.auth_token, self.numar_twilio, self.numar_meu]


def incarca_cheia_anthropic() -> None:
    """Pune cheia Claude din .env la indemana librariei anthropic (care o citeste singura)."""
    load_dotenv(FISIER_ENV, override=True)
    cheie = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not cheie:
        raise EroareConfig("Probleme in .env:\n  - ANTHROPIC_API_KEY: lipseste (e gol)")
    if not cheie.startswith("sk-ant-"):
        raise EroareConfig("Probleme in .env:\n  - ANTHROPIC_API_KEY: trebuie sa inceapa cu sk-ant-")
    os.environ["ANTHROPIC_API_KEY"] = cheie


def incarca_config_twilio() -> ConfigTwilio:
    if not FISIER_ENV.exists():
        raise EroareConfig(f"Nu gasesc fisierul {FISIER_ENV.name} in {RADACINA}.")
    load_dotenv(FISIER_ENV, override=True)

    valori = {
        nume: os.getenv(nume, "").strip()
        for nume in (
            "TWILIO_ACCOUNT_SID",
            "TWILIO_AUTH_TOKEN",
            "TWILIO_FROM_NUMBER",
            "MY_PHONE_NUMBER",
        )
    }

    probleme = []
    for nume, valoare in valori.items():
        if not valoare:
            probleme.append(f"{nume}: lipseste (e gol)")
    if valori["TWILIO_ACCOUNT_SID"] and not _SID.match(valori["TWILIO_ACCOUNT_SID"]):
        probleme.append(
            "TWILIO_ACCOUNT_SID: trebuie sa inceapa cu AC si sa aiba 34 de caractere"
        )
    for nume in ("TWILIO_FROM_NUMBER", "MY_PHONE_NUMBER"):
        if valori[nume] and not _TELEFON.match(valori[nume]):
            probleme.append(
                f"{nume}: trebuie sa fie in format international, cu + si fara spatii"
                " (ex. +40700000000)"
            )
    if probleme:
        raise EroareConfig(
            "Probleme in .env:\n" + "\n".join(f"  - {p}" for p in probleme)
        )

    return ConfigTwilio(
        account_sid=valori["TWILIO_ACCOUNT_SID"],
        auth_token=valori["TWILIO_AUTH_TOKEN"],
        numar_twilio=valori["TWILIO_FROM_NUMBER"],
        numar_meu=valori["MY_PHONE_NUMBER"],
    )
