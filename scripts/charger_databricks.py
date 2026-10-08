"""Crée le schéma et les tables Sentinelle dans Databricks, puis charge les CSV.
Reconstruit tout l'environnement en une commande (Free Edition comme Azure Databricks).

Usage :
    python scripts/charger_databricks.py              # refuse d'écraser des tables non vides
    python scripts/charger_databricks.py --remplacer  # recrée les tables à partir des CSV
"""
import argparse
import csv
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from mcp_risque.adapters_databricks import SCHEMA_VALIDE, connexion_depuis_env

TABLES = {
    "acheteurs": {
        "siren": "STRING", "denomination": "STRING", "secteur": "STRING",
        "limite_credit": "DOUBLE", "encours": "DOUBLE", "profil": "STRING",
    },
    "factures": {
        "siren": "STRING", "numero": "STRING", "date_emission": "DATE",
        "date_echeance": "DATE", "montant": "DOUBLE", "date_paiement": "DATE",
    },
}
TAILLE_LOT = 100


def ddl(schema: str, table: str, remplacer: bool) -> str:
    colonnes = ", ".join(f"{c} {t}" for c, t in TABLES[table].items())
    verbe = "CREATE OR REPLACE TABLE" if remplacer else "CREATE TABLE IF NOT EXISTS"
    return f"{verbe} {schema}.{table} ({colonnes})"


def insert_par_lot(schema: str, table: str, lignes: list[dict]) -> tuple[str, dict]:
    """INSERT multi-lignes entièrement paramétré : aucune valeur n'est concaténée dans le SQL."""
    colonnes = list(TABLES[table])
    valeurs, params = [], {}
    for i, ligne in enumerate(lignes):
        marqueurs = []
        for c in colonnes:
            nom = f"{c}_{i}"
            brut = ligne[c] or None                       # chaîne vide du CSV -> NULL
            params[nom] = brut
            # CAST explicite : le paramètre arrive en texte, la colonne a son vrai type
            marqueurs.append(f"CAST(:{nom} AS {TABLES[table][c]})")
        valeurs.append(f"({', '.join(marqueurs)})")
    sql = f"INSERT INTO {schema}.{table} ({', '.join(colonnes)}) VALUES {', '.join(valeurs)}"
    return sql, params


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remplacer", action="store_true", help="recrée les tables existantes")
    parser.add_argument("--dossier", default="data/synthetique")
    args = parser.parse_args()

    load_dotenv(Path(".env"))
    schema = os.environ.get("DATABRICKS_SCHEMA", "workspace.sentinelle")
    if not SCHEMA_VALIDE.match(schema):
        sys.exit(f"Nom de schéma invalide : {schema!r}")

    with connexion_depuis_env()() as conn, conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        for table in TABLES:
            cur.execute(ddl(schema, table, args.remplacer))
            cur.execute(f"SELECT count(*) FROM {schema}.{table}")
            existantes = cur.fetchall()[0][0]
            if existantes and not args.remplacer:
                sys.exit(f"{schema}.{table} contient déjà {existantes} lignes. "
                         f"Relance avec --remplacer pour la recréer.")

            with open(Path(args.dossier) / f"{table}.csv", encoding="utf-8") as f:
                lignes = list(csv.DictReader(f))
            for debut in range(0, len(lignes), TAILLE_LOT):
                cur.execute(*insert_par_lot(schema, table, lignes[debut:debut + TAILLE_LOT]))

            cur.execute(f"SELECT count(*) FROM {schema}.{table}")
            print(f"{schema}.{table} : {cur.fetchall()[0][0]} lignes")


if __name__ == "__main__":
    main()
