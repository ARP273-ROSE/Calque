"""Fabrique les captures du manuel, sans écran : QT_QPA_PLATFORM=offscreen python docs/captures.py

Les disques montrés sont FICTIFS : des fichiers creux de 500 Go et 1 To
(quelques Mo réellement écrits), avec une table GPT façon Windows et les
signatures de volume — de quoi faire calculer à Calque un vrai plan.
Il faut sgdisk (gdisk).
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI.parent))

from PyQt6 import QtCore, QtWidgets  # noqa: E402

from calque import disques as D  # noqa: E402
from calque import style  # noqa: E402
from calque.i18n import definir_langue  # noqa: E402

GO = 10**9


def attendre(app, condition, delai=20):
    fin = time.time() + delai
    while time.time() < fin and not condition():
        app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 50)
        time.sleep(0.01)


def disque_fictif(chemin: Path, taille: int, windows: bool) -> list[D.Volume]:
    with open(chemin, "wb") as f:
        f.truncate(taille)
    if not windows:
        return []
    subprocess.run(["sgdisk", "-o", "-n", "1:2048:+100M", "-t", "1:ef00", "-c", "1:EFI system partition",
                    "-n", "2:0:+16M", "-t", "2:0c01", "-c", "2:Microsoft reserved partition",
                    "-n", "3:0:-750M", "-t", "3:0700", "-c", "3:Basic data partition",
                    "-n", "4:0:0", "-t", "4:2700", "-c", "4:Basic data partition", str(chemin)],
                   check=True, capture_output=True)
    sortie = subprocess.run(["sgdisk", "-p", str(chemin)], capture_output=True, text=True).stdout
    debuts = {}
    for ligne in sortie.splitlines():
        c = ligne.split()
        if c and c[0].isdigit():
            debuts[int(c[0])] = (int(c[1]), int(c[2]) - int(c[1]) + 1)
    with open(chemin, "r+b") as f:
        for n, sig in ((1, None), (3, b"NTFS    "), (4, b"NTFS    ")):
            f.seek(debuts[n][0] * 512)
            s = bytearray(512)
            if sig:
                s[3:11] = sig
            else:
                s[82:90] = b"FAT32   "
            s[510:512] = b"\x55\xaa"
            f.write(s)
    return [D.Volume(debuts[3][0] * 512, debuts[3][1] * 512, "C:", "", "NTFS")]


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    style.appliquer(app)
    from calque import fenetre
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        os.environ["CALQUE_DONNEES"] = str(tmp / "donnees")
        src, cib, cib4k = tmp / "source.img", tmp / "cible.img", tmp / "cible4k.img"
        volumes = disque_fictif(src, 500_107_862_016, True)
        disque_fictif(cib, 1_000_204_886_016, False)
        disque_fictif(cib4k, 1_000_204_886_016, False)
        for lg in ("fr", "en"):
            definir_langue(lg)
            dock = "Boîtier USB" if lg == "fr" else "USB enclosure"
            liste = [
                D.Disque(str(src), 0, "SSD NVMe 500 Go" if lg == "fr" else "NVMe SSD 500 GB", 500_107_862_016,
                         bus="NVMe", systeme=True, volumes=volumes),
                D.Disque(str(cib), 2, f"{dock} — SSD 1 To" if lg == "fr" else f"{dock} — SSD 1 TB",
                         1_000_204_886_016, bus="USB"),
            ]
            D.lister = lambda liste=liste: list(liste)
            w = fenetre.FenetrePrincipale()
            w.resize(960, 900)
            w.show()
            attendre(app, lambda: w.choix_cible.count() > 0)
            attendre(app, lambda: w.plan is not None)
            # disque fictif sans vrai NTFS : on montre l'estimation d'un C: rempli à 148 Go
            w.plan.estimation = 148 * GO
            # captures de la partie Windows : l'alerte propre à Linux n'y a pas sa place
            w.plan.avertissements = [a for a in w.plan.avertissements if a[0] != "plan.demarrage_rapide"]
            w._majeur_texte_plan()
            app.processEvents()
            w.grab().save(str(ICI / f"capture_plan-{lg}.png"))
            # clonage interrompu (boîtier décroché) : bandeau « Reprendre »
            from calque import clonage
            j = clonage.Journal()
            j.d = {"version": 1, "signature": w.plan.signature(), "source": w.plan.source.empreinte(),
                   "cible": w.plan.cible.empreinte(), "blocs_faits": int(0.41 * 148 * GO / clonage.BLOC),
                   "total": 148 * GO, "date": "2026-11-08 21:14"}
            j.ecrire()
            w._majeur_bandeau()
            app.processEvents()
            w.grab().save(str(ICI / f"capture_reprise-{lg}.png"))
            j.effacer()
            w._majeur_bandeau()
            w.confirmation.setChecked(True)
            # en cours : on montre la progression telle que l'affiche le clonage
            w.en_cours = True
            w.bouton.setText(fenetre.tr("bouton.annuler"))
            for x in (w.choix_source, w.choix_cible, w.option_deplacer, w.option_verifier, w.confirmation):
                x.setEnabled(False)
            w._afficher_progres({"etape": "copie", "fait": 61 * GO, "total": 148 * GO, "debit": 392e6})
            app.processEvents()
            w.grab().save(str(ICI / f"capture_copie-{lg}.png"))
            w.en_cours = False
            w.bouton.setText(fenetre.tr("bouton.cloner"))
            # cible présentée en secteurs de 4096 octets par un boîtier : refus expliqué
            liste[1] = D.Disque(str(cib4k), 3, liste[1].modele, 1_000_204_886_016, 4096, 4096, bus="USB")
            w.charger_disques(liste)
            app.processEvents()
            w.grab().save(str(ICI / f"capture_4k-{lg}.png"))
            w.onglets.setCurrentIndex(1)
            w.etat_c.setText(fenetre.tr("apres.etat", taille=D.octets_lisibles(499_000_000_000),
                                        maximum=D.octets_lisibles(999_100_000_000)))
            w.bouton_agrandir.setEnabled(True)
            w.bouton_winre.setEnabled(True)
            app.processEvents()
            w.grab().save(str(ICI / f"capture_apres-{lg}.png"))
            w.close()
    print("captures écrites dans", ICI)


if __name__ == "__main__":
    main()
