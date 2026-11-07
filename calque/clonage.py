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
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import disques as D
from . import ntfs
from . import table as T
from .peripherique import ErreurAcces, Fenetre, ouvrir

BLOC = 4 * 1024 * 1024
SEUIL_CARTE = 256 * T.MIO       # sous cette taille, une partition est copiée entière


class Annule(Exception):
    """Arrêt demandé ; le clonage peut être repris."""


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
    estimation: int = 0         # octets qui seront copiés (estimation)

    @property
    def possible(self) -> bool:
        return not self.bloquants

    def octets_partitions(self) -> int:
        return sum(t.partition.secteurs for t in self.travaux) * self.table_source.taille_secteur

    def espace_gagne(self) -> int:
        return max(0, self.cible.taille - self.source.taille)

    def duree_estimee(self, verifier: bool = True, debit_max: float | None = None) -> tuple[float, float]:
        """Fourchette (secondes) : la vitesse dépend surtout de la liaison de la cible."""
        lent, rapide = (120e6, 350e6) if self.cible.bus.upper() == "USB" else (300e6, 1500e6)
        if debit_max:
            lent, rapide = min(lent, debit_max), min(rapide, debit_max)
        facteur = 1.6 if verifier else 1.0      # la relecture va plus vite que l'écriture
        return self.estimation * facteur / rapide, self.estimation * facteur / lent

    def signature(self) -> str:
        """Empreinte du plan : une reprise n'est permise que pour le MÊME plan."""
        h = hashlib.sha256()
        for _, donnees in T.zones_table(self.table_cible):
            h.update(donnees)
        h.update(repr([(t.partition.numero, t.partition.debut, t.partition.secteurs, t.nouveau_debut)
                       for t in self.travaux]).encode())
        return h.hexdigest()


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
        estimation = 0
        for p in ts.triees():
            premier = dev.lire(p.debut * ts.taille_secteur, 512)
            t = Travail(p, p.debut, ntfs.nature(premier), False)
            travaux.append(t)
            # estimation de ce qui sera copié, lue sur le disque tel quel (le
            # cliché, pris au moment du clonage, donnera presque la même chose)
            try:
                lecteur = Fenetre(dev, p.debut * ts.taille_secteur, p.secteurs * ts.taille_secteur)
                estimation += sum(n for _, n in _zones(t, lecteur, ts.taille_secteur))
            except Exception:
                estimation += p.secteurs * ts.taille_secteur
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

    # la cible contient-elle déjà quelque chose ? (le dire en clair : c'est effacé)
    try:
        dc = ouvrir(cible.chemin, False, cible.taille_secteur)
        try:
            tcible = T.lire(dc.lire, cible.taille or dc.taille, cible.taille_secteur)
            if tcible.partitions:
                avert.append(("plan.cible_non_vide", {
                    "n": len(tcible.partitions),
                    "taille": D.octets_lisibles(sum(p.secteurs for p in tcible.partitions) * tcible.taille_secteur)}))
        finally:
            dc.fermer()
    except Exception:
        pass
    if D.sur_batterie():
        avert.append(("plan.batterie", {}))
    import sys as _sys
    if _sys.platform == "win32" and source.numero is not None:
        for v in source.volumes:
            if v.nom and v.libre is not None and (v.systeme_fichiers or "").upper() == "NTFS":
                if v.libre < 1_000_000_000:
                    bloquants.append(("plan.place_cliche_bloque", {"nom": v.nom, "libre": D.octets_lisibles(v.libre)}))
                elif v.libre < 5_000_000_000:
                    avert.append(("plan.place_cliche", {"nom": v.nom, "libre": D.octets_lisibles(v.libre)}))
    elif any(t.systeme_fichiers == "ntfs" for t in travaux):
        avert.append(("plan.demarrage_rapide", {}))
    if source.sante and source.sante != "Healthy":
        avert.append(("plan.sante", {"etat": source.sante}))
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
    plan = Plan(source, cible, ts, tc, travaux, bloquants, avert)
    plan.estimation = estimation
    return plan


@dataclass
class Bilan:
    octets_copies: int = 0
    octets_verifies: int = 0
    duree: float = 0.0
    blocs_differents: int = 0
    secteurs_illisibles: int = 0
    reconnexions: int = 0
    repris_a: int = 0           # octets déjà faits avant la reprise


class Progression:
    """Relais de progression, appelable depuis le fil de travail."""

    def __init__(self, rappel=None):
        self.rappel = rappel or (lambda **k: None)
        self.etape, self.fait, self.total, self.t0, self.depart = "", 0, 0, time.monotonic(), 0

    def debut(self, etape: str, total: int, deja: int = 0):
        self.etape, self.fait, self.total, self.t0, self.depart = etape, deja, total, time.monotonic(), deja
        self.rappel(etape=etape, fait=deja, total=total, debit=0.0)

    def avance(self, n: int):
        self.fait += n
        ecoule = max(1e-6, time.monotonic() - self.t0)
        self.rappel(etape=self.etape, fait=self.fait, total=self.total, debit=(self.fait - self.depart) / ecoule)


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


