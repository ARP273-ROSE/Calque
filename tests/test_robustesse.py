"""Ce qui arrive en vrai avec un boîtier USB : décrochage, retour, disque source abîmé.

Les pannes sont simulées autour de vrais disques image : la cible « disparaît »
au milieu de la copie (comme un boîtier qui chauffe), revient ou non ; la
source a un secteur illisible.
"""
import errno
import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fabrique  # noqa: E402
from calque import clonage, disques, table  # noqa: E402
from calque.peripherique import ErreurAcces, ouvrir  # noqa: E402

pytestmark = pytest.mark.skipif(not fabrique.outils_presents(), reason="outils de fabrication absents")
MIO = fabrique.MIO


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    d = tmp_path_factory.mktemp("rob")
    temoins = fabrique.fichiers_temoins(n=6)
    disque, parts = fabrique.disque_gpt(d, fichiers=temoins)
    return disque, parts, temoins


@pytest.fixture(autouse=True)
def rapide(monkeypatch, tmp_path):
    monkeypatch.setattr(clonage, "PAS_RECONNEXION", 0.05)
    monkeypatch.setattr(clonage, "DELAI_RECONNEXION", 0.5)
    monkeypatch.setattr(clonage.Journal, "PERIODE", 4)
    monkeypatch.setenv("CALQUE_DONNEES", str(tmp_path / "donnees"))


def _cible(tmp_path, nom="cible.img", mio=2000):
    c = tmp_path / nom
    with open(c, "wb") as f:
        f.truncate(mio * MIO)
    return c


def _plan(src, cible):
    return clonage.preparer_plan(disques.disque_image(str(src)), disques.disque_image(str(cible)))


def _verifier_clone(cible, temoins, tmp_path):
    d = ouvrir(str(cible))
    t = table.lire(d.lire, d.taille, 512)
    d.fermer()
    c = t.triees()[2]
    vol = fabrique.extraire(cible, c.debut, c.secteurs, tmp_path / "vol.img")
    for nom, contenu in temoins.items():
        assert fabrique.lire_fichier_ntfs(vol, nom) == contenu, nom


class Capricieuse:
    """Un périphérique qui « se débranche » après un certain volume écrit."""
    ecrits = 0

    def __init__(self, dev, panne_apres, definitive):
        self.dev, self.panne_apres, self.definitive = dev, panne_apres, definitive
        self.taille = dev.taille

    def _panne(self):
        if Capricieuse.ecrits >= self.panne_apres and (self.definitive or not Capricieuse.deja):
            Capricieuse.deja = True
            raise ErreurAcces("acces.ecriture", code=errno.ENODEV, chemin="cible", detail="No such device")

    def ecrire(self, p, b):
        self._panne()
        self.dev.ecrire(p, b)
        Capricieuse.ecrits += len(b)

    def lire(self, p, n):
        self._panne()
        return self.dev.lire(p, n)

    def vider(self):
        self.dev.vider()

    def fermer(self):
        self.dev.fermer()


def _ouvrir_capricieux(chemin_cible, panne_apres, definitive):
    Capricieuse.ecrits, Capricieuse.deja = 0, False

    def ouvrir_(chemin, ecriture=False, ss=512):
        d = ouvrir(chemin, ecriture, ss)
        return Capricieuse(d, panne_apres, definitive) if chemin == str(chemin_cible) and ecriture else d
    return ouvrir_


def test_decrochage_bref_rattrape_tout_seul(source, tmp_path, monkeypatch):
    src, _, temoins = source
    cible = _cible(tmp_path)
    monkeypatch.setattr(clonage, "ouvrir", _ouvrir_capricieux(cible, 60 * MIO, definitive=False))
    etapes = []
    bilan = clonage.cloner(_plan(src, cible), journal=lambda c, **k: etapes.append(c))
    assert bilan.reconnexions == 1 and "cible_attente" in etapes and "cible_revenue" in etapes
    assert bilan.blocs_differents == 0
    _verifier_clone(cible, temoins, tmp_path)


