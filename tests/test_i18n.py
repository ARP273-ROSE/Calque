"""Garde-fous de traduction."""
import string
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
from calque import i18n  # noqa: E402


def champs(modele: str) -> set:
    return {nom for _, nom, _, _ in string.Formatter().parse(modele) if nom}


def test_toutes_les_cles_dans_les_deux_langues():
    for cle, textes in i18n.TEXTES.items():
        for lg in i18n.LANGUES:
            assert textes.get(lg, "").strip(), f"{cle} : texte {lg} vide ou absent"


def test_memes_champs_de_format():
    for cle, textes in i18n.TEXTES.items():
        assert champs(textes["fr"]) == champs(textes["en"]), cle


def test_chaque_cle_du_moteur_est_traduite():
    """Les erreurs et étapes nommées dans le moteur ont toutes un texte."""
    import re
    manquantes = set()
    for f in (RACINE / "calque").glob("*.py"):
        for cle in re.findall(r'["\']((?:table|plan|clone|acces|etape)\.[a-z_]+)["\']', f.read_text(encoding="utf-8")):
            if cle not in i18n.TEXTES:
                manquantes.add(cle)
    for etape in ("preparation", "cliche", "analyse", "zones", "copie", "verification", "table", "fini"):
        if f"etape.{etape}" not in i18n.TEXTES:
            manquantes.add(etape)
    assert not manquantes, manquantes


def test_cle_inconnue_ne_casse_rien():
    assert i18n.tr("cle.qui.n.existe.pas") == "cle.qui.n.existe.pas"


def test_detection_par_environnement(monkeypatch):
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LANG", "fr_FR.UTF-8")
    assert i18n.detecter() == "fr"
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    assert i18n.detecter() == "en"


def test_message_d_erreur_traduit():
    from calque.table import ErreurTable
    i18n.definir_langue("en")
    assert "too small" in i18n.message(ErreurTable("table.cible_trop_petite", cible="1 TB", besoin="2 TB"))
    i18n.definir_langue("fr")
    assert "trop petite" in i18n.message(ErreurTable("table.cible_trop_petite", cible="1 To", besoin="2 To"))


def test_option_version():
    sortie = subprocess.run([sys.executable, str(RACINE / "run.py"), "--version"],
                            capture_output=True, text=True, timeout=60)
    assert sortie.returncode == 0 and sortie.stdout.startswith("Calque ")


def test_paquet_reconnu_sur_les_trois_systemes(tmp_path, monkeypatch):
    import updater
    for chemin in ("python/python.exe", "python/bin/python3"):
        racine = tmp_path / chemin.replace("/", "_")
        exe = racine / chemin
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        monkeypatch.setattr(updater, "app_dir", lambda r=racine: r / "app")
        assert updater.is_packaged(), chemin
