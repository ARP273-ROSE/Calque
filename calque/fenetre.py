"""Fenêtre principale de Calque."""
from __future__ import annotations

import sys
import threading
from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from . import __version__, clonage
from . import disques as D
from . import style
from .i18n import duree, langue, message, tr

# alertes mises en avant (fond orangé) ; les autres sont « à savoir »
IMPORTANTS = {"plan.ntfs_sale", "plan.cible_non_vide", "plan.cible_occupee", "plan.batterie", "plan.place_cliche", "plan.sante",
              "plan.demarrage_rapide", "plan.volume_sans_cliche"}

COULEURS = {"efi": "#C07A1E", "msr": "#9AA7B1", "donnees": "#1D4E73", "recuperation": "#5E8C61",
            "linux": "#7B5EA7", "fat32": "#C07A1E", "autre": "#6B7884"}


class Barres(QtWidgets.QWidget):
    """Schéma « aujourd'hui / après » : une barre par disque, à la même échelle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.plan: clonage.Plan | None = None
        self.setMinimumHeight(118)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)

    def montrer(self, plan):
        self.plan = plan
        self.update()

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        if not self.plan:
            return
        pl = self.plan
        ss = pl.table_source.taille_secteur
        marge_g = 90
        largeur = self.width() - marge_g - 8
        echelle = max(pl.source.taille, pl.cible.taille) or 1
        fm = p.fontMetrics()
        lignes = ((tr("barre.source"), pl.source, pl.table_source, {t.partition.numero: t.partition.debut for t in pl.travaux}),
                  (tr("barre.cible"), pl.cible, pl.table_cible, {t.partition.numero: t.nouveau_debut for t in pl.travaux}))
        if not pl.possible:
            lignes = lignes[:1]
        for rang, (titre, disque, _table, debuts) in enumerate(lignes):
            y = 8 + rang * 56
            h = 34
            p.setPen(QtGui.QColor(style.ENCRE))
            p.drawText(QtCore.QRectF(0, y, marge_g - 8, h), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, titre)
            w_disque = largeur * disque.taille / echelle
            cadre = QtCore.QRectF(marge_g, y, w_disque, h)
            p.setPen(QtGui.QPen(QtGui.QColor(style.BORD), 1))
            p.setBrush(QtGui.QBrush(QtGui.QColor("#FFFFFF"), Qt.BrushStyle.SolidPattern))
            p.drawRoundedRect(cadre, 4, 4)
            # hachures du libre
            p.setBrush(QtGui.QBrush(QtGui.QColor("#D5DEE5"), Qt.BrushStyle.BDiagPattern))
            p.drawRoundedRect(cadre, 4, 4)
            for t in pl.travaux:
                part = t.partition
                x = marge_g + largeur * debuts[part.numero] * ss / echelle
                w = max(3.0, largeur * part.secteurs * ss / echelle)
                r = QtCore.QRectF(x, y + 1, w, h - 2)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QtGui.QColor(COULEURS.get(part.nature, COULEURS["autre"])))
                p.drawRect(r)
                nom = next((v.nom for v in pl.source.volumes if v.debut == part.debut * ss and v.nom), "")
                texte = nom or tr(f"nature.{part.nature}")
                texte = f"{texte} {D.octets_lisibles(part.secteurs * ss)}"
                if fm.horizontalAdvance(texte) + 8 < w:
                    p.setPen(QtGui.QColor("#FFFFFF"))
                    p.drawText(r, Qt.AlignmentFlag.AlignCenter, texte)
            # espace gagné après la principale
            if rang == 1 and pl.possible and pl.cible.taille > pl.source.taille:
                principale = next((t for t in pl.travaux if t.partition.numero ==
                                   getattr(clonage.T.partition_principale(pl.table_source), "numero", -1)), None)
                if principale:
                    x0 = marge_g + largeur * (principale.nouveau_debut + principale.partition.secteurs) * ss / echelle
                    suivants = [t.nouveau_debut for t in pl.travaux if t.nouveau_debut > principale.nouveau_debut]
                    x1 = marge_g + largeur * (min(suivants) * ss if suivants else disque.taille) / echelle
                    libre = tr("barre.libre")
                    if x1 - x0 > fm.horizontalAdvance(libre) + 8:
                        p.setPen(QtGui.QColor(style.BLEU))
                        p.drawText(QtCore.QRectF(x0, y, x1 - x0, h), Qt.AlignmentFlag.AlignCenter, libre)


class FenetrePrincipale(QtWidgets.QMainWindow):
    _inventaire_pret = QtCore.pyqtSignal(object, object)
    _progres = QtCore.pyqtSignal(dict)
    _journal = QtCore.pyqtSignal(str, dict)
    _fin = QtCore.pyqtSignal(object, object)
    _maj_signal = QtCore.pyqtSignal(object, bool)

    def __init__(self, images: list[str] | None = None):
        super().__init__()
        self.setWindowTitle(f"Calque {__version__}")
        self.resize(960, 880)
        self.reglages = QtCore.QSettings("ARP273-ROSE", "Calque")
        self.images = images or []
        self.disques: list[D.Disque] = []
        self.plan: clonage.Plan | None = None
        self._annulation = threading.Event()
        self.en_cours = False
        self._construire()
        self._construire_menus()
        self._inventaire_pret.connect(self._recevoir_inventaire)
        self._progres.connect(self._afficher_progres)
        self._journal.connect(self._afficher_journal)
        self._fin.connect(self._clonage_fini)
        QtCore.QTimer.singleShot(0, self.actualiser)

    # ------------------------------------------------------------ construction
    def _construire(self):
        central = QtWidgets.QWidget()
        lo = QtWidgets.QVBoxLayout(central)
        lo.setContentsMargins(18, 12, 18, 10)
        titre = QtWidgets.QLabel("Calque")
        titre.setObjectName("titre")
        sous = QtWidgets.QLabel(tr("app.sous_titre"))
        sous.setObjectName("sous_titre")
        lo.addWidget(titre)
        lo.addWidget(sous)
        self.onglets = QtWidgets.QTabWidget()
        lo.addWidget(self.onglets, 1)
        self.onglets.addTab(self._onglet_cloner(), tr("onglet.cloner"))
        self.onglets.addTab(self._onglet_apres(), tr("onglet.apres"))
        self.setCentralWidget(central)

    def _onglet_cloner(self):
        w = QtWidgets.QWidget()
        lo = QtWidgets.QVBoxLayout(w)
        g1 = QtWidgets.QGroupBox(tr("zone.disques"))
        f = QtWidgets.QGridLayout(g1)
        self.choix_source = QtWidgets.QComboBox()
        self.choix_cible = QtWidgets.QComboBox()
        for c in (self.choix_source, self.choix_cible):
            c.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            c.currentIndexChanged.connect(self._recalculer)
        f.addWidget(QtWidgets.QLabel(tr("champ.source")), 0, 0)
        f.addWidget(self.choix_source, 0, 1)
        f.addWidget(QtWidgets.QLabel(tr("champ.cible")), 1, 0)
        f.addWidget(self.choix_cible, 1, 1)
        self.bouton_actualiser = QtWidgets.QPushButton(tr("bouton.actualiser"))
        self.bouton_actualiser.setToolTip(tr("astuce.actualiser"))
        self.bouton_actualiser.clicked.connect(self.actualiser)
        f.addWidget(self.bouton_actualiser, 0, 2, 2, 1)
        f.setColumnStretch(1, 1)
        lo.addWidget(g1)

        # bandeau : clonage interrompu à reprendre
        self.bandeau = QtWidgets.QFrame()
        self.bandeau.setObjectName("bandeau")
        lb = QtWidgets.QHBoxLayout(self.bandeau)
        self.texte_bandeau = QtWidgets.QLabel()
        self.texte_bandeau.setWordWrap(True)
        lb.addWidget(self.texte_bandeau, 1)
        self.bouton_reprendre = QtWidgets.QPushButton(tr("reprise.reprendre"))
        self.bouton_reprendre.setObjectName("principal")
        self.bouton_reprendre.clicked.connect(self._reprendre)
        self.bouton_oublier = QtWidgets.QPushButton(tr("reprise.abandonner"))
        self.bouton_oublier.clicked.connect(self._oublier_reprise)
        lb.addWidget(self.bouton_reprendre)
        lb.addWidget(self.bouton_oublier)
        self.bandeau.hide()
        lo.addWidget(self.bandeau)

        g2 = QtWidgets.QGroupBox(tr("zone.plan"))
        l2 = QtWidgets.QVBoxLayout(g2)
        self.barres = Barres()
        l2.addWidget(self.barres)
        self.texte_plan = QtWidgets.QLabel()
        self.texte_plan.setWordWrap(True)
        self.texte_plan.setTextFormat(Qt.TextFormat.RichText)
        self.texte_plan.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        defil = QtWidgets.QScrollArea()
        defil.setWidgetResizable(True)
        defil.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        defil.setWidget(self.texte_plan)
        defil.setMinimumHeight(130)
        l2.addWidget(defil, 1)
        lo.addWidget(g2, 1)

        g3 = QtWidgets.QGroupBox(tr("zone.lancer"))
        l3 = QtWidgets.QVBoxLayout(g3)
        self.option_deplacer = QtWidgets.QCheckBox(tr("option.deplacer"))
        self.option_deplacer.setChecked(True)
        self.option_deplacer.toggled.connect(self._recalculer)
        self.option_verifier = QtWidgets.QCheckBox(tr("option.verifier"))
        self.option_verifier.setChecked(True)
        self.option_verifier.toggled.connect(self._majeur_texte_plan)
        self.option_doux = QtWidgets.QCheckBox(tr("option.doux"))
        self.option_doux.toggled.connect(self._majeur_texte_plan)
        self.confirmation = QtWidgets.QCheckBox()
        self.confirmation.toggled.connect(self._majeur_bouton)
        for x in (self.option_deplacer, self.option_verifier, self.option_doux, self.confirmation):
            l3.addWidget(x)
        ligne = QtWidgets.QHBoxLayout()
        self.barre = QtWidgets.QProgressBar()
        self.barre.setRange(0, 1000)
        self.barre.setTextVisible(False)
        ligne.addWidget(self.barre, 1)
        self.bouton = QtWidgets.QPushButton(tr("bouton.cloner"))
        self.bouton.setObjectName("principal")
        self.bouton.clicked.connect(self._cloner_ou_annuler)
        ligne.addWidget(self.bouton)
        l3.addLayout(ligne)
        self.etat = QtWidgets.QLabel(tr("etape.attente"))
        self.etat.setObjectName("resume")
        l3.addWidget(self.etat)
        lo.addWidget(g3)
        self._majeur_bouton()
        return w

    def _onglet_apres(self):
        w = QtWidgets.QWidget()
        lo = QtWidgets.QVBoxLayout(w)
        intro = QtWidgets.QLabel(tr("apres.intro") if sys.platform == "win32"
                                 else tr("apres.intro") + tr("apres.linux_conseil"))
        intro.setWordWrap(True)
        lo.addWidget(intro)
        self.etat_c = QtWidgets.QLabel()
        self.etat_c.setObjectName("resume")
        lo.addWidget(self.etat_c)
        ligne = QtWidgets.QHBoxLayout()
        self.bouton_agrandir = QtWidgets.QPushButton(tr("apres.agrandir"))
        self.bouton_agrandir.setObjectName("principal")
        self.bouton_agrandir.clicked.connect(self._agrandir)
        self.bouton_winre = QtWidgets.QPushButton(tr("apres.winre"))
        self.bouton_winre.setToolTip(tr("apres.winre_astuce"))
        self.bouton_winre.clicked.connect(self._winre)
        ligne.addWidget(self.bouton_agrandir)
        ligne.addWidget(self.bouton_winre)
        ligne.addStretch(1)
        lo.addLayout(ligne)
        self.sortie_apres = QtWidgets.QPlainTextEdit()
        self.sortie_apres.setReadOnly(True)
        lo.addWidget(self.sortie_apres, 1)
        windows = sys.platform == "win32"
        self.bouton_agrandir.setEnabled(windows)
        self.bouton_winre.setEnabled(windows)
        if not windows:
            self.etat_c.setText(tr("apres.windows"))
        return w

    def _construire_menus(self):
        m = self.menuBar().addMenu(tr("menu.fichier"))
        m.addAction(tr("menu.quitter"), self.close).setShortcut("Ctrl+Q")
        lg = self.menuBar().addMenu(tr("menu.langue"))
        groupe = QtGui.QActionGroup(self)
        actuel = self.reglages.value("langue", "auto", type=str)
        for code, libelle in (("auto", tr("menu.langue.auto")), ("fr", "Français"), ("en", "English")):
            a = lg.addAction(libelle)
            a.setCheckable(True)
            a.setChecked(code == actuel)
            groupe.addAction(a)
            a.triggered.connect(lambda _=False, c=code: self._changer_langue(c))
        aide = self.menuBar().addMenu(tr("menu.aide"))
        aide.addAction(tr("menu.manuel"), self._ouvrir_manuel).setShortcut("F1")
        aide.addAction(tr("menu.mode_emploi"), self._afficher_aide)
        aide.addSeparator()
        aide.addAction(tr("menu.maj"), lambda: self._check_update(manual=True))
        aide.addAction(tr("menu.signaler"), self._signaler_probleme)
        self.act_autoreport = aide.addAction(tr("menu.rapports_auto"))
        self.act_autoreport.setCheckable(True)
        try:
            import reporting
            self.act_autoreport.setChecked(reporting.consentement() is True)
        except Exception:
            self.act_autoreport.setEnabled(False)
        self.act_autoreport.toggled.connect(self._basculer_rapports)
        aide.addSeparator()
        aide.addAction(tr("menu.a_propos"), self._a_propos)
        self.onglets.currentChanged.connect(self._onglet_change)

    # ------------------------------------------------------------ disques
    def actualiser(self):
        self.bouton_actualiser.setEnabled(False)
        self.statusBar().showMessage(tr("bouton.actualiser") + "…")

        def travail():
            try:
                liste = D.lister()
                erreur = None
            except Exception as e:  # noqa: BLE001
                liste, erreur = [], e
            liste += [D.disque_image(c) for c in self.images]
            self._inventaire_pret.emit(liste, erreur)

        threading.Thread(target=travail, daemon=True, name="calque-inventaire").start()

    def _recevoir_inventaire(self, liste, erreur):
        self.bouton_actualiser.setEnabled(True)
        self.statusBar().clearMessage()
        if erreur is not None and not liste:
            QtWidgets.QMessageBox.warning(self, "Calque", tr("inventaire.echec", detail=message(erreur)))
        self.charger_disques(liste)
        suite, self._apres_inventaire = getattr(self, "_apres_inventaire", None), None
        if suite:
            suite()

    def charger_disques(self, liste: list[D.Disque]):
        ancienne_s = self.choix_source.currentData()
        ancienne_c = self.choix_cible.currentData()
        self.disques = liste
        for c in (self.choix_source, self.choix_cible):
            c.blockSignals(True)
            c.clear()
        for i, d in enumerate(liste):
            libelle = d.libelle() + (f" — {tr('disque.systeme')}" if d.systeme else "")
            self.choix_source.addItem(libelle, i)
            if not d.systeme:
                self.choix_cible.addItem(libelle, i)
        if not liste:
            self.choix_source.addItem(tr("disque.aucun"), None)
        # source par défaut : le disque système ; cible : le plus grand des autres
        def trouver(combo, chemin):
            for k in range(combo.count()):
                j = combo.itemData(k)
                if j is not None and liste[j].chemin == chemin:
                    return k
            return -1
        k = trouver(self.choix_source, liste[ancienne_s].chemin) if isinstance(ancienne_s, int) and ancienne_s < len(liste) else -1
        if k < 0:
            k = next((n for n in range(self.choix_source.count())
                      if self.choix_source.itemData(n) is not None and liste[self.choix_source.itemData(n)].systeme), 0)
        self.choix_source.setCurrentIndex(k)
        k = trouver(self.choix_cible, liste[ancienne_c].chemin) if isinstance(ancienne_c, int) and ancienne_c < len(liste) else -1
        if k < 0 and self.choix_cible.count():
            k = max(range(self.choix_cible.count()), key=lambda n: liste[self.choix_cible.itemData(n)].taille)
        self.choix_cible.setCurrentIndex(max(k, 0))
        for c in (self.choix_source, self.choix_cible):
            c.blockSignals(False)
        self._recalculer()

    def _disque(self, combo) -> D.Disque | None:
        i = combo.currentData()
        return self.disques[i] if isinstance(i, int) and i < len(self.disques) else None

    def _recalculer(self, *_):
        if self.en_cours:
            return
        source, cible = self._disque(self.choix_source), self._disque(self.choix_cible)
        self.plan = None
        self.barres.montrer(None)
        self.barre.setValue(0)
        self.etat.setText(tr("etape.attente"))
        self.confirmation.setChecked(False)
        self.confirmation.setText(tr("option.confirmer", cible=cible.libelle() if cible else "—"))
        if not source or not cible or source.chemin == cible.chemin:
            self.texte_plan.setText(tr("plan.choisir"))
            self._majeur_bouton()
            return
        QtWidgets.QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            bl = D.bitlocker_windows() if sys.platform == "win32" and source.numero is not None else set()
            self.plan = clonage.preparer_plan(source, cible, self.option_deplacer.isChecked(), bl)
        except Exception as e:  # noqa: BLE001
            self.texte_plan.setText(f"<p style='color:#A33'><b>{tr('plan.bloque')}</b> {_html(message(e))}</p>")
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        usb = cible.bus.upper() == "USB"
        self.option_doux.setVisible(usb)
        self.option_doux.setChecked(usb)
        if self.plan:
            self.barres.montrer(self.plan)
        self._majeur_texte_plan()
        self._majeur_bandeau()
        self._majeur_bouton()

    DEBIT_DOUX = 200e6

    def _debit_max(self):
        return self.DEBIT_DOUX if self.option_doux.isVisible() and self.option_doux.isChecked() else None

    def _majeur_texte_plan(self, *_):
        if self.plan:
            self.texte_plan.setText(self._texte_plan(self.plan))

    def _majeur_bandeau(self):
        """Clonage interrompu : bouton Reprendre si ce sont les mêmes disques."""
        if self.en_cours:
            self.bandeau.hide()
            return
        d = clonage.Journal().charger()
        if not d:
            self.bandeau.hide()
            return
        total = d.get("total") or 1
        fait = 0
        try:
            fait = min(100, int(100 * int(d.get("blocs_faits", 0)) * clonage.BLOC / total))
        except Exception:
            pass
        memes = bool(self.plan and clonage.reprise_possible(self.plan))
        self.texte_bandeau.setText(tr("reprise.titre", date=d.get("date", "?"), pourcent=fait) + " "
                                   + tr("reprise.memes" if memes else "reprise.autres"))
        self.bouton_reprendre.setVisible(memes)
        self.bandeau.show()

    def _reprendre(self):
        if self.plan and clonage.reprise_possible(self.plan):
            self._lancer(self.plan, self.option_verifier.isChecked(), reprendre=True)

    def _oublier_reprise(self):
        r = QtWidgets.QMessageBox.question(self, "Calque", tr("reprise.abandon_confirmer"))
        if r != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        QtWidgets.QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            clonage.abandonner_reprise()
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self._majeur_bandeau()

    def _texte_plan(self, plan: clonage.Plan) -> str:
        """Le plan en clair : d'abord ce qui empêche ou ce qu'il faut savoir
        AVANT (en couleur, en tête, toujours visible), puis ce qui va se passer."""
        ss = plan.table_source.taille_secteur
        morceaux = []
        morceaux.extend(
            f"<p style='background:#F8E6E3; color:#A33A2E; padding:4px'><b>{tr('niveau.bloque')}</b> — "
            f"{_html(tr(c, **k))}</p>" for c, k in plan.bloquants)
        importants = [(c, k) for c, k in plan.avertissements if c in IMPORTANTS]
        infos = [(c, k) for c, k in plan.avertissements if c not in IMPORTANTS]
        morceaux.extend(
            f"<p style='background:#FBF1E2; color:#7A4A0C; padding:4px'><b>{tr('niveau.important')}</b> — "
            f"{_html(tr(c, **k))}</p>" for c, k in importants)
        if not plan.bloquants:
            morceaux.append("<p>" + _html(tr("plan.resume", n=len(plan.travaux), style=plan.table_source.style.upper(),
                                              cible=plan.cible.libelle())) + "</p>")
            principale = clonage.T.partition_principale(plan.table_source)
            nom = ""
            if principale:
                nom = next((v.nom for v in plan.source.volumes if v.debut == principale.debut * ss and v.nom), "") \
                    or tr(f"nature.{principale.nature}")
            gain = D.octets_lisibles(plan.espace_gagne())
            if any(t.deplacee for t in plan.travaux):
                morceaux.append("<p>" + _html(tr("plan.deplacees", gain=gain, nom=nom)) + "</p>")
            elif plan.espace_gagne() > 0:
                morceaux.append("<p>" + _html(tr("plan.gain", gain=gain, nom=nom)) + "</p>")
            if plan.estimation:
                bas, haut = plan.duree_estimee(self.option_verifier.isChecked(), self._debit_max())
                morceaux.append("<p><b>" + _html(tr("plan.estimation", octets=D.octets_lisibles(plan.estimation),
                                                     min=duree(bas, True), max=duree(haut * 1.0001 + 300, True)))
                                + "</b></p>")
        if infos:
            morceaux.append(f"<p><b>{tr('niveau.info')}</b></p><ul>" + "".join(
                f"<li>{_html(tr(c, **k))}</li>" for c, k in infos) + "</ul>")
        return "".join(morceaux)

    def _majeur_bouton(self, *_):
        if self.en_cours:
            self.bouton.setEnabled(True)
            return
        self.bouton.setEnabled(bool(self.plan and self.plan.possible and self.confirmation.isChecked()))
        self.confirmation.setEnabled(bool(self.plan and self.plan.possible))

    # ------------------------------------------------------------ clonage
    def _cloner_ou_annuler(self):
        if self.en_cours:
            self._annulation.set()
            self.bouton.setEnabled(False)
            return
        plan = self.plan
        if not plan:
            return
        boite = QtWidgets.QMessageBox(self)
        boite.setWindowTitle(tr("dlg.confirmer_titre"))
        boite.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        boite.setText(tr("dlg.confirmer", source=_html(plan.source.libelle()), cible=_html(plan.cible.libelle())))
        boite.setInformativeText(tr("dlg.avant"))
        oui = boite.addButton(tr("dlg.effacer"), QtWidgets.QMessageBox.ButtonRole.DestructiveRole)
        non = boite.addButton(tr("bouton.annuler"), QtWidgets.QMessageBox.ButtonRole.RejectRole)
        boite.setDefaultButton(non)
        boite.exec()
        if boite.clickedButton() is not oui:
            return
        self._lancer(plan, self.option_verifier.isChecked())

    def _lancer(self, plan, verifier: bool, reprendre: bool = False, tolerer: bool = False):
        self.en_cours = True
        self._annulation.clear()
        self.bandeau.hide()
        self._dernier = (plan, verifier)
        debit_max = self._debit_max()
        for w in (self.choix_source, self.choix_cible, self.bouton_actualiser, self.option_deplacer,
                  self.option_verifier, self.option_doux, self.confirmation):
            w.setEnabled(False)
        self.bouton.setText(tr("bouton.annuler"))
        self.barre.setValue(0)

        def travail():
            try:
                bilan = clonage.cloner(plan, rappel=lambda **k: self._progres.emit(k),
                                       annulation=self._annulation, verifier=verifier,
                                       journal=lambda cle, **k: self._journal.emit(cle, k),
                                       reprendre=reprendre, tolerer_illisibles=tolerer, debit_max=debit_max)
                self._fin.emit(bilan, None)
            except BaseException as e:  # noqa: BLE001
                self._fin.emit(None, e)

        threading.Thread(target=travail, daemon=True, name="calque-clonage").start()

    def _afficher_journal(self, cle: str, champs: dict):
        if "octets" in champs:
            champs = dict(champs, octets=D.octets_lisibles(champs["octets"]))
        self.etat.setText(tr(f"etape.{cle}", **champs))

    def _afficher_progres(self, k: dict):
        total = k.get("total") or 1
        self.barre.setValue(int(1000 * k.get("fait", 0) / total))
        debit = k.get("debit") or 0
        reste = (total - k.get("fait", 0)) / debit if debit > 0 else 0
        self.etat.setText(tr("etape.progres", etape=tr(f"etape.{k['etape']}"), fait=D.octets_lisibles(k.get("fait", 0)),
                             total=D.octets_lisibles(total), debit=D.octets_lisibles(int(debit)),
                             reste=duree(reste)))

    def _clonage_fini(self, bilan, erreur):
        self.en_cours = False
        for w in (self.choix_source, self.choix_cible, self.bouton_actualiser, self.option_deplacer,
                  self.option_verifier, self.option_doux):
            w.setEnabled(True)
        self.bouton.setText(tr("bouton.cloner"))
        self.confirmation.setChecked(False)
        self._majeur_bouton()
        self._majeur_bandeau()
        if erreur is None:
            self.barre.setValue(1000)
            self.etat.setText(tr("etape.fini"))
            verifie = tr("fin.verifie") if bilan.octets_verifies else ""
            remarques = ""
            if bilan.secteurs_illisibles:
                remarques += tr("fin.illisibles", n=bilan.secteurs_illisibles)
            if bilan.reconnexions:
                remarques += tr("fin.reconnexions", n=bilan.reconnexions)
            if bilan.controles:
                ko = [o for o, ok, _ in bilan.controles if not ok]
                remarques += tr("fin.controles", resultat=tr("fin.controle_ko", outil=", ".join(ko)) if ko
                                else tr("fin.controle_ok") + " (" + ", ".join(o.split()[0] for o, _, _ in bilan.controles) + ")")
            QtWidgets.QMessageBox.information(self, tr("fin.titre"), tr(
                "fin.texte", copie=D.octets_lisibles(bilan.repris_a + bilan.octets_copies), verifie=verifie,
                duree=duree(bilan.duree), remarques=remarques))
            return
        if isinstance(erreur, clonage.Annule):
            self.etat.setText(tr("fin.annule"))
            QtWidgets.QMessageBox.information(self, "Calque", tr("fin.annule"))
            return
        cle = getattr(erreur, "cle", "")
        self.etat.setText(tr("fin.echec", detail=message(erreur)).splitlines()[0])
        if cle == "clone.source_illisible":
            boite = QtWidgets.QMessageBox(self)
            boite.setWindowTitle("Calque")
            boite.setIcon(QtWidgets.QMessageBox.Icon.Warning)
            boite.setText(message(erreur))
            continuer = boite.addButton(tr("clone.continuer_malgre"), QtWidgets.QMessageBox.ButtonRole.AcceptRole)
            boite.addButton(tr("clone.arreter"), QtWidgets.QMessageBox.ButtonRole.RejectRole)
            boite.exec()
            if boite.clickedButton() is continuer and self.plan:
                self._lancer(self.plan, self._dernier[1], reprendre=True, tolerer=True)
            return
        if cle == "clone.cible_perdue":
            boite = QtWidgets.QMessageBox(self)
            boite.setWindowTitle("Calque")
            boite.setIcon(QtWidgets.QMessageBox.Icon.Warning)
            boite.setText(message(erreur))
            reprendre = boite.addButton(tr("dlg.reprendre_maintenant"), QtWidgets.QMessageBox.ButtonRole.AcceptRole)
            boite.addButton(tr("clone.arreter"), QtWidgets.QMessageBox.ButtonRole.RejectRole)
            boite.exec()
            if boite.clickedButton() is reprendre:
                self._apres_inventaire = self._reprendre
                self.actualiser()
            return
        if not cle:
            try:
                import traceback

                import reporting
                reporting.signaler_plantage("".join(traceback.format_exception(type(erreur), erreur, erreur.__traceback__)))
            except Exception:
                pass
        if cle in ("clone.cliche_perdu", "clone.reprise_impossible"):
            clonage.abandonner_reprise()
            self._majeur_bandeau()
        QtWidgets.QMessageBox.critical(self, "Calque", tr("fin.echec", detail=message(erreur)))

    # ------------------------------------------------------------ après
    def _onglet_change(self, i: int):
        if i == 1 and sys.platform == "win32":
            self._lire_etat_c()

    def _lire_etat_c(self):
        try:
            e = clonage.etat_c()
            if int(e["maximum"]) <= int(e["taille"]) + 1024 * 1024:
                texte = tr("apres.deja")
            else:
                texte = tr("apres.etat", taille=D.octets_lisibles(int(e["taille"])),
                           maximum=D.octets_lisibles(int(e["maximum"])))
            disque = next((d for d in self.disques if d.numero == int(e.get("disque", -1))), None)
            if disque:
                texte = _html(tr("apres.disque_actuel", disque=disque.libelle())) + "<br>" + texte
            self.etat_c.setText(texte)
        except Exception:
            self.etat_c.setText(tr("apres.etat_inconnu"))

    def _agrandir(self):
        QtWidgets.QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            e = clonage.agrandir_c()
            self.sortie_apres.appendPlainText(tr("apres.fait", taille=D.octets_lisibles(int(e["taille"]))))
        except Exception as ex:  # noqa: BLE001
            self.sortie_apres.appendPlainText(tr("apres.echec", detail=message(ex)))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self._lire_etat_c()

    def _winre(self):
        QtWidgets.QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.sortie_apres.appendPlainText(clonage.reparer_winre())
        except Exception as ex:  # noqa: BLE001
            self.sortie_apres.appendPlainText(tr("apres.echec", detail=message(ex)))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    # ------------------------------------------------------------ fermeture, aide
    def closeEvent(self, ev):
        if self.en_cours:
            r = QtWidgets.QMessageBox.question(self, "Calque", tr("dlg.quitter_en_cours"))
            if r != QtWidgets.QMessageBox.StandardButton.Yes:
                ev.ignore()
                return
            self._annulation.set()
        super().closeEvent(ev)

    def _afficher_aide(self):
        QtWidgets.QMessageBox.information(self, tr("aide.titre"), tr("aide.texte"))

    def _ouvrir_manuel(self):
        docs = Path(__file__).resolve().parent.parent / "docs"
        try:
            import interface_kit
            if interface_kit.ouvrir_manuel([docs], langue()):
                return
        except Exception:
            pass
        QtWidgets.QMessageBox.information(self, "Calque", tr("manuel.absent"))

    def _changer_langue(self, code: str):
        self.reglages.setValue("langue", code)
        QtWidgets.QMessageBox.information(self, "Calque", tr("menu.langue.redemarrer"))

    def _a_propos(self):
        boite = QtWidgets.QMessageBox(self)
        boite.setWindowTitle(tr("menu.a_propos"))
        logo = Path(__file__).resolve().parent.parent / "logo_128.png"
        if logo.exists():
            boite.setIconPixmap(QtGui.QPixmap(str(logo)))
        boite.setText(tr("a_propos.texte", version=__version__))
        boite.exec()

    def _basculer_rapports(self, coche: bool):
        try:
            import reporting
            reporting.definir_consentement(bool(coche))
        except Exception:
            pass

    # ------------------------------------------------------------ mise à jour (kit commun)
    def _check_update(self, manual: bool = False):
        if self.en_cours:
            if manual:
                QtWidgets.QMessageBox.information(self, tr("maj.titre"), tr("maj.pas_pendant"))
            return
        if not hasattr(self, "_maj_branche"):
            self._maj_signal.connect(self._update_result)
            self._maj_branche = True
        if manual:
            self.statusBar().showMessage(tr("maj.recherche"))

        def worker():
            try:
                import updater
                info = updater.check(__version__)
            except Exception:
                info = None
            self._maj_signal.emit(info, manual)

        threading.Thread(target=worker, daemon=True, name="calque-maj").start()

    def _update_result(self, info, manual: bool):
        self.statusBar().clearMessage()
        if not info:
            if manual:
                QtWidgets.QMessageBox.information(self, tr("maj.titre"), tr("maj.a_jour", version=__version__))
            return
        if self.en_cours:
            return
        try:
            import updater
            installe = bool(updater.is_packaged())
            page = f"https://github.com/{updater.REPO}/releases/latest"
        except Exception:
            installe, page = False, ""
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(tr("maj.titre"))
        box.setText(tr("maj.dispo", nouvelle=info["version"], version=__version__))
        notes = (info.get("notes") or "").strip()
        try:
            import updater
            notes = updater.notes_dans_la_langue(notes, langue())
        except Exception:
            pass
        if notes:
            box.setDetailedText(notes[:4000])
        oui = box.addButton(tr("maj.installer") if installe else tr("maj.page"), QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("maj.plus_tard"), QtWidgets.QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not oui:
            return
        if not installe:
            if page:
                QtGui.QDesktopServices.openUrl(QtCore.QUrl(page))
            return
        self._telecharger_maj(info)

    def _telecharger_maj(self, info: dict):
        import updater
        dlg = QtWidgets.QProgressDialog(tr("maj.telechargement"), None, 0, 100, self)
        dlg.setWindowTitle(tr("maj.titre"))
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setCancelButton(None)
        dlg.setMinimumDuration(0)
        etat = {"fait": 0, "total": 0, "fini": False, "erreur": None, "pose": False}

        def _prog(done, total):
            etat["fait"], etat["total"] = done, total

        def worker():
            try:
                etat["pose"] = bool(updater.download_and_apply(info, progress=_prog))
            except Exception as exc:
                etat["erreur"] = exc
            finally:
                etat["fini"] = True

        threading.Thread(target=worker, daemon=True, name="calque-maj-pose").start()
        poll = QtCore.QTimer(self)
        poll.setInterval(100)

        def tick():
            if not etat["fini"]:
                if etat["total"] > 0:
                    dlg.setValue(min(99, etat["fait"] * 100 // etat["total"]))
                return
            poll.stop()
            dlg.close()
            if etat["erreur"] is not None or not etat["pose"]:
                texte = str(etat["erreur"] or "archive")
                verrou = ("WinError 32" in texte or "used by another process" in texte
                          or isinstance(etat["erreur"], PermissionError))
                QtWidgets.QMessageBox.warning(self, tr("maj.titre"),
                                              tr("maj.verrou") if verrou else tr("maj.echec", erreur=texte))
                return
            QtWidgets.QMessageBox.information(self, tr("maj.titre"), tr("maj.redemarre"))
            try:
                updater.restart()
            finally:
                QtWidgets.QApplication.quit()

        poll.timeout.connect(tick)
        poll.start()
        self._maj_poll = poll

    # ------------------------------------------------------------ rapports
    def _signaler_probleme(self):
        try:
            import reporting
        except Exception:
            return
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(tr("signal.titre"))
        dlg.resize(560, 360)
        lo = QtWidgets.QVBoxLayout(dlg)
        lo.addWidget(QtWidgets.QLabel(tr("signal.invite")))
        texte = QtWidgets.QPlainTextEdit()
        texte.setPlaceholderText(tr("signal.exemple"))
        lo.addWidget(texte)
        note = QtWidgets.QLabel(tr("signal.note"))
        note.setWordWrap(True)
        lo.addWidget(note)
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok
                                          | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        btns.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText(tr("signal.envoyer"))
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lo.addWidget(btns)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        description = texte.toPlainText().strip()
        if not description:
            return
        liste = "\n".join(f"{d.libelle()} · {d.taille_secteur} o/secteur{' · système' if d.systeme else ''}"
                          for d in self.disques)
        accord = reporting.consentement()
        if accord is not True:
            reporting.definir_consentement(True)
        rapport = reporting.envoyer("manuel", description=description + "\n\n" + liste, version=__version__)
        if accord is not True:
            reporting.definir_consentement(bool(accord))
        chemin = None
        try:
            chemin = reporting.paquet_local(rapport, None)
        except Exception:
            pass
        msg = (tr("signal.parti") if rapport.get("transmis", True) and not chemin else tr("signal.local", chemin=chemin))
        QtWidgets.QMessageBox.information(self, tr("signal.merci"), msg)


def _html(t: str) -> str:
    return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
