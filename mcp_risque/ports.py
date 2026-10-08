"""Port d'accès aux données internes de l'assureur, et ses adaptateurs.

Les outils MCP ne connaissent que RiskDataPort. L'adaptateur est choisi par
configuration : « local » (CSV, pour le développement et les tests) aujourd'hui,
« databricks » ensuite, « snowflake » au jalon 2, sans toucher aux outils.
"""
import csv
from datetime import date
from pathlib import Path
from typing import Protocol

from .models import Acheteur, Facture


class AcheteurInconnu(LookupError):
    pass


class RiskDataPort(Protocol):
    def get_acheteur(self, siren: str) -> Acheteur: ...
    def get_factures(self, siren: str) -> list[Facture]: ...
    def lister_acheteurs(self) -> list[Acheteur]: ...


class MemoryAdapter:
    """Adaptateur en mémoire : alimenté directement par le générateur."""

    def __init__(self, acheteurs: list[Acheteur], factures: list[Facture]):
        self._acheteurs = {a.siren: a for a in acheteurs}
        self._factures: dict[str, list[Facture]] = {}
        for f in factures:
            self._factures.setdefault(f.siren, []).append(f)

    def get_acheteur(self, siren: str) -> Acheteur:
        try:
            return self._acheteurs[siren]
        except KeyError:
            raise AcheteurInconnu(f"Aucun acheteur couvert avec le SIREN {siren}.") from None

    def get_factures(self, siren: str) -> list[Facture]:
        return list(self._factures.get(siren, []))

    def lister_acheteurs(self) -> list[Acheteur]:
        return list(self._acheteurs.values())


class CsvAdapter(MemoryAdapter):
    """Lit acheteurs.csv et factures.csv : les mêmes fichiers que ceux chargés dans Databricks."""

    def __init__(self, dossier: str | Path):
        dossier = Path(dossier)
        with open(dossier / "acheteurs.csv", encoding="utf-8") as f:
            acheteurs = [Acheteur(**ligne) for ligne in csv.DictReader(f)]
        with open(dossier / "factures.csv", encoding="utf-8") as f:
            factures = [
                Facture(**{**ligne, "date_paiement": ligne["date_paiement"] or None})
                for ligne in csv.DictReader(f)
            ]
        super().__init__(acheteurs, factures)


def exporter_csv(acheteurs: list[Acheteur], factures: list[Facture], dossier: str | Path) -> None:
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    for nom, lignes, modele in [("acheteurs", acheteurs, Acheteur), ("factures", factures, Facture)]:
        with open(dossier / f"{nom}.csv", "w", newline="", encoding="utf-8") as f:
            ecrivain = csv.DictWriter(f, fieldnames=list(modele.model_fields))
            ecrivain.writeheader()
            for l in lignes:
                d = l.model_dump()
                ecrivain.writerow({k: ("" if v is None else v.isoformat() if isinstance(v, date) else v)
                                   for k, v in d.items()})