def test_decrochage_definitif_puis_reprise(source, tmp_path, monkeypatch):
    src, _, temoins = source
    cible = _cible(tmp_path)
    monkeypatch.setattr(clonage, "ouvrir", _ouvrir_capricieux(cible, 80 * MIO, definitive=True))
    monkeypatch.setattr(disques, "retrouver", lambda e: None)          # le boîtier ne revient pas
    with pytest.raises(clonage.ErreurClonage) as e:
        clonage.cloner(_plan(src, cible))
    assert e.value.cle == "clone.cible_perdue"
    plan = _plan(src, cible)
    d = clonage.reprise_possible(plan)
    assert d and d["blocs_faits"] > 0
    # rebranché : on reprend, sans tout recommencer
    monkeypatch.setattr(clonage, "ouvrir", ouvrir)
    monkeypatch.setattr(disques, "retrouver", lambda e: disques.disque_image(e["chemin"]))
    bilan = clonage.cloner(plan, reprendre=True)
    assert bilan.repris_a > 0 and bilan.octets_copies < 196 * MIO
    assert bilan.blocs_differents == 0
    assert clonage.Journal().charger() is None                # journal effacé une fois fini
    _verifier_clone(cible, temoins, tmp_path)


def test_annulation_puis_reprise(source, tmp_path):
    src, _, temoins = source
    cible = _cible(tmp_path)
    import threading
    stop = threading.Event()

    def rappel(**k):
        if k["etape"] == "copie" and k["fait"] > 40 * MIO:
            stop.set()
    with pytest.raises(clonage.Annule):
        clonage.cloner(_plan(src, cible), rappel=rappel, annulation=stop)
    bilan = clonage.cloner(_plan(src, cible), reprendre=True)
    assert bilan.repris_a >= 16 * MIO
    _verifier_clone(cible, temoins, tmp_path)


def test_reprise_refusee_pour_un_autre_plan(source, tmp_path):
    src, _, _ = source
    cible = _cible(tmp_path)
    import threading
    stop = threading.Event()
    with pytest.raises(clonage.Annule):
        clonage.cloner(_plan(src, cible), rappel=lambda **k: k["fait"] > 20 * MIO and stop.set(), annulation=stop)
    autre = clonage.preparer_plan(disques.disque_image(str(src)), disques.disque_image(str(cible)), deplacer_fin=False)
    assert clonage.reprise_possible(autre) is None
    with pytest.raises(clonage.ErreurClonage) as e:
        clonage.cloner(autre, reprendre=True)
    assert e.value.cle == "clone.reprise_impossible"


def test_secteur_illisible_sur_la_source(source, tmp_path, monkeypatch):
    src, parts, temoins = source
    cible = _cible(tmp_path)
    # un secteur abîmé au milieu des données de C:
    plan = _plan(src, cible)
    c_debut = parts[3][0] * 512
    d = ouvrir(str(src))
    from calque import ntfs
    zones = ntfs.zones_occupees(lambda p, n: d.lire(c_debut + p, n), parts[3][1] * 512)
    d.fermer()
    z0, zn = zones[len(zones) // 2]
    mauvais = c_debut + z0 + zn // 2
    mauvais -= mauvais % 512

    class Abimee:
        def __init__(self, dev):
            self.dev, self.taille = dev, dev.taille

        def lire(self, p, n):
            if p <= mauvais < p + n:
                raise ErreurAcces("acces.lecture", code=errno.EIO, chemin="source", detail="I/O error")
            return self.dev.lire(p, n)

        def fermer(self):
            self.dev.fermer()

    def ouvrir_(chemin, ecriture=False, ss=512):
        dv = ouvrir(chemin, ecriture, ss)
        return Abimee(dv) if chemin == str(src) else dv
    monkeypatch.setattr(clonage, "ouvrir", ouvrir_)
    with pytest.raises(clonage.ErreurClonage) as e:
        clonage.cloner(plan)
    assert e.value.cle == "clone.source_illisible"
    bilan = clonage.cloner(plan, reprendre=True, tolerer_illisibles=True)
    assert bilan.secteurs_illisibles == 1
    with open(cible, "rb") as f:
        f.seek(mauvais)                       # C: n'a pas bougé : même position
        assert f.read(512) == b"\0" * 512
        f.seek(mauvais + 512)
        with open(src, "rb") as g:
            g.seek(mauvais + 512)
            assert f.read(4096) == g.read(4096)


def test_copie_bridee(source, tmp_path):
    src, _, _ = source
    cible = _cible(tmp_path)
    t0 = time.monotonic()
    bilan = clonage.cloner(_plan(src, cible), verifier=False, debit_max=150e6)
    assert time.monotonic() - t0 >= bilan.octets_copies / 150e6 * 0.9


def test_estimation_du_plan(source, tmp_path):
    src, _, _ = source
    plan = _plan(src, _cible(tmp_path))
    bilan = clonage.cloner(plan, verifier=False)
    assert plan.estimation == bilan.octets_copies
    bas, haut = plan.duree_estimee()
    assert 0 < bas < haut
