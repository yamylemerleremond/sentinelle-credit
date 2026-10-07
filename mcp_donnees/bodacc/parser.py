"""Transforme un enregistrement brut de l'API BODACC en CompanySignal.

Règle d'or : ne jamais planter sur une donnée sale. Un champ illisible
devient None, et c'est la couche de confiance qui décide quoi en faire.
"""
import json
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .models import CompanySignal, Jugement

MOIS_FR = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
}


def load_pack(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# --- petites fonctions pures, testables une par une -------------------------

def normalise(texte: str) -> str:
    """Minuscules, sans accents : 'Clôture' -> 'cloture'."""
    sans_accents = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return sans_accents.lower().strip()


def normalise_siren(registre: Any) -> str | None:
    """Le champ registre contient ['752 461 681', '752461681'] : on garde 9 chiffres."""
    valeurs = registre if isinstance(registre, list) else [registre]
    for v in valeurs:
        if v is None:
            continue
        chiffres = re.sub(r"\D", "", str(v))
        if len(chiffres) == 9:
            return chiffres
    return None


def json_dans_chaine(valeur: Any) -> dict | None:
    """Les détails BODACC sont du JSON stocké dans une chaîne. Parsing défensif."""
    if valeur is None:
        return None
    if isinstance(valeur, dict):
        return valeur
    try:
        resultat = json.loads(valeur)
    except (TypeError, ValueError):
        return None
    return resultat if isinstance(resultat, dict) else None


def date_fr(texte: str | None) -> date | None:
    """'10 décembre 2009' ou '1er mars 2024' -> date. None si illisible."""
    if not texte:
        return None
    m = re.match(r"^\s*(\d{1,2})(?:er)?\s+([a-zA-Zéèêûôàç]+)\s+(\d{4})", texte)
    if not m:
        return None
    jour, mois_txt, annee = m.groups()
    mois = MOIS_FR.get(normalise(mois_txt))
    if not mois:
        return None
    try:
        return date(int(annee), mois, int(jour))
    except ValueError:
        return None


def date_iso(texte: str | None) -> date | None:
    try:
        return date.fromisoformat(texte) if texte else None
    except ValueError:
        return None


def niveau_gravite(nature: str | None, regles: list[dict]) -> int:
    """Premier motif du pack trouvé dans la nature du jugement."""
    texte = normalise(nature or "")
    for regle in regles:
        motif = regle["motif"]
        if motif == "*" or normalise(motif) in texte:
            return regle["niveau"]
    return 3


def personnes(listepersonnes: Any) -> list[dict]:
    """'personne' peut être un objet seul ou une liste d'objets."""
    contenu = json_dans_chaine(listepersonnes) or {}
    p = contenu.get("personne")
    if isinstance(p, list):
        return [x for x in p if isinstance(x, dict)]
    return [p] if isinstance(p, dict) else []


# --- fonction principale ------------------------------------------------------

def parse_bodacc_record(raw: dict, pack: dict) -> CompanySignal | None:
    """Renvoie None si l'annonce est hors périmètre (pas de SIREN, personne physique, poids ignoré)."""
    siren = normalise_siren(raw.get("registre"))
    date_parution = date_iso(raw.get("dateparution"))
    if not siren or not date_parution or not raw.get("id"):
        return None

    # Périmètre RGPD : on ne garde que les types de personne autorisés par le pack.
    liste = personnes(raw.get("listepersonnes"))
    types_retenus = set(pack.get("types_personne_retenus", ["pm"]))
    if liste and not any(p.get("typePersonne") in types_retenus for p in liste):
        return None
    personne = next((p for p in liste if p.get("typePersonne") in types_retenus), {})

    famille = raw.get("familleavis") or "inconnue"
    regle = pack["signaux_bodacc"].get(famille, pack["signaux_bodacc"]["_defaut"])
    if regle["poids"] == "ignore":
        return None

    # Détail du jugement (procédures collectives)
    jugement, jugement_manquant = None, False
    if regle.get("detail") == "jugement":
        j = json_dans_chaine(raw.get("jugement"))
        if j:
            jugement = Jugement(
                famille=j.get("famille"),
                nature=j.get("nature"),
                date_jugement=date_fr(j.get("date")),
                complement=j.get("complementJugement"),
                niveau_gravite=niveau_gravite(j.get("nature"), pack["gravite_jugement"]),
            )
        else:
            jugement_manquant = True

    # Détail du dépôt des comptes
    depot = json_dans_chaine(raw.get("depot")) or {}
    descriptif = normalise(depot.get("descriptif") or "")

    return CompanySignal(
        signal_id=raw["id"],
        siren=siren,
        date_parution=date_parution,
        famille=famille,
        famille_lib=raw.get("familleavis_lib"),
        poids=regle["poids"],
        type_avis=raw.get("typeavis"),
        denomination=personne.get("denomination") or raw.get("commercant"),
        forme_juridique=personne.get("formeJuridique"),
        tribunal=raw.get("tribunal"),
        date_cloture=date_iso(depot.get("dateCloture")),
        comptes_confidentiels="confidentialite" in descriptif,
        jugement=jugement,
        jugement_manquant=jugement_manquant,
        source_url=raw.get("url_complete"),
    )