# ------------------------------------------------------------ journal de reprise

def dossier_donnees() -> Path:
    if os.environ.get("CALQUE_DONNEES"):
        return Path(os.environ["CALQUE_DONNEES"])
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Calque"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Calque"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "Calque"
    return base


class Journal:
    """Où en est un clonage, pour le reprendre après une interruption.

    Écrit de façon atomique toutes les quelques centaines de Mo : un arrêt
    brutal fait refaire au plus ces quelques centaines de Mo.
    """
    PERIODE = 64            # blocs de 4 Mio entre deux écritures

    def __init__(self, chemin: Path | None = None):
        self.chemin = Path(chemin) if chemin else dossier_donnees() / "reprise.json"
        self.d: dict = {}

    def charger(self) -> dict | None:
        try:
            self.d = json.loads(self.chemin.read_text(encoding="utf-8"))
            return self.d if self.d.get("version") == 1 else None
        except (OSError, ValueError):
            return None

    def ecrire(self) -> None:
        try:
            self.chemin.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.chemin.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.d), encoding="utf-8")
            os.replace(tmp, self.chemin)
        except OSError:
            pass

    def effacer(self) -> None:
        try:
            self.chemin.unlink()
        except OSError:
            pass


def reprise_possible(plan: Plan, journal: Journal | None = None) -> dict | None:
    """Le journal d'un clonage interrompu correspondant EXACTEMENT à ce plan."""
    j = journal or Journal()
    d = j.charger()
    if not d or d.get("signature") != plan.signature():
        return None
    if not plan.source.correspond(d.get("source", {})) or not plan.cible.correspond(d.get("cible", {})):
        return None
    return d


def abandonner_reprise(journal: Journal | None = None) -> None:
    """Oublie un clonage interrompu et supprime ses clichés."""
    j = journal or Journal()
    d = j.charger() or {}
    D.supprimer_cliches([c[0] for c in (d.get("cliches") or {}).values()])
    j.effacer()


# ------------------------------------------------------------ accès robustes

DELAI_RECONNEXION = 90.0      # secondes d'attente d'un disque qui a décroché
PAS_RECONNEXION = 2.0
DECONNEXIONS = {2, 3, 6, 21, 31, 55, 121, 433, 483, 1117, 1167}       # Windows
DECONNEXIONS_POSIX = {5, 6, 19, 110, 112}                          # EIO, ENXIO, ENODEV…


def _deconnexion(e: ErreurAcces) -> bool:
    if e.code is None:
        return True
    return e.code in (DECONNEXIONS if sys.platform == "win32" else DECONNEXIONS_POSIX)


class Cible:
    """La cible, qui se rebranche toute seule si la liaison USB décroche.

    Un boîtier USB qui chauffe se déconnecte puis réapparaît souvent quelques
    secondes plus tard, parfois sous un autre numéro. On attend, on le
    retrouve à son empreinte (taille, modèle, n° de série), on rouvre, et on
    réécrit le bloc en cours. Au-delà du délai, le clonage s'arrête proprement
    et pourra être repris.
    """

    def __init__(self, disque: D.Disque, journal_cb, annulation, delai: float | None = None):
        self.disque, self.journal_cb, self.annulation = disque, journal_cb, annulation
        self.delai = DELAI_RECONNEXION if delai is None else delai
        self.empreinte = disque.empreinte()
        self.reconnexions = 0
        self.dev = ouvrir(disque.chemin, True, disque.taille_secteur)

    def _rouvrir(self) -> None:
        try:
            self.dev.fermer()
        except Exception:
            pass
        self.journal_cb("cible_attente")
        fin = time.monotonic() + self.delai
        while time.monotonic() < fin:
            if self.annulation.is_set():
                raise Annule()
            time.sleep(PAS_RECONNEXION)
            d = D.retrouver(self.empreinte)
            if d is None:
                continue
            try:
                self.dev = ouvrir(d.chemin, True, d.taille_secteur)
            except ErreurAcces:
                continue
            self.disque = d
            self.reconnexions += 1
            self.journal_cb("cible_revenue")
            return
        raise ErreurClonage("clone.cible_perdue")

    def _faire(self, action):
        for _ in range(4):
            try:
                return action()
            except ErreurAcces as e:
                if not _deconnexion(e):
                    raise ErreurClonage("clone.cible_erreur", detail=e.champs.get("detail", "")) from e
                self._rouvrir()
        raise ErreurClonage("clone.cible_perdue")

    def ecrire(self, position: int, donnees: bytes) -> None:
        self._faire(lambda: self.dev.ecrire(position, donnees))

    def lire(self, position: int, taille: int) -> bytes:
        return self._faire(lambda: self.dev.lire(position, taille))

    def vider(self) -> None:
        self._faire(self.dev.vider)

    def fermer(self) -> None:
        if hasattr(self.dev, "mettre_a_jour"):
            try:
                self.dev.mettre_a_jour()
            except Exception:
                pass
        self.dev.fermer()


