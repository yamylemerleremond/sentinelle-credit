"""Enregistre la réponse brute du BODACC pour un SIREN, comme fixture de test.
Usage : python scripts/capturer_fixture.py 933407314 jeune_entreprise_liquidation
"""
import json
import sys
from pathlib import Path

from mcp_donnees.bodacc.client import (
    BASE_URL, RECORDS_PATH, PAGE_MAX, construire_where,
    creer_client, familles_suivies, get_avec_reprise,
)
from mcp_donnees.bodacc.parser import load_pack

siren, nom = sys.argv[1], sys.argv[2]
pack = load_pack("packs/risque_credit.yaml")
params = {
    "where": construire_where(siren, familles_suivies(pack)),
    "order_by": "dateparution desc",
    "limit": PAGE_MAX,
}

with creer_client() as client:
    reponse = get_avec_reprise(client, BASE_URL + RECORDS_PATH, params)

cible = Path("tests/fixtures") / f"{nom}.json"
cible.write_text(json.dumps(reponse.json(), ensure_ascii=False, indent=2), encoding="utf-8")
print(f"{len(reponse.json().get('results', []))} annonces enregistrées dans {cible}")