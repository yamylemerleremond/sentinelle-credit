# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Ingestion REST des annonces BODACC (zone d'atterrissage)
# MAGIC
# MAGIC Télécharge les annonces **brutes**, sans transformation, en **JSON Lines** (une annonce
# MAGIC par ligne) dans le volume `workspace.sentinelle.brut`, **un fichier par jour publié**.
# MAGIC
# MAGIC **Choix de la méthode** : l'API de recherche (`/records`) est paginée et plafonnée à
# MAGIC 10 000 résultats par requête ; un seul jour de dépôts de comptes peut dépasser 15 000
# MAGIC annonces. On utilise donc l'**API d'export** (`/exports/jsonl`) : pas de plafond, et le
# MAGIC format JSON Lines est livré directement.
# MAGIC
# MAGIC **Écriture atomique** : le fichier est d'abord écrit sous un nom commençant par `_`
# MAGIC (ignoré par Spark, COPY INTO et Auto Loader), puis renommé une fois complet. Un
# MAGIC téléchargement interrompu ne laisse jamais de fichier partiel visible.
# MAGIC
# MAGIC Certification : *Data Ingestion and Loading — ingestion REST, choix de la méthode d'ingestion.*

# COMMAND ----------

dbutils.widgets.text("date_debut", "", "Date de parution début (AAAA-MM-JJ, vide = hier)")
dbutils.widgets.text("date_fin", "", "Date de parution fin (AAAA-MM-JJ, vide = hier)")

# COMMAND ----------

import os
import time
from datetime import date, datetime, timedelta, timezone

import requests

EXPORT = ("https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/"
          "annonces-commerciales/exports/jsonl")
DOSSIER = "/Volumes/workspace/sentinelle/brut/bodacc"
# Familles utiles au risque crédit (même liste que le pack risque_credit.yaml)
FAMILLES = ["collective", "radiation", "conciliation", "retablissement_professionnel",
            "vente", "dpc", "modification", "creation", "immatriculation"]

hier = (date.today() - timedelta(days=1)).isoformat()
date_debut = date.fromisoformat(dbutils.widgets.get("date_debut") or hier)
date_fin = date.fromisoformat(dbutils.widgets.get("date_fin") or hier)  # refuse une date mal formée
if date_fin < date_debut:
    raise ValueError("date_fin doit être postérieure ou égale à date_debut")
jours = [date_debut + timedelta(days=i) for i in range((date_fin - date_debut).days + 1)]
print(f"{len(jours)} jour(s) à ingérer : {jours[0]} → {jours[-1]}")

# COMMAND ----------

def telecharger_jour(jour: date, chemin_tmp: str, essais: int = 3) -> int:
    """Télécharge en flux l'export JSON Lines d'un jour dans chemin_tmp.
    Renvoie le nombre d'annonces (lignes). Reprise à attente croissante sur erreur temporaire."""
    familles = " or ".join(f'familleavis="{f}"' for f in FAMILLES)
    params = {"where": f"dateparution = date'{jour.isoformat()}' and ({familles})"}
    attente = 1.0
    for essai in range(1, essais + 1):
        try:
            with requests.get(EXPORT, params=params, stream=True, timeout=(10, 300)) as r:
                if r.status_code in (429, 500, 502, 503, 504):
                    raise requests.ConnectionError(f"statut {r.status_code}")
                r.raise_for_status()                 # 400/404 : inutile de réessayer
                lignes = 0
                with open(chemin_tmp, "wb") as f:
                    for ligne in r.iter_lines():
                        if ligne.strip():
                            f.write(ligne + b"\n")
                            lignes += 1
                return lignes
        except (requests.Timeout, requests.ConnectionError) as erreur:
            if os.path.exists(chemin_tmp):
                os.remove(chemin_tmp)
            if essai == essais:
                raise RuntimeError(f"{jour} : export BODACC indisponible ({erreur})") from erreur
            time.sleep(attente)
            attente *= 2

# COMMAND ----------

dbutils.fs.mkdirs(DOSSIER)
horodatage = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
ecrits = 0

for jour in jours:
    nom = f"bodacc_{jour.isoformat()}_{horodatage}.jsonl"
    chemin_tmp = f"{DOSSIER}/_en_cours_{nom}"        # préfixe _ : invisible pour Spark
    chemin = f"{DOSSIER}/{nom}"
    n = telecharger_jour(jour, chemin_tmp)
    if n == 0:
        os.remove(chemin_tmp)
        print(f"{jour} : aucune parution, aucun fichier écrit")   # ex. le lundi
        continue
    os.rename(chemin_tmp, chemin)                     # publication atomique du fichier complet
    ecrits += 1
    print(f"{jour} : {n} annonces → {chemin}")

print(f"{ecrits} fichier(s) écrit(s)")
display(dbutils.fs.ls(DOSSIER))
