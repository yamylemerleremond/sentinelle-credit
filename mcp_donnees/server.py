"""Serveur MCP « sentinelle-donnees » : expose les signaux publics d'une entreprise.

Lancement local (Claude Desktop) : python -m mcp_donnees.server
"""
import os
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from .bodacc.client import BodaccIndisponible, SirenInvalide, creer_client, fetch_company_signals
from .bodacc.parser import load_pack

RACINE = Path(__file__).resolve().parents[1]
PACK_PATH = Path(os.environ.get("SENTINELLE_PACK", RACINE / "packs" / "risque_credit.yaml"))
ORDRE_POIDS = ["contexte", "moyen", "eleve", "critique"]

mcp = FastMCP("sentinelle-donnees")
_pack = load_pack(PACK_PATH)


def resumer(signaux: list) -> dict:
    """Synthèse lisible par l'agent : le signal le plus grave d'abord."""
    if not signaux:
        return {"nb_signaux": 0, "poids_max": None, "gravite_max_jugement": None}
    poids_max = max((s.poids for s in signaux), key=ORDRE_POIDS.index)
    gravites = [s.jugement.niveau_gravite for s in signaux if s.jugement]
    return {
        "nb_signaux": len(signaux),
        "poids_max": poids_max,
        "gravite_max_jugement": max(gravites) if gravites else None,
        "procedure_sans_detail": any(s.jugement_manquant for s in signaux),
    }


@mcp.tool
def get_company_signals(siren: str) -> dict:
    """Signaux publics BODACC d'une entreprise française (procédures collectives,
    radiations, conciliations, ventes, dépôts de comptes...), du plus récent au plus ancien.

    Chaque signal porte un poids (critique, eleve, moyen, contexte) issu du pack métier.
    Pour une procédure collective, `jugement.niveau_gravite` va de 1 (clôture) à 5
    (liquidation judiciaire) et `source_gravite` indique d'où vient ce niveau.
    Si `procedure_sans_detail` est vrai, la source est incomplète : le dire, ne pas deviner.

    Args:
        siren: numéro SIREN à 9 chiffres (les espaces sont acceptés).
    """
    try:
        with creer_client() as client:
            signaux = fetch_company_signals(siren, _pack, client)
    except SirenInvalide as e:
        raise ToolError(str(e)) from e
    except BodaccIndisponible as e:
        raise ToolError(f"{e}. Réessayer plus tard ; ne pas conclure à l'absence de risque.") from e

    return {
        "siren": siren.replace(" ", ""),
        "source": "BODACC (open data DILA)",
        "resume": resumer(signaux),
        "signaux": [s.model_dump(mode="json", exclude_none=True) for s in signaux],
    }


if __name__ == "__main__":
    mcp.run()
