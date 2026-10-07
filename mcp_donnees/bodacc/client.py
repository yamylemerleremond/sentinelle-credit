"""Appel à l'API open data du BODACC (plateforme OpenDataSoft).

Le client HTTP est injecté : en production un vrai httpx.Client,
en test un httpx.MockTransport qui rejoue les fixtures.
"""
import re
import time
from typing import Callable

import httpx

from .models import CompanySignal
from .parser import parse_bodacc_record

BASE_URL = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1"
RECORDS_PATH = "/catalog/datasets/annonces-commerciales/records"
PAGE_MAX = 100                         # limite par page de l'API
STATUTS_A_REESSAYER = {429, 500, 502, 503, 504}


class SirenInvalide(ValueError):
    pass


class BodaccIndisponible(RuntimeError):
    pass


def familles_suivies(pack: dict) -> list[str]:
    """Familles BODACC à interroger, lues dans le pack : jamais en dur dans le code."""
    return [
        famille for famille, regle in pack["signaux_bodacc"].items()
        if not famille.startswith("_") and regle["poids"] != "ignore"
    ]


def construire_where(siren: str, familles: list[str]) -> str:
    """Filtre ODSQL : le SIREN ET l'une des familles suivies."""
    ou_familles = " or ".join(f'familleavis="{f}"' for f in familles)
    return f'registre="{siren}" and ({ou_familles})'


def get_avec_reprise(
    client: httpx.Client,
    url: str,
    params: dict,
    essais: int = 3,
    attente_initiale: float = 1.0,
    dormir: Callable[[float], None] = time.sleep,
) -> httpx.Response:
    """GET avec reprise à attente croissante (1 s, 2 s, 4 s...) sur erreur temporaire."""
    attente = attente_initiale
    for essai in range(1, essais + 1):
        try:
            reponse = client.get(url, params=params)
            if reponse.status_code not in STATUTS_A_REESSAYER:
                reponse.raise_for_status()      # une 400 ou 404 ne se réessaie pas
                return reponse
            cause = f"statut {reponse.status_code}"
        except (httpx.TimeoutException, httpx.TransportError) as erreur:
            cause = type(erreur).__name__
        if essai < essais:
            dormir(attente)
            attente *= 2
    raise BodaccIndisponible(f"BODACC indisponible après {essais} essais ({cause})")


def fetch_company_signals(
    siren: str,
    pack: dict,
    client: httpx.Client,
    dormir: Callable[[float], None] = time.sleep,
) -> list[CompanySignal]:
    """Signaux BODACC d'une entreprise, du plus récent au plus ancien."""
    siren = re.sub(r"\s", "", siren or "")
    if not re.fullmatch(r"\d{9}", siren):
        raise SirenInvalide(f"SIREN invalide : {siren!r} (9 chiffres attendus)")

    params = {
        "where": construire_where(siren, familles_suivies(pack)),
        "order_by": "dateparution desc",
        "limit": PAGE_MAX,
    }
    reponse = get_avec_reprise(client, BASE_URL + RECORDS_PATH, params, dormir=dormir)
    resultats = reponse.json().get("results", [])

    signaux = [parse_bodacc_record(raw, pack) for raw in resultats]
    return [s for s in signaux if s is not None]


def creer_client(timeout: float = 10.0) -> httpx.Client:
    """Client de production : timeout explicite, jamais de requête sans limite."""
    return httpx.Client(timeout=timeout, headers={"User-Agent": "sentinelle-credit/0.1"})
