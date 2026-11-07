"""Apparence figée de Calque.

L'interface ne doit dépendre ni du thème de Windows (clair, sombre, contraste
élevé), ni de sa couleur d'accentuation, ni de ses polices : une fenêtre qui
change d'aspect d'un PC à l'autre (ou d'un système à l'autre) déroute. On impose donc :

* le style Qt « Fusion », identique sur toutes les plateformes ;
* une palette fixe (papier calque bleuté, encre, bleu de Prusse et ocre), appliquée aussi
  aux boîtes de dialogue ;
* des polices embarquées (Source Sans 3 pour le texte, EB Garamond pour les
  titres), chargées depuis le paquet et non depuis Windows.

Seule la mise à l'échelle (125 %, 150 %…) reste celle de Windows : la
neutraliser rendrait le texte minuscule sur un écran 4K.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6 import QtGui, QtWidgets

POLICES = Path(__file__).resolve().parent / "polices"

PAPIER = "#F4F7F9"      # fond général
CARTE = "#FFFFFF"       # zones de saisie, liste
LIGNE = "#EDF2F5"       # lignes alternées
ENCRE = "#1F2A33"       # texte
GRIS = "#6B7884"        # texte secondaire, désactivé
BORD = "#C9D4DC"        # traits et contours
BLEU = "#1D4E73"    # couleur d'action
BLEU_CLAIR = "#2A6391"
OCRE = "#C07A1E"          # sélection, accents
SELECTION = "#CFE0EC"

FAMILLE_TEXTE = "Source Sans 3"
FAMILLE_TITRE = "EB Garamond"


def charger_polices() -> tuple[str, str]:
    """Charge les polices du paquet ; repli sur des polices système sûres."""
    texte, titre = "Segoe UI", "Georgia"
    for f in sorted(POLICES.glob("*.otf")):
        ident = QtGui.QFontDatabase.addApplicationFont(str(f))
        if ident < 0:
            continue
        familles = QtGui.QFontDatabase.applicationFontFamilies(ident)
        if FAMILLE_TEXTE in familles:
            texte = FAMILLE_TEXTE
        if FAMILLE_TITRE in familles:
            titre = FAMILLE_TITRE
    return texte, titre


def _palette() -> QtGui.QPalette:
    p = QtGui.QPalette()
    R = QtGui.QPalette.ColorRole
    G = QtGui.QPalette.ColorGroup
    c = QtGui.QColor
    # les TROIS groupes (actif, inactif, désactivé) : un rôle laissé vide dans
    # le groupe désactivé prendrait la couleur du système
    for groupe in (G.Active, G.Inactive, G.Disabled):
        p.setColor(groupe, R.Window, c(PAPIER))
        p.setColor(groupe, R.WindowText, c(ENCRE))
        p.setColor(groupe, R.Base, c(CARTE))
        p.setColor(groupe, R.AlternateBase, c(LIGNE))
        p.setColor(groupe, R.Text, c(ENCRE))
        p.setColor(groupe, R.Button, c("#E6EDF2"))
        p.setColor(groupe, R.ButtonText, c(ENCRE))
        p.setColor(groupe, R.Highlight, c(SELECTION))
        p.setColor(groupe, R.HighlightedText, c(ENCRE))
        p.setColor(groupe, R.ToolTipBase, c("#FBFCFD"))
        p.setColor(groupe, R.ToolTipText, c(ENCRE))
        p.setColor(groupe, R.PlaceholderText, c(GRIS))
        p.setColor(groupe, R.Link, c(BLEU))
        p.setColor(groupe, R.BrightText, c("#FFFFFF"))
        p.setColor(groupe, R.Light, c("#FFFFFF"))
        p.setColor(groupe, R.Midlight, c("#EEF3F6"))
        p.setColor(groupe, R.Mid, c(BORD))
        p.setColor(groupe, R.Dark, c("#A9B7C2"))
        p.setColor(groupe, R.Shadow, c("#7E8C97"))
    for role in (R.WindowText, R.Text, R.ButtonText, R.HighlightedText):
        p.setColor(G.Disabled, role, c(GRIS))
    p.setColor(G.Disabled, R.Window, c(PAPIER))
    p.setColor(G.Disabled, R.Base, c("#F0F4F7"))
    p.setColor(G.Disabled, R.Button, c("#E5ECF1"))
    return p


QSS = f"""
QWidget {{ color: {ENCRE}; }}
QMainWindow, QDialog, QMessageBox {{ background: {PAPIER}; }}
QToolTip {{ background: #FBFCFD; color: {ENCRE}; border: 1px solid {BORD}; padding: 4px; }}

QLabel#titre {{ font-family: "{{TITRE}}"; font-size: 22pt; color: {BLEU}; }}
QLabel#sous_titre {{ color: {GRIS}; }}
QLabel#resume {{ color: {ENCRE}; padding: 2px 4px; }}
QFrame#bandeau {{ background: #FBF1E2; border: 1px solid {OCRE}; border-radius: 8px; padding: 4px; }}

QListWidget {{
    background: {CARTE}; alternate-background-color: {LIGNE};
    border: 1px solid {BORD}; border-radius: 6px; padding: 4px; outline: 0;
}}
QListWidget::item {{ padding: 6px 6px; border-radius: 4px; }}
QListWidget::item:selected {{ background: {SELECTION}; color: {ENCRE}; }}
QListWidget::item:hover {{ background: #DDE9F1; }}

QPushButton {{
    background: #EEF3F6; border: 1px solid {BORD}; border-radius: 6px;
    padding: 6px 14px; min-height: 22px;
}}
QPushButton:hover {{ background: #E1EAF0; border-color: #AFC0CC; }}
QPushButton:pressed {{ background: #D4E1EA; }}
QPushButton:disabled {{ color: {GRIS}; background: #EDF1F4; border-color: #DCE4EA; }}
QPushButton#principal {{
    background: {BLEU}; color: #FFFFFF; border: 1px solid {BLEU};
    border-radius: 8px; padding: 8px 26px;
}}
QPushButton#principal:hover {{ background: {BLEU_CLAIR}; }}
QPushButton#principal:pressed {{ background: #153B58; }}
QPushButton#principal:disabled {{ background: #A9BCCB; border-color: #A9BCCB; color: #FFFFFF; }}

QGroupBox {{
    border: 1px solid {BORD}; border-radius: 8px; margin-top: 14px; padding: 10px 10px 8px 10px;
    background: #FAFCFD;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {BLEU}; font-weight: 600;
}}
QLineEdit {{
    background: {CARTE}; border: 1px solid {BORD}; border-radius: 5px; padding: 5px 7px;
    selection-background-color: {SELECTION}; selection-color: {ENCRE};
}}
QLineEdit:focus {{ border-color: {OCRE}; }}
QComboBox {{
    background: {CARTE}; border: 1px solid {BORD}; border-radius: 5px; padding: 4px 8px;
}}
QComboBox:hover, QComboBox:focus {{ border-color: {OCRE}; }}
QComboBox QAbstractItemView {{
    background: {CARTE}; border: 1px solid {BORD}; selection-background-color: {SELECTION};
    selection-color: {ENCRE}; outline: 0;
}}
QLineEdit:read-only {{ background: #F0F4F7; color: #4A5763; }}

QTabWidget::pane {{ border: 1px solid {BORD}; border-radius: 8px; top: -1px; background: {PAPIER}; }}
QTabBar::tab {{
    background: #E2EAF0; border: 1px solid {BORD}; border-bottom: none;
    border-top-left-radius: 7px; border-top-right-radius: 7px;
    padding: 7px 18px; margin-right: 3px; color: #4A5763;
}}
QTabBar::tab:selected {{ background: {PAPIER}; color: {BLEU}; font-weight: 600; }}
QTabBar::tab:hover:!selected {{ background: #EAF0F4; }}
QRadioButton {{ spacing: 8px; padding: 2px 0; }}
QRadioButton::indicator {{
    width: 16px; height: 16px; border: 1px solid #A9B7C2; border-radius: 9px; background: {CARTE};
}}
QRadioButton::indicator:hover {{ border-color: {OCRE}; }}
QRadioButton::indicator:checked {{ background: {BLEU}; border-color: {BLEU}; image: url("{{POINT}}"); }}
QCheckBox {{ spacing: 8px; padding: 2px 0; }}
QCheckBox::indicator {{
    width: 17px; height: 17px; border: 1px solid #A9B7C2; border-radius: 4px; background: {CARTE};
}}
QCheckBox::indicator:hover {{ border-color: {OCRE}; }}
QCheckBox::indicator:checked {{ background: {BLEU}; border-color: {BLEU}; image: url("{{COCHE}}"); }}

QProgressBar {{
    border: 1px solid {BORD}; border-radius: 6px; background: {CARTE}; text-align: center;
    min-height: 20px;
}}
QProgressBar::chunk {{ background: {OCRE}; border-radius: 5px; }}

QMenuBar {{ background: {PAPIER}; border-bottom: 1px solid {BORD}; }}
QMenuBar::item {{ padding: 4px 10px; background: transparent; }}
QMenuBar::item:selected {{ background: #E1EAF0; border-radius: 4px; }}
QMenu {{ background: {CARTE}; border: 1px solid {BORD}; padding: 4px; }}
QMenu::item {{ padding: 5px 24px 5px 20px; border-radius: 4px; }}
QMenu::item:selected {{ background: {SELECTION}; color: {ENCRE}; }}
QMenu::separator {{ height: 1px; background: {BORD}; margin: 4px 8px; }}

QStatusBar {{ background: {PAPIER}; color: {GRIS}; border-top: 1px solid {BORD}; }}
QPlainTextEdit {{ background: {CARTE}; border: 1px solid {BORD}; border-radius: 5px; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #C3CFD8; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #A8B8C4; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
"""


def appliquer(app: QtWidgets.QApplication) -> None:
    """Fige l'apparence de toute l'application (fenêtre et dialogues)."""
    app.setStyle("Fusion")
    try:  # Qt ≥ 6.8 : ignorer le mode sombre de Windows
        from PyQt6.QtCore import Qt
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    except Exception:
        pass
    texte, titre = charger_polices()
    police = QtGui.QFont(texte)
    police.setPointSizeF(11)
    police.setHintingPreference(QtGui.QFont.HintingPreference.PreferNoHinting)
    app.setFont(police)
    app.setPalette(_palette())
    coche = (Path(__file__).resolve().parent / "icones" / "coche.svg").as_posix()
    point = (Path(__file__).resolve().parent / "icones" / "point.svg").as_posix()
    app.setStyleSheet(QSS.replace("{TITRE}", titre).replace("{COCHE}", coche)
                      .replace("{POINT}", point))