def lire_source(lecteur, position: int, taille: int, ss: int, tolerer: bool, illisibles: list) -> bytes:
    """Lit un bloc de la source ; en cas d'erreur, morceau par morceau.

    Les secteurs vraiment illisibles (disque abîmé) sont notés. Sans accord
    (`tolerer`), le clonage s'arrête : le disque est peut-être en train de
    lâcher, et l'utilisateur doit le savoir. Avec accord, ils sont remplacés
    par des zéros.
    """
    try:
        return lecteur.lire(position, taille)
    except ErreurAcces as e:
        # un cliché qui disparaît (Windows l'a supprimé faute de place) n'est
        # pas un disque abîmé : il faut le dire autrement
        if "ShadowCopy" in str(getattr(lecteur, "chemin", "")) and e.code in DECONNEXIONS:
            raise ErreurClonage("clone.cliche_disparu") from e
    morceaux = []
    pas = 64 * 1024 if taille > 64 * 1024 else ss
    for p in range(position, position + taille, pas):
        n = min(pas, position + taille - p)
        try:
            morceaux.append(lecteur.lire(p, n))
            continue
        except ErreurAcces:
            pass
        if n > ss:
            morceaux.append(lire_source(lecteur, p, n, ss, tolerer, illisibles))
            continue
        bon = None
        for _ in range(3):
            try:
                bon = lecteur.lire(p, n)
                break
            except ErreurAcces:
                time.sleep(0.05)
        if bon is None:
            if not tolerer:
                raise ErreurClonage("clone.source_illisible", position=p)
            illisibles.append(p)
            bon = b"\0" * n
        morceaux.append(bon)
    return b"".join(morceaux)


