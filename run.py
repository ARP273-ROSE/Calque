#!/usr/bin/env python3
"""Lanceur de Calque — cloner un disque sur un disque plus grand.

    python run.py                          ouvre la fenêtre (droits d'administrateur demandés)
    python run.py --lister                 liste les disques
    python run.py --cloner SOURCE CIBLE    sans fenêtre (numéro de disque Windows,
                                           /dev/sdX sous Linux, ou fichier image)

Branchement du kit Windows, comme MusicOthèque et Anticythere3D : rapports
d'incident (plantage Python, crash natif, gel), accord au premier lancement,
verrou nommé lu par l'installeur, vérification silencieuse des mises à jour.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or ".")

NOM = "Calque"
_fichier_faulthandler = None


def _dossier_donnees() -> Path:
    """Données hors du dossier d'installation : elles survivent aux mises à jour.

    Windows : %LOCALAPPDATA%\\Calque ; macOS : ~/Library/Application Support/Calque ;
    Linux : $XDG_STATE_HOME/Calque (~/.local/state/Calque). Depuis les sources :
    le dossier du dépôt.
    """
    ici = Path(__file__).resolve().parent
    python = ici.parent / "python"
    installe = (python / "python.exe").exists() or (python / "bin" / "python3").exists()
    if not installe:
        base = ici
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / NOM
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / NOM
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / NOM
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        base = Path.home()
    # Versions ≤ 1.1.2 sous macOS et Linux : réglages des rapports écrits dans
    # app/. On les reprend une fois, pour ne pas reposer la question d'accord.
    if installe and base != ici:
        for nom in ("reglages_rapports.json",):
            ancien, neuf = ici / nom, base / nom
            if ancien.exists() and not neuf.exists():
                try:
                    neuf.write_bytes(ancien.read_bytes())
                except OSError:
                    pass
    return base


def _demarrer_rapports() -> None:
    dossier = _dossier_donnees()
    trace_native = dossier / "_crash_natif.log"
    # La trace de la session précédente est relevée AVANT de rouvrir le
    # fichier : l'ouverture en écriture le vide.
    try:
        import reporting
        from calque import __version__
        reporting.init(dossier, application="calque", version=__version__)
        reporting.relever_crash_natif(trace_native)
        reporting.reprendre_file_en_fond()
    except Exception:
        pass
    try:
        import faulthandler
        global _fichier_faulthandler
        _fichier_faulthandler = open(trace_native, "w", encoding="utf-8")
        faulthandler.enable(file=_fichier_faulthandler, all_threads=True)
    except Exception:
        pass


def _demander_accord(win) -> None:
    try:
        import reporting
        from PyQt6 import QtWidgets
        premier = reporting.consentement() is None
        if premier:
            boite = QtWidgets.QMessageBox(win)
            boite.setWindowTitle(NOM)
            boite.setIcon(QtWidgets.QMessageBox.Icon.Question)
            from calque.i18n import tr
            boite.setText(tr("accord.titre"))
            boite.setInformativeText(tr("accord.texte"))
            oui = boite.addButton(tr("dlg.oui"), QtWidgets.QMessageBox.ButtonRole.AcceptRole)
            boite.addButton(tr("dlg.non"), QtWidgets.QMessageBox.ButtonRole.RejectRole)
            boite.exec()
            reporting.definir_consentement(boite.clickedButton() is oui)
            win.act_autoreport.setChecked(reporting.consentement() is True)
        reporting.signaler_demarrage(premier=premier)
    except Exception:
        pass


def _rapport_crash(exc: BaseException) -> None:
    """Une application fenêtrée n'a pas de console : sans ce filet, une erreur
    au démarrage fermerait le programme sans rien montrer."""
    import datetime
    import traceback
    texte = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    entete = f"{NOM} — erreur au démarrage — {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n"
    chemin = _dossier_donnees() / "calque-erreur.log"
    try:
        with open(chemin, "a", encoding="utf-8") as fh:
            fh.write(entete + texte + "\n")
    except OSError:
        chemin = "(journal impossible à écrire)"
    sys.stderr.write(entete + texte)
    try:
        import reporting
        reporting.signaler_plantage(texte)
    except Exception:
        pass
    try:
        from PyQt6 import QtWidgets
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        from calque.i18n import tr
        QtWidgets.QMessageBox.critical(
            None, NOM, tr("demarrage.echec", erreur=f"{type(exc).__name__}: {exc}", chemin=chemin))
    except Exception:
        pass


def _trouver(nom: str):
    from calque import disques as D
    if os.path.isfile(nom):
        return D.disque_image(nom)
    for d in D.lister():
        if nom == d.chemin or (d.numero is not None and nom == str(d.numero)):
            return d
    return None


def _lister() -> int:
    from calque import disques as D
    from calque.i18n import tr
    for d in D.lister():
        print(f"{d.chemin:24} {d.libelle()} · {d.taille_secteur} {'o' if tr('cli.mot') == 'OUI' else 'B'}" + (f" · {tr('disque.systeme')}" if d.systeme else ""))
    return 0


def _ligne_de_commande(args) -> int:
    from calque import clonage
    from calque import disques as D
    from calque.i18n import message, tr
    source, cible = (_trouver(n) for n in args.cloner)
    for nom, d in zip(args.cloner, (source, cible)):
        if d is None:
            print(tr("cli.introuvable", nom=nom), file=sys.stderr)
            return 2
    try:
        bl = D.bitlocker_windows() if sys.platform == "win32" and source.numero is not None else set()
        plan = clonage.preparer_plan(source, cible, not args.garder_place, bl)
    except Exception as e:  # noqa: BLE001
        print(message(e), file=sys.stderr)
        return 1
    ss = plan.table_source.taille_secteur
    print(tr("cli.plan"), f"{source.libelle()}  ->  {cible.libelle()}  ({plan.table_source.style.upper()})")
    for t in plan.travaux:
        p = t.partition
        print(f"  {p.numero}  {p.nature:13} {t.systeme_fichiers:9} {D.octets_lisibles(p.secteurs * ss):>9}  "
              f"{p.debut} -> {t.nouveau_debut}")
    for cle, champs in plan.avertissements:
        print("  ! " + tr(cle, **champs))
    if plan.bloquants:
        for cle, champs in plan.bloquants:
            print("  X " + tr(cle, **champs), file=sys.stderr)
        return 1
    if not args.oui:
        if input(tr("cli.confirmer", cible=cible.libelle())).strip().upper() != tr("cli.mot"):
            print(tr("cli.abandon"))
            return 1
    dernier = [0.0]

    def rappel(**k):
        import time
        if time.monotonic() - dernier[0] > 1 or k["fait"] >= k["total"]:
            dernier[0] = time.monotonic()
            print(f"\r  {tr('etape.' + k['etape'])} {D.octets_lisibles(k['fait'])} / {D.octets_lisibles(k['total'])}"
                  f"  {D.octets_lisibles(int(k['debit']))}/s   ", end="", flush=True)

    try:
        bilan = clonage.cloner(plan, rappel=rappel, verifier=not args.sans_verification,
                               journal=lambda cle, **k: print("\n" + tr("etape." + cle, **{
                                   c: (D.octets_lisibles(v) if c == "octets" else v) for c, v in k.items()})))
    except clonage.Annule:
        print("\n" + tr("fin.annule"))
        return 1
    except Exception as e:  # noqa: BLE001
        print("\n" + tr("fin.echec", detail=message(e)), file=sys.stderr)
        return 1
    print(f"\n{D.octets_lisibles(bilan.octets_copies)} · {bilan.duree:.0f} s · OK")
    return 0


def _elever_si_besoin() -> bool:
    """Windows : relance le programme en administrateur (UAC). Rend True si
    une nouvelle instance a été lancée et que celle-ci doit s'arrêter."""
    if sys.platform != "win32":
        return False
    from calque import disques as D
    if D.est_administrateur() or os.environ.get("CALQUE_SANS_ELEVATION"):
        return False
    import ctypes
    import subprocess
    params = subprocess.list2cmdline([os.path.abspath(sys.argv[0]), *sys.argv[1:]])
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    return r > 32


