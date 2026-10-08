import json
from datetime import date
from pathlib import Path

import pytest

from mcp_donnees.bodacc.parser import (
    date_fr, json_dans_chaine, load_pack, niveau_gravite,
    normalise_siren, parse_bodacc_record,
)

RACINE = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def pack():
    return load_pack(RACINE / "packs" / "risque_credit.yaml")


def charger(nom: str) -> dict:
    return json.loads((FIXTURES / nom).read_text(encoding="utf-8"))


# --- fonctions unitaires -------------------------------------------------------

@pytest.mark.parametrize("registre, attendu", [
    (["752461681", "752 461 681"], "752461681"),
    (["482 309 382"], "482309382"),
    ("752 461 681", "752461681"),
    ([None, "12345"], None),
    (None, None),
])
def test_normalise_siren(registre, attendu):
    assert normalise_siren(registre) == attendu


@pytest.mark.parametrize("texte, attendu", [
    ("10 décembre 2009", date(2009, 12, 10)),
    ("1er mars 2024", date(2024, 3, 1)),
    ("15 août 2023", date(2023, 8, 15)),
    ("31 février 2024", None),       # date impossible
    ("le mois dernier", None),
    (None, None),
])
def test_date_fr(texte, attendu):
    assert date_fr(texte) == attendu


@pytest.mark.parametrize("valeur, attendu", [
    ('{"a": 1}', {"a": 1}),
    ({"a": 1}, {"a": 1}),
    ("pas du json", None),
    ("[1, 2]", None),                # JSON valide mais pas un objet
    (None, None),
])
def test_json_dans_chaine(valeur, attendu):
    assert json_dans_chaine(valeur) == attendu


@pytest.mark.parametrize("nature, attendu", [
    ("Jugement de conversion en liquidation judiciaire", 5),
    ("Jugement d'ouverture d'une procédure de redressement judiciaire", 4),
    ("Jugement d'ouverture d'une procédure de sauvegarde", 3),
    ("Jugement arrêtant le plan de continuation", 2),
    ("Jugement de clôture pour extinction du passif", 1),
    ("Nature jamais vue", 3),
    (None, 3),
])
def test_niveau_gravite(nature, attendu, pack):
    assert niveau_gravite(nature, pack["gravite_jugement"]) == attendu


# --- enregistrements réels -------------------------------------------------------

def test_fournil_depot_confidentiel(pack):
    signal = parse_bodacc_record(charger("fournil_dpc_confidentiel.json"), pack)
    assert signal is not None
    assert signal.signal_id == "C202500182618"
    assert signal.siren == "752461681"
    assert signal.famille == "dpc"
    assert signal.poids == "contexte"
    assert signal.denomination == "Le Fournil des Bocages"
    assert signal.date_cloture == date(2024, 8, 31)
    assert signal.comptes_confidentiels is True
    assert signal.jugement is None


def test_sagittaire_personne_physique_exclue(pack):
    """Entrepreneur individuel : hors périmètre RGPD, même en liquidation."""
    assert parse_bodacc_record(charger("sagittaire_liquidation_pp.json"), pack) is None


def test_sagittaire_si_personne_morale(pack):
    """Même annonce, rejouée comme personne morale, pour tester la lecture du jugement."""
    raw = charger("sagittaire_liquidation_pp.json")
    raw["listepersonnes"] = raw["listepersonnes"].replace('"pp"', '"pm"')
    signal = parse_bodacc_record(raw, pack)
    assert signal.poids == "critique"
    assert signal.jugement.niveau_gravite == 5
    assert signal.jugement.date_jugement == date(2009, 12, 10)
    assert signal.jugement_manquant is False


# --- données sales : on ne plante jamais -------------------------------------------

def test_collective_sans_jugement_est_signalee(pack):
    raw = charger("fournil_dpc_confidentiel.json")
    raw.update(familleavis="collective", depot=None, jugement=None)
    signal = parse_bodacc_record(raw, pack)
    assert signal.poids == "critique"
    assert signal.jugement is None
    assert signal.jugement_manquant is True


def test_jugement_illisible_ne_plante_pas(pack):
    raw = charger("fournil_dpc_confidentiel.json")
    raw.update(familleavis="collective", jugement="{json cassé")
    assert parse_bodacc_record(raw, pack).jugement_manquant is True


@pytest.mark.parametrize("famille", [None, "inconnue", "divers"])
def test_familles_ignorees(famille, pack):
    raw = charger("fournil_dpc_confidentiel.json")
    raw["familleavis"] = famille
    assert parse_bodacc_record(raw, pack) is None


def test_sans_siren_ignore(pack):
    raw = charger("fournil_dpc_confidentiel.json")
    raw["registre"] = None
    assert parse_bodacc_record(raw, pack) is None


# --- nature générique : on lit le complément -------------------------------------------

from mcp_donnees.bodacc.parser import evaluer_gravite  # noqa: E402


@pytest.mark.parametrize("nature, complement, attendu", [
    ("Jugement de conversion en liquidation judiciaire", None, (5, "nature")),
    ("Autre jugement et ordonnance", "Jugement prononçant la liquidation judiciaire", (5, "complement")),
    ("Autre jugement et ordonnance", "ouverture d'une procédure de redressement judiciaire", (4, "complement")),
    ("Autre jugement et ordonnance", "Ordonnance du juge-commissaire", (3, "defaut")),
    ("Autre jugement et ordonnance", None, (3, "defaut")),
    # la nature explicite l'emporte sur le complément
    ("Jugement d'ouverture d'une procédure de sauvegarde", "désignant mandataire, liquidation judiciaire évitée", (3, "nature")),
])
def test_evaluer_gravite(nature, complement, attendu, pack):
    assert evaluer_gravite(nature, complement, pack["gravite_jugement"]) == attendu


def test_nature_generique_dans_un_enregistrement(pack):
    raw = charger("fournil_dpc_confidentiel.json")
    raw.update(familleavis="collective", jugement=json.dumps({
        "famille": "Jugement", "nature": "Autre jugement et ordonnance",
        "date": "1er octobre 2026",
        "complementJugement": "Jugement d'ouverture d'une procédure de redressement judiciaire",
    }))
    j = parse_bodacc_record(raw, pack).jugement
    assert (j.niveau_gravite, j.source_gravite) == (4, "complement")
