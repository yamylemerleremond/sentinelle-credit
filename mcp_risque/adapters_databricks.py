"""Adaptateur Databricks du port RiskDataPort.

Lit les tables `acheteurs` et `factures` via un SQL warehouse. Ne calcule rien :
le score reste dans mcp_risque/score.py, identique pour tous les adaptateurs.

Configuration (fichier .env, jamais committé) :
    DATABRICKS_SERVER_HOSTNAME   ex. dbc-xxxx.cloud.databricks.com
    DATABRICKS_HTTP_PATH         ex. /sql/1.0/warehouses/xxxx
    DATABRICKS_TOKEN             jeton d'accès personnel
    DATABRICKS_SCHEMA            ex. workspace.sentinelle
"""
import os
import re
from collections import defaultdict
from typing import Any, Callable

from .models import Acheteur, Facture
from .ports import AcheteurInconnu

# Un nom de schéma ne peut pas être passé en paramètre SQL : on le valide strictement.
SCHEMA_VALIDE = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*){0,2}$")
COLONNES_ACHETEUR = "siren, denomination, secteur, limite_credit, encours, profil"
COLONNES_FACTURE = "siren, numero, date_emission, date_echeance, montant, date_paiement"


class ConfigurationDatabricks(RuntimeError):
    pass


def connexion_depuis_env() -> Callable[[], Any]:
    """Fabrique de connexions lue dans l'environnement. Erreur claire si une variable manque."""
    noms = ["DATABRICKS_SERVER_HOSTNAME", "DATABRICKS_HTTP_PATH", "DATABRICKS_TOKEN"]
    manquantes = [n for n in noms if not os.environ.get(n)]
    if manquantes:
        raise ConfigurationDatabricks(f"Variables manquantes dans .env : {', '.join(manquantes)}")

    def connecter():
        from databricks import sql      # importé ici : inutile pour les autres adaptateurs
        return sql.connect(
            server_hostname=os.environ["DATABRICKS_SERVER_HOSTNAME"],
            http_path=os.environ["DATABRICKS_HTTP_PATH"],
            access_token=os.environ["DATABRICKS_TOKEN"],
        )
    return connecter


class DatabricksAdapter:
    def __init__(self, connecter: Callable[[], Any], schema: str):
        if not SCHEMA_VALIDE.match(schema):
            raise ConfigurationDatabricks(f"Nom de schéma invalide : {schema!r}")
        self._connecter = connecter
        self._schema = schema

    def _requete(self, sql: str, params: dict | None = None) -> list[dict]:
        with self._connecter() as conn, conn.cursor() as curseur:
            curseur.execute(sql, params or {})          # paramètres nommés : jamais de concaténation
            noms = [d[0] for d in curseur.description]
            return [dict(zip(noms, ligne)) for ligne in curseur.fetchall()]

    def get_acheteur(self, siren: str) -> Acheteur:
        lignes = self._requete(
            f"SELECT {COLONNES_ACHETEUR} FROM {self._schema}.acheteurs WHERE siren = :siren",
            {"siren": siren},
        )
        if not lignes:
            raise AcheteurInconnu(f"Aucun acheteur couvert avec le SIREN {siren}.")
        return Acheteur(**lignes[0])

    def get_factures(self, siren: str) -> list[Facture]:
        lignes = self._requete(
            f"SELECT {COLONNES_FACTURE} FROM {self._schema}.factures WHERE siren = :siren",
            {"siren": siren},
        )
        return [Facture(**l) for l in lignes]

    def lister_acheteurs(self) -> list[Acheteur]:
        return [Acheteur(**l) for l in self._requete(
            f"SELECT {COLONNES_ACHETEUR} FROM {self._schema}.acheteurs")]

    def get_toutes_factures(self) -> dict[str, list[Facture]]:
        groupes: dict[str, list[Facture]] = defaultdict(list)
        for l in self._requete(f"SELECT {COLONNES_FACTURE} FROM {self._schema}.factures"):
            groupes[l["siren"]].append(Facture(**l))
        return dict(groupes)
