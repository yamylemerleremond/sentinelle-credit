"""Score de dégradation du comportement de paiement d'un acheteur.

Même idée que le score d'anomalie d'asset-health : on compare l'acheteur à
lui-même. Référence = médiane de ses retards mensuels passés, dispersion = MAD
(écart absolu médian), robuste aux mois atypiques. Un payeur habituellement
lent n'est pas alerté ; un bon payeur qui dérive, si.
"""
from collections import defaultdict
from datetime import date
from statistics import mean, median

from .models import Facture

MOIS_RECENTS = 3
MOIS_REFERENCE = 12
MOIS_REFERENCE_MIN = 6        # en dessous : données insuffisantes
SIGMA_MIN = 2.0               # jours ; évite d'alerter un payeur parfaitement régulier pour 1 jour
Z_PLEIN = 6.0                 # z à partir duquel le score vaut 1
RETARD_DEFAUT = 60            # jours : impayé échu au-delà = défaut de paiement
SEUILS = [(0.33, "normal"), (0.66, "vigilance"), (1.01, "alerte")]


def _cle_mois(d: date) -> tuple[int, int]:
    return (d.year, d.month)


def _mois_precedents(date_ref: date, n: int) -> list[tuple[int, int]]:
    annee, mois = date_ref.year, date_ref.month
    resultat = []
    for _ in range(n):
        resultat.append((annee, mois))
        mois -= 1
        if mois == 0:
            annee, mois = annee - 1, 12
    return list(reversed(resultat))


def retards_mensuels(factures: list[Facture], date_ref: date) -> dict[tuple[int, int], float]:
    """Retard moyen pondéré par le montant, par mois d'échéance. Un impayé échu
    compte avec son retard courant (date_ref - échéance) : il pèse de plus en plus."""
    sommes, poids = defaultdict(float), defaultdict(float)
    for f in factures:
        if f.date_echeance > date_ref:
            continue
        fin = f.date_paiement or date_ref
        retard = max(0, (fin - f.date_echeance).days)
        cle = _cle_mois(f.date_echeance)
        sommes[cle] += retard * f.montant
        poids[cle] += f.montant
    return {cle: sommes[cle] / poids[cle] for cle in sommes}


def tendance(factures: list[Facture], mensuels: dict, mois: list[tuple[int, int]], date_ref: date) -> list[dict]:
    """Retard par mois, en signalant les mois qui contiennent des impayés : leur valeur
    est un MINIMUM (l'impayé continue de vieillir), jamais le signe d'une amélioration."""
    impayes_par_mois = defaultdict(float)
    for f in factures:
        if f.date_paiement is None and f.date_echeance <= date_ref:
            impayes_par_mois[_cle_mois(f.date_echeance)] += f.montant
    return [
        {
            "mois": f"{a}-{m:02d}",
            "retard_jours": round(mensuels[(a, m)], 1),
            "impayes_en_cours": round(impayes_par_mois[(a, m)], 2),
            "valeur_minimale": impayes_par_mois[(a, m)] > 0,
        }
        for a, m in mois if (a, m) in mensuels
    ]


def score_acheteur(factures: list[Facture], date_ref: date) -> dict:
    mensuels = retards_mensuels(factures, date_ref)
    calendrier = _mois_precedents(date_ref, MOIS_RECENTS + MOIS_REFERENCE)
    reference = [mensuels[m] for m in calendrier[:MOIS_REFERENCE] if m in mensuels]
    recents = [mensuels[m] for m in calendrier[MOIS_REFERENCE:] if m in mensuels]

    impayes = [f for f in factures if f.date_paiement is None and f.date_echeance <= date_ref]
    montant_impaye = round(sum(f.montant for f in impayes), 2)
    retard_max_impaye = max(((date_ref - f.date_echeance).days for f in impayes), default=0)
    defaut = retard_max_impaye > RETARD_DEFAUT

    base = {
        "impayes_echus": montant_impaye,
        "retard_max_impaye_jours": retard_max_impaye,
        "defaut_paiement": defaut,
        "tendance_6_mois": tendance(factures, mensuels, calendrier[-6:], date_ref),
    }

    if len(reference) < MOIS_REFERENCE_MIN or not recents:
        return {**base, "donnees_suffisantes": False, "score": None,
                "niveau": "defaut" if defaut else "inconnu",
                "explication": f"{len(reference)} mois d'historique de référence, {MOIS_REFERENCE_MIN} requis."}

    med = median(reference)
    mad = median(abs(x - med) for x in reference)
    sigma = max(1.4826 * mad, SIGMA_MIN)
    recent = mean(recents)
    z = (recent - med) / sigma
    score = min(1.0, max(0.0, z / Z_PLEIN))
    if defaut:
        score = 1.0
    # Un défaut de paiement est un fait, pas une tendance : il a son propre niveau.
    niveau = "defaut" if defaut else next(nom for seuil, nom in SEUILS if score < seuil)

    return {
        **base,
        "donnees_suffisantes": True,
        "score": round(score, 3),
        "niveau": niveau,
        "retard_reference_jours": round(med, 1),
        "retard_recent_jours": round(recent, 1),
        "ecarts_types_robustes": round(z, 2),
        "explication": (
            f"Retard moyen récent {recent:.0f} j contre {med:.0f} j habituellement "
            f"({z:+.1f} écarts robustes)."
            + (f" Impayé échu depuis {retard_max_impaye} j." if defaut else "")
        ),
    }
