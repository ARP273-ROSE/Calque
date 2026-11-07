"""Le clonage : plan, contrôles, copie, vérification, table.

Ordre des écritures sur la cible, choisi pour qu'une interruption (câble USB
arraché, annulation, panne) ne laisse jamais un disque trompeur :

1. effacement du début et de la fin de la cible (anciennes tables) ;
2. copie des partitions, bloc par bloc, chaque bloc empreinté ;
3. relecture de la cible et comparaison des empreintes ;
4. retouche des secteurs d'amorçage des volumes déplacés ;
5. table de partitions, EN DERNIER.

Tant que l'étape 5 n'est pas faite, la cible apparaît vide : rien ne peut
démarrer dessus par erreur, ni être pris pour un clone complet.
"""
from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field

from . import disques as D
from . import ntfs
from . import table as T
from .peripherique import ErreurAcces, Fenetre, ouvrir

BLOC = 4 * 1024 * 1024
SEUIL_CARTE = 256 * T.MIO       # sous cette taille, une partition est copiée entière


class Annule(Exception):
    pass


class ErreurClonage(Exception):
    def __init__(self, cle: str, **champs):
        super().__init__(f"{cle} {champs}")
        self.cle, self.champs = cle, champs


@dataclass
class Travail:
    partition: T.Partition
    nouveau_debut: int          # secteur
    systeme_fichiers: str       # ntfs, fat32, bitlocker…
    deplacee: bool


@dataclass
class Plan:
    source: D.Disque
    cible: D.Disque
    table_source: T.Table
    table_cible: T.Table
    travaux: list[Travail]
    bloquants: list[tuple[str, dict]] = field(default_factory=list)
    avertissements: list[tuple[str, dict]] = field(default_factory=list)

    @property
    def possible(self) -> bool:
        return not self.bloquants

    def octets_partitions(self) -> int:
        return sum(t.partition.secteurs for t in self.travaux) * self.table_source.taille_secteur

    def espace_gagne(self) -> int:
        return max(0, self.cible.taille - self.source.taille)


