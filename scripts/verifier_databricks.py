"""Compare l'adaptateur Databricks réel à l'adaptateur local (CSV) : mêmes données, mêmes scores.
Usage : python scripts/verifier_databricks.py
"""
import os
from pathlib import Path

from dotenv import load_dotenv

from mcp_risque.adapters_databricks import DatabricksAdapter, connexion_depuis_env
from mcp_risque.donnees_synthetiques import DATE_REF
from mcp_risque.ports import CsvAdapter
from mcp_risque.score import score_acheteur

load_dotenv(Path(".env"))
local = CsvAdapter("data/synthetique")
distant = DatabricksAdapter(connexion_depuis_env(), os.environ.get("DATABRICKS_SCHEMA", "workspace.sentinelle"))

acheteurs = distant.lister_acheteurs()
print(f"Acheteurs lus dans Databricks : {len(acheteurs)}")
toutes = distant.get_toutes_factures()
print(f"Factures lues dans Databricks : {sum(len(v) for v in toutes.values())}")

par_siren = {a.siren: a for a in acheteurs}
ecarts = []
for a in local.lister_acheteurs():
    s_local = score_acheteur(local.get_factures(a.siren), DATE_REF)
    s_distant = score_acheteur(toutes.get(a.siren, []), DATE_REF)
    if s_local != s_distant or par_siren.get(a.siren) != a:
        ecarts.append(a.siren)

print("OK : Databricks et local donnent exactement les mêmes scores." if not ecarts
      else f"ÉCARTS sur {len(ecarts)} acheteurs : {ecarts[:5]}")
