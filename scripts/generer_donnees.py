"""Génère le portefeuille fictif en CSV (data/synthetique/), prêt à charger dans Databricks.
Usage : python scripts/generer_donnees.py
"""
from collections import Counter
from pathlib import Path

from mcp_risque.donnees_synthetiques import generer_portefeuille
from mcp_risque.ports import exporter_csv

DOSSIER = Path("data/synthetique")
acheteurs, factures = generer_portefeuille()
exporter_csv(acheteurs, factures, DOSSIER)
print(f"{len(acheteurs)} acheteurs, {len(factures)} factures → {DOSSIER}/")
print("Profils :", dict(Counter(a.profil for a in acheteurs)))
