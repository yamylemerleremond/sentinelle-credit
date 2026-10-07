import json
from pathlib import Path

import httpx
import pytest

from mcp_donnees.bodacc.client import (
    BodaccIndisponible, SirenInvalide, construire_where,
    familles_suivies, fetch_company_signals,
)
from mcp_donnees.bodacc.parser import load_pack

RACINE = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def pack():
    return load_pack(RACINE / "packs" / "risque_credit.yaml")


def charger(nom: str) -> dict:
    return json.loads((FIXTURES / nom).read_text(encoding="utf-8"))


def client_simule(reponses: list, appels: list) -> httpx.Client:
    """Rejoue les réponses dans l'ordre et note chaque requête reçue."""
    file_attente = list(reponses)

    def gerer(requete: httpx.Request) -> httpx.Response:
        appels.append(requete)
        suivante = file_attente.pop(0)
        if isinstance(suivante, Exception):
            raise suivante
        statut, corps = suivante
        return httpx.Response(statut, json=corps)

    return httpx.Client(transport=httpx.MockTransport(gerer))


def ne_pas_dormir(_secondes: float) -> None:
    pass


# --- construction de la requête ---------------------------------------------------

def test_familles_lues_dans_le_pack(pack):
    familles = familles_suivies(pack)
    assert "collective" in familles and "dpc" in familles
    assert "_defaut" not in familles
    assert "divers" not in familles          # absente du pack, donc ignorée


def test_where_odsql():
    assert construire_where("752461681", ["collective", "dpc"]) == (
        'registre="752461681" and (familleavis="collective" or familleavis="dpc")'
    )


def test_parametres_envoyes(pack):
    appels = []
    client = client_simule([(200, {"results": []})], appels)
    fetch_company_signals("752 461 681", pack, client)
    params = appels[0].url.params
    assert 'registre="752461681"' in params["where"]
    assert params["order_by"] == "dateparution desc"
    assert params["limit"] == "100"


# --- filtrage des résultats ----------------------------------------------------------

def test_resultats_parses_et_filtres(pack):
    """Le Fournil est gardé, le Sagittaire (personne physique) est écarté."""
    corps = {"results": [
        charger("fournil_dpc_confidentiel.json"),
        charger("sagittaire_liquidation_pp.json"),
    ]}
    client = client_simule([(200, corps)], [])
    signaux = fetch_company_signals("752461681", pack, client)
    assert [s.signal_id for s in signaux] == ["C202500182618"]


# --- robustesse -------------------------------------------------------------------

@pytest.mark.parametrize("siren", ["12345", "ABCDEFGHI", "", None, '752461681" or "1"="1'])
def test_siren_invalide_aucun_appel(siren, pack):
    appels = []
    client = client_simule([], appels)
    with pytest.raises(SirenInvalide):
        fetch_company_signals(siren, pack, client)
    assert appels == []


def test_reprise_apres_503(pack):
    attentes = []
    appels = []
    corps = {"results": [charger("fournil_dpc_confidentiel.json")]}
    client = client_simule([(503, {}), (200, corps)], appels)
    signaux = fetch_company_signals("752461681", pack, client, dormir=attentes.append)
    assert len(signaux) == 1
    assert len(appels) == 2
    assert attentes == [1.0]


def test_reprise_apres_timeout(pack):
    appels = []
    client = client_simule([httpx.ReadTimeout("lent"), (200, {"results": []})], appels)
    assert fetch_company_signals("752461681", pack, client, dormir=ne_pas_dormir) == []
    assert len(appels) == 2


def test_indisponible_apres_trois_essais(pack):
    attentes = []
    client = client_simule([(503, {}), (502, {}), (503, {})], [])
    with pytest.raises(BodaccIndisponible, match="3 essais"):
        fetch_company_signals("752461681", pack, client, dormir=attentes.append)
    assert attentes == [1.0, 2.0]            # attente croissante


def test_erreur_400_pas_reessayee(pack):
    appels = []
    client = client_simule([(400, {"error": "requête invalide"})], appels)
    with pytest.raises(httpx.HTTPStatusError):
        fetch_company_signals("752461681", pack, client, dormir=ne_pas_dormir)
    assert len(appels) == 1
