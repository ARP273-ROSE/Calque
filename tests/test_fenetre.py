"""La fenêtre, hors écran, sur deux disques image : plan, garde-fous, clonage."""
import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fabrique  # noqa: E402

QtWidgets = pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    from calque import i18n, style
    i18n.definir_langue("fr")
    a = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    style.appliquer(a)
    return a


def _attendre(app, condition, delai=60):
    fin = time.monotonic() + delai
    while not condition() and time.monotonic() < fin:
        app.processEvents()
        time.sleep(0.02)
    assert condition()


def test_ouverture_sans_disque(app, monkeypatch):
    from calque import disques
    from calque.fenetre import FenetrePrincipale
    monkeypatch.setattr(disques, "lister", lambda: [])
    w = FenetrePrincipale()
    w.show()
    _attendre(app, lambda: w.bouton_actualiser.isEnabled())
    assert not w.bouton.isEnabled()
    w.grab()
    w.close()


@pytest.mark.skipif(not fabrique.outils_presents(), reason="outils de fabrication absents")
def test_plan_puis_clonage(app, tmp_path, monkeypatch):
    from calque import disques
    from calque.fenetre import FenetrePrincipale
    monkeypatch.setattr(disques, "lister", lambda: [])
    src, _ = fabrique.disque_gpt(tmp_path, fichiers=fabrique.fichiers_temoins(n=2))
    cible = tmp_path / "cible.img"
    with open(cible, "wb") as f:
        f.truncate(2000 * fabrique.MIO)
    w = FenetrePrincipale(images=[str(src), str(cible)])
    w.show()
    _attendre(app, lambda: w.choix_cible.count() == 2)
    w.choix_source.setCurrentIndex(0)
    w.choix_cible.setCurrentIndex(1)
    assert w.plan is not None and w.plan.possible
    assert not w.bouton.isEnabled()                 # pas sans la case d'effacement
    w.confirmation.setChecked(True)
    assert w.bouton.isEnabled()
    w.barres.grab()
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *a, **k: None)
    w._lancer(w.plan, True)
    _attendre(app, lambda: not w.en_cours, 120)
    assert w.barre.value() == 1000
    assert w.etat.text() == "Terminé."
    w.close()
