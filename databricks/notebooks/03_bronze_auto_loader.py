# Databricks notebook source
# MAGIC %md
# MAGIC # 03 — Couche bronze avec Auto Loader
# MAGIC
# MAGIC Même source que le notebook 02 (les fichiers JSON Lines du volume `brut/bodacc`),
# MAGIC mais en **flux incrémental** avec Auto Loader (`cloudFiles`) :
# MAGIC
# MAGIC - le **checkpoint** mémorise les fichiers déjà traités : chaque exécution ne lit que les nouveaux ;
# MAGIC - le **schéma** est déduit une fois, stocké, puis **évolue** si un nouveau champ apparaît ;
# MAGIC - `trigger(availableNow=True)` : traite tout ce qui est en attente, puis s'arrête (mode batch incrémental).
# MAGIC
# MAGIC Checkpoint et schéma vivent dans un volume séparé (`systeme`), **jamais** dans le dossier surveillé.
# MAGIC
# MAGIC Certification : *Data Ingestion and Loading — Auto Loader, évolution de schéma, chargement incrémental.*

# COMMAND ----------

SOURCE = "/Volumes/workspace/sentinelle/brut/bodacc"
SYSTEME = "/Volumes/workspace/sentinelle/systeme"
CHECKPOINT = f"{SYSTEME}/checkpoints/bodacc_bronze"
SCHEMA = f"{SYSTEME}/schemas/bodacc_bronze"
CIBLE = "workspace.sentinelle.bodacc_bronze"

spark.sql("CREATE VOLUME IF NOT EXISTS workspace.sentinelle.systeme")

# COMMAND ----------

from pyspark.sql import functions as F

flux = (
    spark.readStream
    .format("cloudFiles")
    .option("cloudFiles.format", "json")
    .option("cloudFiles.schemaLocation", SCHEMA)          # où le schéma déduit est stocké et versionné
    .option("cloudFiles.schemaEvolutionMode", "addNewColumns")   # le défaut, explicité pour l'examen
    .load(SOURCE)
    .withColumn("_fichier_source", F.col("_metadata.file_path"))
    .withColumn("_ingere_le", F.current_timestamp())
)

def compter(table: str) -> int:
    return spark.table(table).count() if spark.catalog.tableExists(table) else 0

avant = compter(CIBLE)

requete = (
    flux.writeStream
    .option("checkpointLocation", CHECKPOINT)             # mémoire des fichiers traités
    .option("mergeSchema", "true")                        # la table cible accepte les nouvelles colonnes
    .trigger(availableNow=True)
    .toTable(CIBLE)
)
requete.awaitTermination()
apres = compter(CIBLE)
print(f"{apres - avant} lignes ajoutées par ce passage ({apres} au total)")

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Combien de lignes, depuis quels fichiers ?
# MAGIC SELECT _fichier_source, count(*) AS annonces
# MAGIC FROM workspace.sentinelle.bodacc_bronze
# MAGIC GROUP BY _fichier_source
# MAGIC ORDER BY _fichier_source;

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Le schéma déduit par Auto Loader : observe le type des colonnes, et la colonne _rescued_data
# MAGIC DESCRIBE TABLE workspace.sentinelle.bodacc_bronze;

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Lignes dont une partie n'a pas pu entrer dans le schéma (type inattendu, champ mal formé…)
# MAGIC SELECT count(*) AS lignes_avec_donnees_sauvees
# MAGIC FROM workspace.sentinelle.bodacc_bronze
# MAGIC WHERE _rescued_data IS NOT NULL;