def _verifier() -> int:
    """--check : l'application et ses dépendances se chargent (lancé par la
    construction des paquets avec l'interpréteur embarqué ; aucune fenêtre)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PyQt6 import QtWidgets
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
        import interface_kit  # noqa: F401
        import reporting  # noqa: F401
        import updater  # noqa: F401
        from calque import clonage, disques, fenetre, ntfs, style, table  # noqa: F401
        style.appliquer(app)
        del app
    except Exception as exc:
        print(f"Calque : ECHEC / FAILED -- {type(exc).__name__}: {exc}")
        return 1
    print("Calque : OK")
    return 0


def main() -> int:
    if "--check" in sys.argv[1:]:
        return _verifier()
    from calque.i18n import definir_langue, tr
    ap = argparse.ArgumentParser(description=tr("cli.description"))
    ap.add_argument("--lister", "--list", action="store_true", help="list the disks / lister les disques")
    ap.add_argument("--cloner", "--clone", nargs=2, metavar=("SOURCE", "TARGET"),
                    help="clone without a window / cloner sans fenêtre")
    ap.add_argument("--oui", "--yes", action="store_true", help="no confirmation / sans confirmation")
    ap.add_argument("--sans-verification", "--no-verify", action="store_true",
                    help="do not read the target back / sans relecture")
    ap.add_argument("--garder-place", "--keep-layout", action="store_true",
                    help="do not move the trailing partitions / ne pas déplacer les partitions de fin")
    ap.add_argument("--image", action="append", default=[], metavar="FILE",
                    help="add a disk image to the window's lists / ajouter une image disque")
    ap.add_argument("--lang", choices=["fr", "en"], help="interface language / langue")
    from calque import __version__
    ap.add_argument("--version", action="version", version=f"Calque {__version__}")
    args = ap.parse_args()
    definir_langue(args.lang)

    if args.lister:
        return _lister()
    if args.cloner:
        return _ligne_de_commande(args)
    if _elever_si_besoin():
        return 0

    _demarrer_rapports()
    from PyQt6 import QtCore, QtGui, QtWidgets
    from calque.fenetre import FenetrePrincipale

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(NOM)
    # Langue : choix du menu Langue s'il existe, sinon détection automatique.
    if not args.lang:
        choix = QtCore.QSettings("ARP273-ROSE", NOM).value("langue", "auto", type=str)
        definir_langue(choix if choix in ("fr", "en") else None)
    from calque import style
    style.appliquer(app)            # apparence figée, indépendante du thème Windows
    # Linux : la boîte « native » passe par le portail XDG et se réduit souvent
    # à une liste ; on impose la boîte COMPLÈTE de Qt (barre latérale avec
    # dossier personnel, Documents, Téléchargements, supports montés ;
    # arborescence, création de dossier), au style de l'application (kit
    # commun, interface_kit). Windows et macOS gardent leur boîte native.
    try:
        import interface_kit
        interface_kit.installer_dialogues_fichiers()
    except Exception:
        pass
    # Verrou nommé lu par l'installeur Inno (AppMutex = <nom_fichier>EnCours).
    if sys.platform == "win32":
        try:
            import ctypes
            app._mutex_installeur = ctypes.windll.kernel32.CreateMutexW(None, False, f"{NOM}EnCours")
        except Exception:
            pass
    icone = Path(__file__).resolve().parent / "logo.png"
    if icone.exists():
        app.setWindowIcon(QtGui.QIcon(str(icone)))

    win = FenetrePrincipale(images=args.image)
    win.show()
    from calque import disques as D
    if not D.est_administrateur() and not args.image:
        QtCore.QTimer.singleShot(400, lambda: QtWidgets.QMessageBox.warning(
            win, NOM, tr("admin.requis") if sys.platform == "win32" else tr("admin.linux")))

    QtCore.QTimer.singleShot(1200, lambda: _demander_accord(win))
    try:
        import updater
        if updater.is_packaged():
            QtCore.QTimer.singleShot(3000, lambda: win._check_update(manual=False))
    except Exception:
        pass
    try:
        import reporting
        vigie = reporting.Vigie(seuil=10.0, periode=2.0)
        vigie.demarrer()
        minuteur = QtCore.QTimer(win)
        minuteur.timeout.connect(vigie.battre)
        minuteur.start(2000)
        win._vigie, win._vigie_timer = vigie, minuteur
    except Exception:
        pass
    return app.exec()


if __name__ == "__main__":
    # Sans effet sauf si un jour des processus fils réimportent ce fichier :
    # réimportent ce fichier ; sans cette garde, chacun rouvrirait une fenêtre.
    import multiprocessing
    multiprocessing.freeze_support()
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as _exc:          # noqa: BLE001 — filet volontaire
        _rapport_crash(_exc)
        sys.exit(1)
