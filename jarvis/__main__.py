"""Comenzile lui Jarvis. Rulare: python -m jarvis <comanda>"""

import argparse
import sys
from datetime import datetime

from jarvis import gmail
from jarvis.apel import EroareApel, suna
from jarvis.clasificare import EroareClasificare, clasifica
from jarvis.triere import IGNORAT, URGENT, triaza
from jarvis.calendar_google import (
    FUS_ORAR,
    EroareAutorizare,
    autorizeaza,
    urmatoarele_evenimente,
)
from jarvis.config import EroareConfig, incarca_config_twilio
from jarvis.reguli import NUME_CULOARE, EroareReguli, incarca_reguli
from jarvis.serviciu import ZILE, Serviciu

MESAJ_TEST = (
    "Salut! Aici Jarvis. Acesta este un apel de test. "
    "Dacă auzi acest mesaj, legătura cu Twilio funcționează."
)


def apel_test(doar_verifica: bool) -> int:
    try:
        config = incarca_config_twilio()
    except EroareConfig as e:
        print(e)
        return 1
    print("Cheile Twilio sunt completate si au forma corecta.")
    if doar_verifica:
        print("Doar verificare: nu am sunat.")
        return 0

    print("Sun acum... (astept pana se incheie apelul)")
    try:
        rezultat = suna(config, MESAJ_TEST)
    except EroareApel as e:
        print(e)
        return 1
    durata = (
        f", durata {rezultat.durata_secunde} s"
        if rezultat.durata_secunde is not None
        else ""
    )
    print(f"Rezultat: {rezultat.stare} - {rezultat.explicatie}{durata}")
    print(f"Identificator apel (pentru Twilio Console): {rezultat.sid}")
    return 0 if rezultat.stare == "completed" else 1


def autorizare() -> int:
    print("Deschid browserul pentru autorizarea Google... (astept sa termini acolo)")
    try:
        autorizeaza()
    except EroareAutorizare as e:
        print(e)
        return 1
    print("Autorizare reusita. Jarvis poate citi calendarul si emailurile (doar citire).")
    return 0


def evenimente(cate: int) -> int:
    try:
        lista = urmatoarele_evenimente(cate)
    except EroareAutorizare as e:
        print(e)
        return 1
    if not lista:
        print("Nu ai niciun eveniment viitor in calendarul principal.")
        return 0
    print(f"Urmatoarele {len(lista)} evenimente (ora Romaniei):")
    for ev in lista:
        zi = f"{ZILE[ev.inceput.weekday()]} {ev.inceput:%d.%m.%Y}"
        if ev.toata_ziua:
            cand = f"{zi}  toata ziua"
        else:
            cand = f"{zi}  {ev.inceput:%H:%M}     "
        culoare = f"  [culoare {ev.culoare}]" if ev.culoare else ""
        print(f"  {cand}  {ev.titlu}{culoare}")
    return 0


def verifica_reguli() -> int:
    try:
        r = incarca_reguli()
    except EroareReguli as e:
        print(e)
        return 1
    print("Fisierul de reguli e corect:")
    print(f"  eveniment important: culoarea {NUME_CULOARE[r.culoare_importanta]}")
    print(f"  sun cu {r.minute_inainte} min inainte; verific la {r.minute_intre_verificari} min")
    print(f"  calendare: {', '.join('principal' if c == 'primary' else c for c in r.calendare)}")
    print(f"  eveniment important de o zi intreaga: apel la {r.ora_zi_intreaga:%H:%M}")
    if r.zile_nastere:
        print(f"  zile de nastere: apel la {r.ora_zile_nastere:%H:%M}")
    else:
        print("  zile de nastere: fara apel")
    if r.liniste:
        print(f"  ore de liniste: {r.liniste[0]:%H:%M}-{r.liniste[1]:%H:%M}")
    else:
        print("  ore de liniste: nu")
    print(f"  cel mult un apel la {r.minute_intre_apeluri} min si {r.apeluri_pe_zi} pe zi")
    if r.reincercare:
        print(f"  daca nu raspunzi: o reincercare dupa {r.minute_pana_la_reincercare} min")
    else:
        print("  daca nu raspunzi: fara reincercare")
    if r.emailuri:
        urgenti = ", ".join(
            f'{adresa} (subiect care incepe cu "{subiect}")' if subiect else adresa
            for adresa, subiect in r.expeditori_urgenti
        )
        print(f"  emailuri: da; expeditori urgenti: {urgenti or 'niciunul'}")
        print(f"  important la email: {r.instructiune_email}")
    else:
        print("  emailuri: nu")
    return 0