def _empecher_veille(actif: bool) -> None:
    """Windows ne doit pas se mettre en veille pendant la copie (la liaison
    USB serait coupée). Valable pour le fil qui l'appelle."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if actif else 0))
    except Exception:
        pass


# ------------------------------------------------------------ le clonage

def cloner(plan: Plan, rappel=None, annulation: threading.Event | None = None,
           verifier: bool = True, journal=None, reprendre: bool = False, tolerer_illisibles: bool = False,
           debit_max: float | None = None, journal_reprise: Journal | None = None) -> Bilan:
    """Exécute le plan. Lève Annule, ErreurClonage ou ErreurAcces.

    `reprendre` : continue un clonage interrompu (même plan, mêmes disques,
    mêmes clichés) au lieu de recommencer. Toute interruption après le début de
    la copie laisse un journal qui le permet.
    """
    if not plan.possible:
        raise ErreurClonage("plan.impossible")
    annulation = annulation or threading.Event()
    prog = Progression(rappel)
    journal = journal or (lambda cle, **k: None)
    jr = journal_reprise or Journal()
    bilan, t0 = Bilan(), time.monotonic()
    ss = plan.table_source.taille_secteur
    src = plan.source
    precedent = reprise_possible(plan, jr) if reprendre else None
    if reprendre and precedent is None:
        raise ErreurClonage("clone.reprise_impossible")
    if not reprendre:
        abandonner_reprise(jr)          # un vieux journal ne doit jamais être repris par erreur

    def arreter_si_demande():
        if annulation.is_set():
            raise Annule()

    # La cible a-t-elle changé depuis le plan (autre disque branché sous le même numéro) ?
    if plan.cible.bus != "image":
        actuel = D.retrouver(plan.cible.empreinte())
        if actuel is None:
            raise ErreurClonage("clone.cible_changee")
        if actuel.systeme:
            raise ErreurClonage("plan.cible_systeme", disque=actuel.libelle())
        plan.cible = actuel

    _empecher_veille(True)
    journal("preparation")
    if not reprendre:
        D.preparer_cible(plan.cible)
    dev_src = ouvrir(src.chemin, False, ss)
    cib = None
    try:
        cib = Cible(plan.cible, lambda cle, **k: journal(cle, **k), annulation)
        taille_cible = plan.cible.taille or cib.dev.taille
        if not reprendre:
            for position, longueur in T.zones_effacement(taille_cible // ss, ss):
                cib.ecrire(position, b"\0" * longueur)

        parts = [(t.partition.numero, t.partition.debut * ss, t.partition.secteurs * ss) for t in plan.travaux]
        existants = {int(k): tuple(v) for k, v in (precedent or {}).get("cliches", {}).items()}
        with D.lecteurs_figes(src, dev_src, parts, journal, existants) as figes:
            lecteurs = figes.lecteurs
            journal("analyse")
            a_copier = []
            for t in plan.travaux:
                zones = _zones(t, lecteurs[t.partition.numero], ss)
                a_copier.append((t, zones))
                journal("zones", numero=t.partition.numero, fs=t.systeme_fichiers, octets=sum(n for _, n in zones))
            empreinte_zones = hashlib.sha256(repr([z for _, z in a_copier]).encode()).hexdigest()
            blocs = [(t, p, n) for t, zones in a_copier for p, n in _blocs(zones)]
            total = sum(n for _, _, n in blocs)

            # état repris, ou neuf
            if precedent:
                if precedent.get("zones") != empreinte_zones:
                    raise ErreurClonage("clone.reprise_impossible")
                fait_blocs = int(precedent.get("blocs_faits", 0))
                empreintes = [bytes.fromhex(h) for h in precedent.get("empreintes", [])]
                illisibles = list(precedent.get("illisibles", []))
                verifier = bool(precedent.get("verifier", verifier))
            else:
                fait_blocs, empreintes, illisibles = 0, [], []
            deja = sum(n for _, _, n in blocs[:fait_blocs])
            bilan.repris_a = deja
            jr.d = {"version": 1, "signature": plan.signature(), "zones": empreinte_zones,
                    "source": src.empreinte(), "cible": plan.cible.empreinte(),
                    "cliches": {str(k): [c.ident, c.peripherique] for k, c in figes.cliches.items()},
                    "blocs_faits": fait_blocs, "empreintes": [e.hex() for e in empreintes],
                    "illisibles": illisibles, "verifier": verifier, "total": total,
                    "date": time.strftime("%Y-%m-%d %H:%M")}
            jr.ecrire()
            # à partir d'ici, une interruption garde les clichés pour la reprise
            figes.garder = True

            def sauver(i: int) -> None:
                jr.d["blocs_faits"] = i
                jr.d["empreintes"] = [e.hex() for e in empreintes] if verifier else []
                jr.d["illisibles"] = illisibles
                jr.ecrire()

            prog.debut("copie", total, deja)
            debut_debit = time.monotonic()
            octets_session = 0
            i = fait_blocs
            try:
                for i in range(fait_blocs, len(blocs)):
                    arreter_si_demande()
                    t, p, n = blocs[i]
                    donnees = lire_source(lecteurs[t.partition.numero], p, n, ss, tolerer_illisibles, illisibles)
                    cib.ecrire(t.nouveau_debut * ss + p, donnees)
                    if verifier:
                        empreintes.append(_empreinte(donnees))
                    bilan.octets_copies += n
                    octets_session += n
                    prog.avance(n)
                    if debit_max:
                        attente = octets_session / debit_max - (time.monotonic() - debut_debit)
                        if attente > 0:
                            time.sleep(attente)
                    if (i + 1) % Journal.PERIODE == 0:
                        cib.vider()
                        sauver(i + 1)
                i = len(blocs)
                cib.vider()
                sauver(i)
            except BaseException:
                sauver(i)
                raise

            if verifier:
                prog.debut("verification", total)
                for (t, p, n), e in zip(blocs, empreintes):
                    arreter_si_demande()
                    if _empreinte(cib.lire(t.nouveau_debut * ss + p, n)) != e:
                        bilan.blocs_differents += 1
                    bilan.octets_verifies += n
                    prog.avance(n)
                if bilan.blocs_differents:
                    raise ErreurClonage("clone.verification", blocs=bilan.blocs_differents)

            # secteurs d'amorçage des volumes déplacés
            for t in plan.travaux:
                if not t.deplacee:
                    continue
                vue = Fenetre(cib, t.nouveau_debut * ss, t.partition.secteurs * ss)
                for position, secteur in ntfs.retouches_deplacement(
                        vue.lire, t.partition.secteurs * ss, ss, t.nouveau_debut):
                    cib.ecrire(t.nouveau_debut * ss + position, secteur)

            arreter_si_demande()
            journal("table")
            for position, donnees in T.zones_table(plan.table_cible):
                cib.ecrire(position, donnees)
            cib.vider()
            figes.garder = False            # fini : clichés supprimés en sortie
        jr.effacer()
        bilan.secteurs_illisibles = len(illisibles)
    finally:
        if cib is not None:
            bilan.reconnexions = cib.reconnexions
            cib.fermer()
        dev_src.fermer()
        _empecher_veille(False)
    D.rafraichir(plan.cible)
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
