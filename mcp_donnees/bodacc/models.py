"""Modèle normalisé d'un signal BODACC.

Les agents ne voient jamais le JSON brut du BODACC, seulement ce modèle.
Si la source change, seul le parseur bouge.
"""
from datetime import date

from pydantic import BaseModel, Field


class Jugement(BaseModel):
    famille: str | None = None
    nature: str | None = None
    date_jugement: date | None = None
    complement: str | None = None
    niveau_gravite: int = Field(ge=1, le=5)
    source_gravite: str = "nature"       # nature | complement | defaut : pour l'explication


class CompanySignal(BaseModel):
    signal_id: str                       # id BODACC, clé d'idempotence
    siren: str = Field(pattern=r"^\d{9}$")
    date_parution: date
    famille: str                         # code BODACC : collective, dpc...
    famille_lib: str | None = None
    poids: str                           # issu du pack : critique, eleve...
    type_avis: str | None = None         # annonce, rectificatif, annulation
    denomination: str | None = None
    forme_juridique: str | None = None
    tribunal: str | None = None
    date_cloture: date | None = None     # issu de depot
    comptes_confidentiels: bool = False  # issu de depot.descriptif
    jugement: Jugement | None = None
    jugement_manquant: bool = False      # collective sans jugement : incohérence de la source
    source_url: str | None = None
