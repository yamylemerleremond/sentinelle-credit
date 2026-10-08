"""Données internes simulées de l'assureur : acheteurs couverts et factures."""
from datetime import date

from pydantic import BaseModel, Field


class Acheteur(BaseModel):
    siren: str = Field(pattern=r"^\d{9}$")
    denomination: str
    secteur: str
    limite_credit: float          # montant garanti accordé sur cet acheteur (€)
    encours: float                # factures émises non encore payées (€)
    profil: str                   # vérité terrain du générateur, utile aux évaluations


class Facture(BaseModel):
    siren: str
    numero: str
    date_emission: date
    date_echeance: date
    montant: float
    date_paiement: date | None = None   # None = pas encore payée
