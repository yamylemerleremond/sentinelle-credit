"""Générateur déterministe d'un portefeuille d'acheteurs fictifs.

Les SIREN générés échouent volontairement à la clé de Luhn : un vrai SIREN la
respecte toujours, donc aucun acheteur fictif ne peut coïncider avec une vraie
entreprise. On n'attache jamais un faux historique de paiement à une société réelle.
"""
import random
from datetime import date, timedelta

from .models import Acheteur, Facture

DATE_REF = date(2026, 9, 30)
NB_MOIS = 24
SECTEURS = ["BTP", "Distribution", "Transport", "Agroalimentaire", "Industrie", "Restauration"]
PROFILS = {"sain": 35, "erratique": 6, "degradation": 6, "defaut": 3}   # 50 acheteurs


def luhn_valide(nombre: str) -> bool:
    total = 0
    for i, chiffre in enumerate(reversed(nombre)):
        n = int(chiffre)
        if i % 2 == 1:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def siren_fictif(rng: random.Random) -> str:
    while True:
        candidat = str(rng.randint(100_000_000, 999_999_999))
        if not luhn_valide(candidat):
            return candidat


def _retard(profil: str, mois_avant_fin: int, rng: random.Random) -> int | None:
    """Jours de retard pour une échéance. None = impayé à la date de référence."""
    if profil == "sain":
        return max(0, round(rng.gauss(3, 3)))
    if profil == "erratique":                       # bruyant mais stable : pas une dégradation
        return max(0, round(rng.gauss(12, 9)))
    if profil == "degradation":                     # dérive sur les 6 derniers mois
        derive = max(0, 6 - mois_avant_fin) * 8
        return max(0, round(rng.gauss(4 + derive, 4)))
    if profil == "defaut":                          # dérive puis plus rien n'est payé
        if mois_avant_fin < 3:
            return None
        derive = max(0, 8 - mois_avant_fin) * 6
        return max(0, round(rng.gauss(5 + derive, 4)))
    raise ValueError(profil)


def generer_portefeuille(seed: int = 42, date_ref: date = DATE_REF) -> tuple[list[Acheteur], list[Facture]]:
    rng = random.Random(seed)
    profils = [p for p, n in PROFILS.items() for _ in range(n)]
    rng.shuffle(profils)

    acheteurs, factures = [], []
    for i, profil in enumerate(profils, start=1):
        siren = siren_fictif(rng)
        montant_moyen = rng.choice([8_000, 15_000, 25_000, 40_000])
        limite = montant_moyen * rng.choice([3, 4, 5])
        encours = 0.0

        # -1 = facture du mois en cours, pas encore échue : elle compte dans l'encours
        for mois_avant_fin in range(NB_MOIS - 1, -2, -1):
            emission = date_ref - timedelta(days=30 * mois_avant_fin + 45)
            echeance = emission + timedelta(days=30)
            montant = round(montant_moyen * rng.uniform(0.7, 1.3), 2)
            retard = _retard(profil, mois_avant_fin, rng)
            paiement = echeance + timedelta(days=retard) if retard is not None else None
            if paiement is not None and paiement > date_ref:
                paiement = None                     # pas encore payée à la date de référence
            if paiement is None:
                encours += montant
            factures.append(Facture(
                siren=siren, numero=f"F{i:03d}-{NB_MOIS - mois_avant_fin:02d}",
                date_emission=emission, date_echeance=echeance,
                montant=montant, date_paiement=paiement,
            ))

        acheteurs.append(Acheteur(
            siren=siren, denomination=f"Acheteur fictif {i:03d}",
            secteur=rng.choice(SECTEURS), limite_credit=float(limite),
            encours=round(encours, 2), profil=profil,
        ))
    return acheteurs, factures
