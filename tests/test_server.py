"""Teste le serveur MCP comme le ferait Claude : via un client MCP en mémoire."""
import json
from pathlib import Path

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from mcp_donnees import server

FIXTURES = Path(__file__).parent / "fixtures"


def faux_client(statuts_et_corps):
    file_attente = list(statuts_et_corps)

    def gerer(_requete):
        statut, corps = file_attente.pop(0)
        return httpx.Response(statut, json=corps)

    return lambda: httpx.Client(transport=httpx.MockTransport(gerer))


@pytest.fixture
def bodacc(monkeypatch):
    """Remplace l'API BODACC par des réponses construites dans le test."""
    def installer(*reponses):
        monkeypatch.setattr(server, "creer_client", faux_client(reponses))
        monkeypatch.setattr("time.sleep", lambda _s: None)
    return installer


async def appeler(siren: str) -> dict:
    async with Client(server.mcp) as client:
        resultat = await client.call_tool("get_company_signals", {"siren": siren})
        return resultat.data


async def test_outil_declare():
    async with Client(server.mcp) as client:
        outils = {t.name: t for t in await client.list_tools()}
    assert "get_company_signals" in outils
    assert "siren" in outils["get_company_signals"].input_schema["properties"]


async def test_signaux_et_resume(bodacc):
    fournil = json.loads((FIXTURES / "fournil_dpc_confidentiel.json").read_text(encoding="utf-8"))
    bodacc((200, {"results": [fournil]}))
    data = await appeler("752 461 681")
    assert data["siren"] == "752461681"
    assert data["resume"] == {
        "nb_signaux": 1, "poids_max": "contexte",
        "gravite_max_jugement": None, "procedure_sans_detail": False,
    }
    assert data["signaux"][0]["comptes_confidentiels"] is True


async def test_liquidation_resume_critique(bodacc):
    raw = json.loads((FIXTURES / "sagittaire_liquidation_pp.json").read_text(encoding="utf-8"))
    raw["listepersonnes"] = raw["listepersonnes"].replace('"pp"', '"pm"')
    bodacc((200, {"results": [raw]}))
    resume = (await appeler("482309382"))["resume"]
    assert resume["poids_max"] == "critique"
    assert resume["gravite_max_jugement"] == 5


async def test_aucun_signal(bodacc):
    bodacc((200, {"results": []}))
    assert (await appeler("752461681"))["resume"]["nb_signaux"] == 0


async def test_siren_invalide_message_clair(bodacc):
    bodacc()
    with pytest.raises(ToolError, match="SIREN invalide"):
        await appeler("12345")


async def test_bodacc_en_panne(bodacc):
    bodacc((503, {}), (503, {}), (503, {}))
    with pytest.raises(ToolError, match="ne pas conclure"):
        await appeler("752461681")
