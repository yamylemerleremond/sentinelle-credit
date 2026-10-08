"""Tests de contrat : la même suite tourne contre chaque adaptateur du RiskDataPort.
La bascule d'un entrepôt à l'autre est prouvée, pas affirmée."""
import re
from collections import defaultdict

import pytest

from mcp_risque.adapters_databricks import (
    ConfigurationDatabricks, DatabricksAdapter, connexion_depuis_env,
)
from mcp_risque.donnees_synthetiques import DATE_REF, generer_portefeuille
from mcp_risque.ports import AcheteurInconnu, CsvAdapter, MemoryAdapter, exporter_csv
from mcp_risque.score import score_acheteur

ACHETEURS, FACTURES = generer_portefeuille()


class FausseConnexionDatabricks:
    """Imite databricks.sql : connexion et curseur gestionnaires de contexte,
    paramètres nommés, description et fetchall. Note chaque requête reçue."""

    def __init__(self, journal: list):
        self.journal = journal
        self.tables = {
            "acheteurs": [a.model_dump() for a in ACHETEURS],
            "factures": [f.model_dump() for f in FACTURES],
        }

    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def cursor(self): return self

    def execute(self, sql: str, params: dict):
        self.journal.append((sql, params))
        table = re.search(r"FROM \S+\.(\w+)", sql).group(1)
        colonnes = [c.strip() for c in re.search(r"SELECT (.+?) FROM", sql).group(1).split(",")]
        lignes = self.tables[table]
        if "WHERE siren = :siren" in sql:
            lignes = [l for l in lignes if l["siren"] == params["siren"]]
        self.description = [(c,) for c in colonnes]
        self._resultat = [tuple(l[c] for c in colonnes) for l in lignes]

    def fetchall(self): return self._resultat


@pytest.fixture
def journal():
    return []


@pytest.fixture(params=["memoire", "csv", "databricks"])
def port(request, tmp_path, journal):
    if request.param == "memoire":
        return MemoryAdapter(ACHETEURS, FACTURES)
    if request.param == "csv":
        exporter_csv(ACHETEURS, FACTURES, tmp_path)
        return CsvAdapter(tmp_path)
    return DatabricksAdapter(lambda: FausseConnexionDatabricks(journal), "workspace.sentinelle")


# --- le contrat ------------------------------------------------------------------

def test_lister_acheteurs(port):
    assert sorted(a.siren for a in port.lister_acheteurs()) == sorted(a.siren for a in ACHETEURS)


def test_get_acheteur(port):
    assert port.get_acheteur(ACHETEURS[0].siren) == ACHETEURS[0]


def test_acheteur_inconnu(port):
    with pytest.raises(AcheteurInconnu):
        port.get_acheteur("752461681")


def test_factures_identiques(port):
    siren = ACHETEURS[0].siren
    attendu = sorted((f for f in FACTURES if f.siren == siren), key=lambda f: f.numero)
    assert sorted(port.get_factures(siren), key=lambda f: f.numero) == attendu


def test_toutes_factures_coherentes(port):
    toutes = port.get_toutes_factures()
    assert sum(len(v) for v in toutes.values()) == len(FACTURES)
    siren = ACHETEURS[1].siren
    assert sorted(toutes[siren], key=lambda f: f.numero) == \
        sorted(port.get_factures(siren), key=lambda f: f.numero)


def test_meme_score_quel_que_soit_l_adaptateur(port):
    """Le test qui compte : changer d'entrepôt ne change aucune décision."""
    reference = defaultdict(list)
    for f in FACTURES:
        reference[f.siren].append(f)
    for a in ACHETEURS:
        assert score_acheteur(port.get_factures(a.siren), DATE_REF) == \
            score_acheteur(reference[a.siren], DATE_REF)


# --- propre à Databricks ------------------------------------------------------------

def test_siren_jamais_concatene_dans_le_sql(journal):
    port = DatabricksAdapter(lambda: FausseConnexionDatabricks(journal), "workspace.sentinelle")
    port.get_factures(ACHETEURS[0].siren)
    sql, params = journal[-1]
    assert ACHETEURS[0].siren not in sql
    assert params == {"siren": ACHETEURS[0].siren}


@pytest.mark.parametrize("schema", ["workspace.sentinelle; DROP TABLE x", "a b", "1abc", "a.b.c.d"])
def test_schema_invalide_refuse(schema):
    with pytest.raises(ConfigurationDatabricks):
        DatabricksAdapter(lambda: None, schema)


def test_variables_manquantes_message_clair(monkeypatch):
    for n in ["DATABRICKS_SERVER_HOSTNAME", "DATABRICKS_HTTP_PATH", "DATABRICKS_TOKEN"]:
        monkeypatch.delenv(n, raising=False)
    with pytest.raises(ConfigurationDatabricks, match="DATABRICKS_TOKEN"):
        connexion_depuis_env()