def preparer_plan(source: D.Disque, cible: D.Disque, deplacer_fin: bool = True,
                  bitlocker: set[str] | None = None) -> Plan:
    """Lit la source et calcule ce que deviendra la cible. N'écrit rien."""
    bloquants: list[tuple[str, dict]] = []
    avert: list[tuple[str, dict]] = []
    if source.identite() == cible.identite() or source.chemin == cible.chemin:
        raise ErreurClonage("plan.meme_disque")
    if cible.systeme:
        raise ErreurClonage("plan.cible_systeme", disque=cible.libelle())
    dev = ouvrir(source.chemin, False, source.taille_secteur)
    try:
        taille_src = source.taille or dev.taille
        try:
            ts = T.lire(dev.lire, taille_src, source.taille_secteur)
        except T.ErreurTable as e:
            raise ErreurClonage(e.cle, **e.champs) from e
        travaux = []
        for p in ts.triees():
            premier = dev.lire(p.debut * ts.taille_secteur, 512)
            travaux.append(Travail(p, p.debut, ntfs.nature(premier), False))
    finally:
        dev.fermer()

    if cible.taille_secteur != source.taille_secteur:
        bloquants.append(("plan.secteurs", {"source": source.taille_secteur, "cible": cible.taille_secteur}))
        tc, nouveaux = ts, {}
    else:
        try:
            tc, nouveaux = T.transposer(ts, cible.taille // cible.taille_secteur, deplacer_fin)
        except T.ErreurTable as e:
            bloquants.append((e.cle, {"besoin": D.octets_lisibles(e.champs.get("besoin", 0)),
                                      "cible": D.octets_lisibles(cible.taille)}))
            tc, nouveaux = ts, {}
    for t in travaux:
        if nouveaux:
            t.nouveau_debut = nouveaux[t.partition.numero]
            t.deplacee = t.nouveau_debut != t.partition.debut

    if cible.lecture_seule:
        avert.append(("plan.cible_lecture_seule", {}))
    lettres_chiffrees = (bitlocker or set()) & {v.nom for v in source.volumes if v.nom}
    if any(t.systeme_fichiers == "bitlocker" for t in travaux) or lettres_chiffrees:
        bloquants.append(("plan.bitlocker", {}))
    if cible.volumes:
        avert.append(("plan.cible_occupee", {"volumes": ", ".join(v.nom or v.chemin for v in cible.volumes)}))
    if cible.bus.upper() == "USB" and source.systeme:
        avert.append(("plan.cible_usb", {}))
    if ts.style == "mbr" and cible.taille > 2 * 1024**4:
        avert.append(("plan.mbr_2to", {}))
    import sys
    if source.numero is None or not sys.platform == "win32":
        # pas de cliché hors Windows : un volume monté en écriture changerait pendant la copie
        if source.chemin.startswith("/dev/"):
            montes = D.montages_ecriture_linux(source.chemin)
            if montes:
                bloquants.append(("plan.source_montee", {"points": ", ".join(montes)}))
        if cible.chemin.startswith("/dev/") and D.montages_ecriture_linux(cible.chemin):
            bloquants.append(("plan.cible_montee", {}))
    else:
        for v in source.volumes:
            if v.systeme_fichiers and v.systeme_fichiers.upper() not in ("NTFS", "REFS"):
                avert.append(("plan.volume_sans_cliche", {"nom": v.nom or v.chemin, "fs": v.systeme_fichiers}))
    return Plan(source, cible, ts, tc, travaux, bloquants, avert)


@dataclass
class Bilan:
    octets_copies: int = 0
    octets_verifies: int = 0
    duree: float = 0.0
    blocs_differents: int = 0


class Progression:
    """Relais de progression, appelable depuis le fil de travail."""

    def __init__(self, rappel=None):
        self.rappel = rappel or (lambda **k: None)
        self.etape, self.fait, self.total, self.t0 = "", 0, 0, time.monotonic()

    def debut(self, etape: str, total: int, **champs):
        self.etape, self.fait, self.total, self.t0 = etape, 0, total, time.monotonic()
        self.rappel(etape=etape, fait=0, total=total, debit=0.0, **champs)

    def avance(self, n: int):
        self.fait += n
        ecoule = max(1e-6, time.monotonic() - self.t0)
        self.rappel(etape=self.etape, fait=self.fait, total=self.total, debit=self.fait / ecoule)


def _zones(t: Travail, lecteur, ss: int) -> list[tuple[int, int]]:
    taille = t.partition.secteurs * ss
    if t.systeme_fichiers == "ntfs" and taille >= SEUIL_CARTE:
        try:
            return ntfs.zones_occupees(lecteur.lire, taille)
        except ntfs.ErreurNTFS:
            pass
    return [(0, taille)]


def _blocs(zones):
    for debut, longueur in zones:
        p = debut
        while p < debut + longueur:
            n = min(BLOC, debut + longueur - p)
            yield p, n
            p += n


def _empreinte(b: bytes) -> bytes:
    return hashlib.blake2b(b, digest_size=16).digest()


def cloner(plan: Plan, rappel=None, annulation: threading.Event | None = None,
           verifier: bool = True, journal=None) -> Bilan:
    """Exécute le plan. Lève Annule, ErreurClonage ou ErreurAcces."""
    if not plan.possible:
        raise ErreurClonage("plan.impossible")
    annulation = annulation or threading.Event()
    prog = Progression(rappel)
    journal = journal or (lambda cle, **k: None)
    bilan, t0 = Bilan(), time.monotonic()
    ss = plan.table_source.taille_secteur
    src, cib = plan.source, plan.cible

    def arreter_si_demande():
        if annulation.is_set():
            raise Annule()

    # La cible a-t-elle changé depuis le plan (autre disque branché sous le même numéro) ?
    if cib.bus != "image":
        actuels = {d.chemin: d for d in D.lister()}
        actuel = actuels.get(cib.chemin)
        if actuel is None or actuel.identite() != cib.identite():
            raise ErreurClonage("clone.cible_changee")
        if actuel.systeme:
            raise ErreurClonage("plan.cible_systeme", disque=actuel.libelle())

    journal("preparation")
    D.preparer_cible(cib)
    dev_src = ouvrir(src.chemin, False, ss)
    dev_cib = ouvrir(cib.chemin, True, cib.taille_secteur)
    empreintes: list[tuple[int, int, bytes]] = []      # (position cible, taille, empreinte)
    try:
        taille_cible = cib.taille or dev_cib.taille
        for position, longueur in T.zones_effacement(taille_cible // ss, ss):
            dev_cib.ecrire(position, b"\0" * longueur)

        parts = [(t.partition.numero, t.partition.debut * ss, t.partition.secteurs * ss) for t in plan.travaux]
        with D.lecteurs_figes(src, dev_src, parts, journal) as lecteurs:
            # carte des zones occupées, lue dans les clichés
            journal("analyse")
            a_copier = []
            for t in plan.travaux:
                lecteur = lecteurs[t.partition.numero]
                zones = _zones(t, lecteur, ss)
                a_copier.append((t, lecteur, zones))
                journal("zones", numero=t.partition.numero, fs=t.systeme_fichiers,
                        octets=sum(n for _, n in zones))
            total = sum(n for _, _, z in a_copier for _, n in z)
            prog.debut("copie", total)
            for t, lecteur, zones in a_copier:
                base = t.nouveau_debut * ss
                for p, n in _blocs(zones):
                    arreter_si_demande()
                    donnees = lecteur.lire(p, n)
                    dev_cib.ecrire(base + p, donnees)
                    if verifier:
                        empreintes.append((base + p, n, _empreinte(donnees)))
                    bilan.octets_copies += n
                    prog.avance(n)
            dev_cib.vider()

            if verifier:
                prog.debut("verification", sum(n for _, n, _ in empreintes))
                for position, n, e in empreintes:
                    arreter_si_demande()
                    if _empreinte(dev_cib.lire(position, n)) != e:
                        bilan.blocs_differents += 1
                    bilan.octets_verifies += n
                    prog.avance(n)
                if bilan.blocs_differents:
                    raise ErreurClonage("clone.verification", blocs=bilan.blocs_differents)

            # secteurs d'amorçage des volumes déplacés
            for t in plan.travaux:
                if not t.deplacee:
                    continue
                vue = Fenetre(dev_cib, t.nouveau_debut * ss, t.partition.secteurs * ss)
                for position, secteur in ntfs.retouches_deplacement(
                        vue.lire, t.partition.secteurs * ss, ss, t.nouveau_debut):
                    dev_cib.ecrire(t.nouveau_debut * ss + position, secteur)

        arreter_si_demande()
        journal("table")
        for position, donnees in T.zones_table(plan.table_cible):
            dev_cib.ecrire(position, donnees)
        dev_cib.vider()
        if hasattr(dev_cib, "mettre_a_jour"):
            dev_cib.mettre_a_jour()
    finally:
        dev_cib.fermer()
        dev_src.fermer()
    D.rafraichir(cib)
    bilan.duree = time.monotonic() - t0
    journal("fini")
    return bilan


# ------------------------------------------------------------ après le clonage (Windows)

SCRIPT_ETAT_C = r"""
$p = Get-Partition -DriveLetter C
$s = Get-PartitionSupportedSize -DriveLetter C
@{taille=$p.Size; maximum=$s.SizeMax; disque=$p.DiskNumber} | ConvertTo-Json -Compress
"""


def etat_c() -> dict:
    import json
    return json.loads(D.powershell(SCRIPT_ETAT_C))


def agrandir_c() -> dict:
    """Étend C: à tout l'espace libre qui le suit (après démarrage sur le clone)."""
    D.powershell(r"""
$s = Get-PartitionSupportedSize -DriveLetter C
$p = Get-Partition -DriveLetter C
if ($s.SizeMax -gt $p.Size + 1MB) { Resize-Partition -DriveLetter C -Size $s.SizeMax }
""", delai=600)
    return etat_c()


def reparer_winre() -> str:
    """Réenregistre l'environnement de récupération (partition déplacée)."""
    import subprocess
    sorties = []
    for args in (["reagentc", "/disable"], ["reagentc", "/enable"], ["reagentc", "/info"]):
        r = subprocess.run(args, capture_output=True, timeout=300,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        sorties.append(r.stdout.decode("cp850", "replace") + r.stderr.decode("cp850", "replace"))
    return "\n".join(sorties).strip()
