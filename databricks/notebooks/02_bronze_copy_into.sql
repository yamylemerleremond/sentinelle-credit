-- Databricks notebook source
-- MAGIC %md
-- MAGIC # 02 — Couche bronze avec COPY INTO
-- MAGIC
-- MAGIC Charge les fichiers JSON Lines déposés par le notebook 01 dans une table Delta.
-- MAGIC COPY INTO est **idempotent** : il mémorise les fichiers déjà chargés et ne les recharge pas.
-- MAGIC
-- MAGIC Certification : *COPY INTO, chargement incrémental en batch.*

-- COMMAND ----------

-- Table sans schéma : COPY INTO le déduit des fichiers (inferSchema) et le fait évoluer (mergeSchema).
CREATE TABLE IF NOT EXISTS workspace.sentinelle.bodacc_bronze_copy;

-- COMMAND ----------

COPY INTO workspace.sentinelle.bodacc_bronze_copy
FROM (
  SELECT *,
         _metadata.file_path         AS _fichier_source,
         current_timestamp()         AS _ingere_le
  FROM '/Volumes/workspace/sentinelle/brut/bodacc/'
)
FILEFORMAT = JSON
FORMAT_OPTIONS ('inferSchema' = 'true')
COPY_OPTIONS ('mergeSchema' = 'true');

-- COMMAND ----------

-- Vérifications
SELECT _fichier_source, count(*) AS annonces
FROM workspace.sentinelle.bodacc_bronze_copy
GROUP BY _fichier_source;

-- COMMAND ----------

SELECT familleavis, count(*) AS annonces
FROM workspace.sentinelle.bodacc_bronze_copy
GROUP BY familleavis
ORDER BY annonces DESC;