def email_test(cate: int, cu_claude: bool) -> int:
    """Arata ce ar decide Jarvis pentru ultimele emailuri din Inbox. Nu suna si nu tine minte nimic."""
    try:
        reguli = incarca_reguli()
        ids = gmail.ultimele_emailuri(cate)
    except (EroareReguli, EroareAutorizare) as e:
        print(e)
        return 1
    print(f"Ultimele {len(ids)} emailuri din Inbox (cel mai nou primul):")
    for id_ in ids:
        email = gmail.citeste_email(id_)
        if email is None:
            continue
        triere = triaza(email, reguli)
        print(f'\n  {email.nume} <{email.adresa}>: "{email.subiect}"')
        if triere.fel == URGENT:
            print(f"    -> URGENT, as suna imediat: {triere.motiv}")
        elif triere.fel == IGNORAT:
            print(f"    -> IGNORAT, nu ajunge la AI: {triere.motiv}")
        elif not cu_claude:
            print(f"    -> AR MERGE LA CLAUDE: {triere.motiv}")
        else:
            try:
                v = clasifica(email, reguli.instructiune_email)
            except (EroareClasificare, EroareConfig) as e:
                print(f"    -> Claude nu a putut clasifica: {e}")
                continue
            print(f"    -> Claude: {'IMPORTANT, as suna' if v.important else 'nu e important'} ({v.motiv})")
            if v.important:
                print(f'       La telefon: "Ai un email important de la {email.nume}. {v.rezumat}"')
    return 0


def porneste(proba: bool, o_data: bool, ora_simulata: str | None) -> int:
    acum = None
    if ora_simulata:
        if not proba:
            print("--simuleaza-ora merge doar impreuna cu --proba.")
            return 1
        try:
            acum = datetime.strptime(ora_simulata, "%Y-%m-%d %H:%M").replace(tzinfo=FUS_ORAR)
        except ValueError:
            print('Ora simulata trebuie scrisa asa: "2026-10-05 13:40"')
            return 1
    serviciu = Serviciu(proba)
    if acum or o_data:
        if acum:
            serviciu.jurnal.info("PROBA cu ora simulata: %s", ora_simulata)
        serviciu.verifica(acum)
        if not acum:
            serviciu.verifica_emailuri()
        return 0
    serviciu.ruleaza()
    return 0


def main() -> int:
    # Consola Windows nu foloseste mereu UTF-8; fara asta, diacriticele pot da eroare.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="jarvis")
    comenzi = parser.add_subparsers(dest="comanda", required=True)
    p_test = comenzi.add_parser(
        "apel-test", help="Ma suna si citeste o propozitie de test."
    )
    p_test.add_argument(
        "--verifica",
        action="store_true",
        help="Verifica doar cheile, fara sa sune.",
    )
    comenzi.add_parser(
        "autorizare", help="Prima autorizare Google, in browser (doar pe Windows)."
    )
    p_ev = comenzi.add_parser(
        "evenimente", help="Afiseaza urmatoarele evenimente din calendar."
    )
    p_ev.add_argument("--cate", type=int, default=10, help="Cate evenimente (implicit 10).")
    p_start = comenzi.add_parser(
        "porneste", help="Porneste Jarvis: verifica periodic calendarul si suna."
    )
    p_start.add_argument(
        "--proba", action="store_true", help="Decide si scrie in jurnal, dar nu suna."
    )
    p_start.add_argument(
        "--o-data", action="store_true", help="O singura verificare, apoi se opreste."
    )
    p_start.add_argument(
        "--simuleaza-ora",
        metavar='"AAAA-LL-ZZ HH:MM"',
        help="Doar cu --proba: o verificare ca si cum ar fi aceasta ora.",
    )
    comenzi.add_parser(
        "verifica-reguli", help="Citeste reguli_importanta.md si spune daca e corect."
    )
    p_email = comenzi.add_parser(
        "email-test", help="Arata ce ar decide Jarvis pentru ultimele emailuri. Nu suna."
    )
    p_email.add_argument("--cate", type=int, default=10, help="Cate emailuri (implicit 10).")
    p_email.add_argument(
        "--cu-claude",
        action="store_true",
        help="Trimite la Claude emailurile care trec de filtru (costa putin).",
    )
    args = parser.parse_args()
    if args.comanda == "email-test":
        return email_test(args.cate, args.cu_claude)
    if args.comanda == "porneste":
        return porneste(args.proba, args.o_data, args.simuleaza_ora)
    if args.comanda == "verifica-reguli":
        return verifica_reguli()
    if args.comanda == "apel-test":
        return apel_test(args.verifica)
    if args.comanda == "autorizare":
        return autorizare()
    if args.comanda == "evenimente":
        return evenimente(args.cate)
    return 0


if __name__ == "__main__":
    sys.exit(main())
