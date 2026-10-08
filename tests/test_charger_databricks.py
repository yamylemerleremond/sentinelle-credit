from scripts.charger_databricks import ddl, insert_par_lot


def test_ddl_types():
    sql = ddl("workspace.sentinelle", "factures", remplacer=False)
    assert sql.startswith("CREATE TABLE IF NOT EXISTS workspace.sentinelle.factures")
    assert "siren STRING" in sql and "date_paiement DATE" in sql and "montant DOUBLE" in sql


def test_insert_parametre_sans_valeur_dans_le_sql():
    lignes = [
        {"siren": "123456789", "numero": "F1", "date_emission": "2026-01-01",
         "date_echeance": "2026-01-31", "montant": "1000.5", "date_paiement": ""},
        {"siren": "987654321", "numero": "F2", "date_emission": "2026-02-01",
         "date_echeance": "2026-03-03", "montant": "20", "date_paiement": "2026-03-05"},
    ]
    sql, params = insert_par_lot("workspace.sentinelle", "factures", lignes)
    assert "123456789" not in sql and "1000.5" not in sql
    assert sql.count("CAST(:") == 12
    assert params["siren_0"] == "123456789"
    assert params["date_paiement_0"] is None          # vide -> NULL
    assert params["date_paiement_1"] == "2026-03-05"
