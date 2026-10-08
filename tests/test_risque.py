from collections import defaultdict
from datetime import date, timedelta

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from mcp_risque import server
from mcp_risque.donnees_synthetiques import DATE_REF, generer_portefeuille, luhn_valide
from mcp_risque.models import Facture
from mcp_risque.ports import CsvAdapter, MemoryAdapter, exporter_csv
from mcp_risque.score import score_acheteur


@pytest.fixture(scope="module")
def portefeuille():
    acheteurs, factures = generer_portefeuille()
    par_siren = defaultdict(list)
    for f in factures:
        par_siren[f.siren].append(f)
    return acheteurs, factures, par_siren


def niveaux_par_profil(portefeuille):
    acheteurs, _, par_siren = portefeuille
    res = defaultdict(list)
    for a in acheteurs:
        res[a.profil].append(score_acheteur(par_siren[a.siren], DATE_REF)["niveau"])
    return res


# --- générateur ---------------------------------------------------------------------

def test_generateur_deterministe():
    assert generer_portefeuille()[0] == generer_portefeuille()[0]


def test_siren_fictifs_jamais_reels(portefeuille):
    """Un vrai SIREN respecte toujours Luhn : les nôtres jamais, aucune collision possible."""
    assert all(not luhn_valide(a.siren) for a in portefeuille[0])
    assert luhn_valide("752461681")           # le Fournil, entreprise réelle


# --- score : chaque profil est reconnu -----------------------------------------------

def test_defauts_en_alerte(portefeuille):
    assert set(niveaux_par_profil(portefeuille)["defaut"]) == {"alerte"}


def test_degradations_detectees(portefeuille):
    assert all(n in ("vigilance", "alerte") for n in niveaux_par_profil(portefeuille)["degradation"])


def test_erratiques_pas_alertes(portefeuille):
    """Payeurs bruyants mais stables : la MAD évite les fausses alertes."""
    assert set(niveaux_par_profil(portefeuille)["erratique"]) == {"normal"}


def test_peu_de_faux_positifs(portefeuille):
    sains = niveaux_par_profil(portefeuille)["sain"]
    assert "alerte" not in sains
    assert sains.count("normal") / len(sains) >= 0.9


# --- score : cas limites ------------------------------------------------------------

def facture(echeance: date, retard: int | None, montant=10_000.0, n=0) -> Facture:
    paiement = echeance + timedelta(days=retard) if retard is not None else None
    return Facture(siren="123456789", numero=f"F{n}", date_emission=echeance - timedelta(days=30),
                   date_echeance=echeance, montant=montant, date_paiement=paiement)


def test_historique_trop_court():
    factures = [facture(DATE_REF - timedelta(days=30 * k), 2, n=k) for k in range(4)]
    s = score_acheteur(factures, DATE_REF)
    assert s["donnees_suffisantes"] is False and s["score"] is None and s["niveau"] == "inconnu"


def test_payeur_lent_mais_stable_normal():
    factures = [facture(DATE_REF - timedelta(days=30 * k), 45, n=k) for k in range(16)]
    assert score_acheteur(factures, DATE_REF)["niveau"] == "normal"


def test_impaye_ancien_force_alerte():
    factures = [facture(DATE_REF - timedelta(days=30 * k), 2, n=k) for k in range(3, 16)]
    factures.append(facture(DATE_REF - timedelta(days=90), None, n=99))
    s = score_acheteur(factures, DATE_REF)
    assert s["defaut_paiement"] is True and s["score"] == 1.0 and s["niveau"] == "alerte"


# --- port CSV : aller-retour ----------------------------------------------------------

def test_csv_aller_retour(tmp_path, portefeuille):
    acheteurs, factures, _ = portefeuille
    exporter_csv(acheteurs, factures, tmp_path)
    port = CsvAdapter(tmp_path)
    a = acheteurs[0]
    assert port.get_acheteur(a.siren) == a
    assert sorted(port.get_factures(a.siren), key=lambda f: f.numero) == \
        sorted(MemoryAdapter(acheteurs, factures).get_factures(a.siren), key=lambda f: f.numero)


# --- serveur MCP ----------------------------------------------------------------------

async def appeler(outil: str, args: dict) -> dict:
    async with Client(server.mcp) as client:
        return (await client.call_tool(outil, args)).data


async def test_outil_score_acheteur(portefeuille):
    defaillant = next(a for a in portefeuille[0] if a.profil == "defaut")
    data = await appeler("score_acheteur", {"siren": defaillant.siren})
    assert data["comportement_paiement"]["niveau"] == "alerte"
    assert data["exposition"]["limite_credit"] == defaillant.limite_credit


async def test_acheteur_inconnu_message_clair():
    with pytest.raises(ToolError, match="portefeuille"):
        await appeler("score_acheteur", {"siren": "752461681"})


async def test_acheteurs_a_surveiller_ordre(portefeuille):
    data = await appeler("acheteurs_a_surveiller", {"niveau_min": "alerte"})
    assert data["nb_acheteurs_portefeuille"] == 50
    assert all(a["niveau"] == "alerte" for a in data["acheteurs"])
    profils = {a.siren: a.profil for a in portefeuille[0]}
    assert {profils[a["siren"]] for a in data["acheteurs"]} <= {"defaut", "degradation"}


# --- tendance : un impayé récent n'est pas une amélioration ---------------------------

def test_mois_impaye_marque_comme_minimum(portefeuille):
    """Bug vu en démo : le dernier mois d'un défaillant affichait 15 j, lu comme une
    amélioration alors que les factures étaient simplement impayées et récentes."""
    acheteurs, _, par_siren = portefeuille
    defaillant = next(a for a in acheteurs if a.profil == "defaut")
    tendance = score_acheteur(par_siren[defaillant.siren], DATE_REF)["tendance_6_mois"]
    dernier = tendance[-1]
    assert dernier["valeur_minimale"] is True
    assert dernier["impayes_en_cours"] > 0


def test_mois_paye_pas_marque(portefeuille):
    acheteurs, _, par_siren = portefeuille
    sain = next(a for a in acheteurs if a.profil == "sain")
    tendance = score_acheteur(par_siren[sain.siren], DATE_REF)["tendance_6_mois"]
    assert not any(m["valeur_minimale"] for m in tendance[:-1])