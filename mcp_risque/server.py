"""Serveur MCP « sentinelle-risque » : exposition et comportement de paiement des acheteurs.

Les données sont FICTIVES (portefeuille synthétique). Lancement : python -m mcp_risque.server
"""
import os
import re
from datetime import date
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from .donnees_synthetiques import DATE_REF, generer_portefeuille
from .ports import AcheteurInconnu, CsvAdapter, MemoryAdapter, RiskDataPort
from .score import score_acheteur as calculer_score

RACINE = Path(__file__).resolve().parents[1]
ORDRE_NIVEAUX = {"defaut": 0, "alerte": 1, "vigilance": 2, "inconnu": 3, "normal": 4}

mcp = FastMCP("sentinelle-risque")


def creer_port() -> RiskDataPort:
    """Choix de l'adaptateur par configuration (variable d'environnement)."""
    backend = os.environ.get("SENTINELLE_DATA_BACKEND", "local")
    if backend == "local":
        dossier = RACINE / "data" / "synthetique"
        if (dossier / "acheteurs.csv").exists():
            return CsvAdapter(dossier)
        return MemoryAdapter(*generer_portefeuille())
    raise ToolError(f"Backend de données inconnu : {backend}")


_port = creer_port()
_date_ref = date.fromisoformat(os.environ.get("SENTINELLE_DATE_REF", DATE_REF.isoformat()))


def _siren(valeur: str) -> str:
    siren = re.sub(r"\s", "", valeur or "")
    if not re.fullmatch(r"\d{9}", siren):
        raise ToolError(f"SIREN invalide : {valeur!r} (9 chiffres attendus)")
    return siren


def _analyse(siren: str) -> dict:
    acheteur = _port.get_acheteur(siren)
    score = calculer_score(_port.get_factures(siren), _date_ref)
    return {
        "siren": siren,
        "denomination": acheteur.denomination,
        "secteur": acheteur.secteur,
        "exposition": {
            "limite_credit": acheteur.limite_credit,
            "encours": acheteur.encours,
            "taux_utilisation": round(acheteur.encours / acheteur.limite_credit, 2),
        },
        "comportement_paiement": score,
    }


@mcp.tool
def score_acheteur(siren: str) -> dict:
    """Exposition et score de dégradation des paiements d'un acheteur couvert.

    `comportement_paiement.score` va de 0 (comportement habituel) à 1 (forte dégradation
    ou défaut de paiement) ; `niveau` vaut normal, vigilance, alerte, ou inconnu si
    l'historique est trop court. Le score compare l'acheteur à son propre passé :
    un payeur habituellement lent n'est pas en alerte pour autant.
    Dans `tendance_6_mois`, un mois avec `valeur_minimale: true` contient des factures
    encore impayées : son retard continue d'augmenter. Une valeur plus basse sur un tel
    mois n'est JAMAIS une amélioration, seulement des impayés plus récents.
    Données internes FICTIVES de démonstration. Ne jamais inventer un chiffre absent.

    Args:
        siren: SIREN à 9 chiffres d'un acheteur du portefeuille.
    """
    try:
        return _analyse(_siren(siren))
    except AcheteurInconnu as e:
        raise ToolError(f"{e} Il n'est pas dans le portefeuille couvert.") from e


@mcp.tool
def acheteurs_a_surveiller(niveau_min: str = "vigilance", limite: int = 10) -> dict:
    """Liste les acheteurs du portefeuille dont le comportement de paiement se dégrade,
    les plus préoccupants d'abord (défaut, puis alerte, puis vigilance ; à niveau égal,
    la plus forte exposition d'abord).

    Args:
        niveau_min: « alerte » pour ne garder que les cas graves, « vigilance » sinon.
        limite: nombre maximal d'acheteurs renvoyés (1 à 50).
    """
    if niveau_min not in ("alerte", "vigilance"):
        raise ToolError("niveau_min doit valoir « alerte » ou « vigilance ».")
    seuil = ORDRE_NIVEAUX[niveau_min]
    limite = max(1, min(limite, 50))

    analyses = [_analyse(a.siren) for a in _port.lister_acheteurs()]
    retenus = [a for a in analyses if ORDRE_NIVEAUX[a["comportement_paiement"]["niveau"]] <= seuil
               or a["comportement_paiement"]["defaut_paiement"]]
    retenus.sort(key=lambda a: (ORDRE_NIVEAUX[a["comportement_paiement"]["niveau"]],
                                -a["exposition"]["encours"]))
    return {
        "date_reference": _date_ref.isoformat(),
        "nb_acheteurs_portefeuille": len(analyses),
        "nb_a_surveiller": len(retenus),
        "acheteurs": [
            {"siren": a["siren"], "denomination": a["denomination"],
             "niveau": a["comportement_paiement"]["niveau"],
             "score": a["comportement_paiement"]["score"],
             "encours": a["exposition"]["encours"],
             "explication": a["comportement_paiement"]["explication"]}
            for a in retenus[:limite]
        ],
    }


if __name__ == "__main__":
    mcp.run()