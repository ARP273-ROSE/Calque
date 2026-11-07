"""Clonage de bout en bout sur de vrais disques image (GPT et MBR façon Windows).

On vérifie ce qui fait démarrer — ou non — un clone :
identifiants conservés, partition de récupération reportée en fin de disque,
espace libre juste derrière C:, volumes NTFS lisibles et fichiers identiques,
tables valides (sgdisk -v), et l'effet d'une interruption.
"""
import subprocess
import sys
import threading
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fabrique  # noqa: E402
from calque import clonage, disques, ntfs, table  # noqa: E402
from calque.peripherique import ouvrir  # noqa: E402

pytestmark = pytest.mark.skipif(not fabrique.outils_presents(), reason="sgdisk/ntfs-3g/dosfstools absents")
MIO = fabrique.MIO


def _vide(chemin: Path, taille_mio: int, motif: bytes = b"") -> Path:
    with open(chemin, "wb") as f:
        f.truncate(taille_mio * MIO)
        if motif:            # ancien contenu de la cible : doit disparaître
            f.seek(0)
            f.write(motif * (MIO // len(motif)))
            f.seek(taille_mio * MIO - MIO)
            f.write(motif * (MIO // len(motif)))
    return chemin


def _table(chemin: Path) -> table.Table:
    d = ouvrir(str(chemin))
    try:
        return table.lire(d.lire, d.taille, 512)
    finally:
        d.fermer()


@pytest.fixture(scope="module")
def source_gpt(tmp_path_factory):
    dossier = tmp_path_factory.mktemp("gpt")
    temoins = fabrique.fichiers_temoins()
    disque, parts = fabrique.disque_gpt(dossier, fichiers=temoins)
    return disque, parts, temoins


def test_lecture_gpt(source_gpt):
    disque, parts, _ = source_gpt
    t = _table(disque)
    assert t.style == "gpt" and len(t.partitions) == 4
    assert [p.nature for p in t.triees()] == ["efi", "msr", "donnees", "recuperation"]
    assert table.partition_principale(t).numero == 3


def test_zones_occupees_ntfs(source_gpt):
    disque, parts, temoins = source_gpt
    deb, n = parts[3]
    d = ouvrir(str(disque))
    zones = ntfs.zones_occupees(lambda p, t: d.lire(deb * 512 + p, t), n * 512)
    d.fermer()
    copie = sum(l for _, l in zones)
    contenu = sum(len(v) for v in temoins.values())
    assert contenu < copie < n * 512 * 0.8, (copie, contenu, n * 512)


def test_clonage_gpt_vers_plus_grand(source_gpt, tmp_path):
    disque, parts, temoins = source_gpt
    cible = _vide(tmp_path / "cible.img", 2000, b"VIEUX!!!")
    plan = clonage.preparer_plan(disques.disque_image(str(disque)), disques.disque_image(str(cible)))
    assert plan.possible, plan.bloquants
    etapes = []
    bilan = clonage.cloner(plan, rappel=lambda **k: etapes.append(k["etape"]))
    assert "copie" in etapes and "verification" in etapes
    assert bilan.blocs_differents == 0 and bilan.octets_verifies == bilan.octets_copies
    assert bilan.octets_copies < (1200 - 300) * MIO          # pas tout le disque

    # table valide, identifiants conservés
    v = subprocess.run(["sgdisk", "-v", str(cible)], capture_output=True, text=True).stdout
    assert "No problems found" in v, v
    ts, tc = _table(disque), _table(cible)
    assert tc.guid_disque == ts.guid_disque
    for a, b in zip(ts.triees(), tc.triees()):
        assert (a.guid, a.type, a.nom, a.attributs, a.secteurs) == (b.guid, b.type, b.nom, b.attributs, b.secteurs)
    # C: au même endroit, récupération en fin de disque, espace libre entre les deux
    c_s, c_c = ts.triees()[2], tc.triees()[2]
    r_c = tc.triees()[3]
    assert c_c.debut == c_s.debut
    assert r_c.debut > c_c.fin + (700 * MIO // 512)
    assert r_c.fin - 1 <= table.dernier_utilisable(tc, tc.secteurs_disque)
    assert r_c.debut % 2048 == 0

    # volumes lisibles, fichiers identiques
    vol_c = fabrique.extraire(cible, c_c.debut, c_c.secteurs, tmp_path / "c.img")
    for nom, contenu in temoins.items():
        assert fabrique.lire_fichier_ntfs(vol_c, nom) == contenu, nom
    vol_r = fabrique.extraire(cible, r_c.debut, r_c.secteurs, tmp_path / "r.img")
    assert fabrique.lire_fichier_ntfs(vol_r, "winre.wim") == b"WINRE" * 300000
    # secteur d'amorçage de la récupération déplacée : « secteurs cachés » corrigés
    import struct
    premier = vol_r.read_bytes()[:512]
    assert struct.unpack_from("<I", premier, 0x1C)[0] == r_c.debut
    dernier = vol_r.read_bytes()[-512:]
    assert struct.unpack_from("<I", dernier, 0x1C)[0] == r_c.debut
    # EFI copiée à l'identique
    efi = ts.triees()[0]
    with open(disque, "rb") as a, open(cible, "rb") as b:
        a.seek(efi.debut * 512)
        b.seek(efi.debut * 512)
        assert a.read(efi.secteurs * 512) == b.read(efi.secteurs * 512)


def test_cible_trop_petite(source_gpt, tmp_path):
    disque, _, _ = source_gpt
    cible = _vide(tmp_path / "petite.img", 1000)
    plan = clonage.preparer_plan(disques.disque_image(str(disque)), disques.disque_image(str(cible)))
    assert not plan.possible
    assert plan.bloquants[0][0] == "table.cible_trop_petite"


def test_cible_de_meme_taille_sans_deplacement(source_gpt, tmp_path):
    disque, _, temoins = source_gpt
    cible = _vide(tmp_path / "meme.img", 1200)
    plan = clonage.preparer_plan(disques.disque_image(str(disque)), disques.disque_image(str(cible)))
    assert plan.possible and not any(t.deplacee for t in plan.travaux)
    clonage.cloner(plan)
    assert "No problems found" in subprocess.run(["sgdisk", "-v", str(cible)], capture_output=True, text=True).stdout


def test_secteurs_differents_refuses(source_gpt, tmp_path):
    disque, _, _ = source_gpt
    cible = disques.disque_image(str(_vide(tmp_path / "c4k.img", 2000)), taille_secteur=4096)
    plan = clonage.preparer_plan(disques.disque_image(str(disque)), cible)
    assert plan.bloquants and plan.bloquants[0][0] == "plan.secteurs"


def test_annulation_ne_laisse_aucune_table(source_gpt, tmp_path):
    disque, _, _ = source_gpt
    cible = _vide(tmp_path / "ann.img", 2000, b"VIEUX!!!")
    plan = clonage.preparer_plan(disques.disque_image(str(disque)), disques.disque_image(str(cible)))
    stop = threading.Event()

    def rappel(**k):
        if k["etape"] == "copie" and k["fait"] > 50 * MIO:
            stop.set()
    with pytest.raises(clonage.Annule):
        clonage.cloner(plan, rappel=rappel, annulation=stop)
    with open(cible, "rb") as f:
        debut = f.read(MIO)
        f.seek(-MIO, 2)
        fin = f.read(MIO)
    assert debut == b"\0" * MIO and fin == b"\0" * MIO     # ni ancienne ni nouvelle table
    with pytest.raises(table.ErreurTable):
        _table(cible)


def test_clonage_mbr(tmp_path):
    temoins = fabrique.fichiers_temoins(n=3)
    disque, parts = fabrique.disque_mbr(tmp_path, fichiers=temoins)
    cible = _vide(tmp_path / "cible.img", 1500)
    plan = clonage.preparer_plan(disques.disque_image(str(disque)), disques.disque_image(str(cible)))
    assert plan.possible
    clonage.cloner(plan)
    ts, tc = _table(disque), _table(cible)
    assert tc.style == "mbr" and tc.signature == 0x1A2B3C4D
    assert [p.active for p in tc.triees()] == [True, False, False]
    rec = tc.triees()[2]
    assert rec.fin > (1400 * MIO // 512) and rec.debut % 2048 == 0
    sortie = subprocess.run(["sfdisk", "-d", str(cible)], capture_output=True, text=True, check=True).stdout
    assert "label-id: 0x1a2b3c4d" in sortie
    c = tc.triees()[1]
    vol = fabrique.extraire(cible, c.debut, c.secteurs, tmp_path / "c.img")
    for nom, contenu in temoins.items():
        assert fabrique.lire_fichier_ntfs(vol, nom) == contenu


def test_volume_ntfs_marque_a_reparer(tmp_path):
    """Drapeau « dirty » de NTFS : signalé, comme ntfsclone/partclone le font."""
    temoins = fabrique.fichiers_temoins(n=1)
    disque, parts = fabrique.disque_gpt(tmp_path, fichiers=temoins)
    deb, n = parts[3]
    d = ouvrir(str(disque))
    vue = lambda p, t: d.lire(deb * 512 + p, t)  # noqa: E731
    assert not ntfs.volume_a_reparer(vue)
    d.fermer()
    # ntfs-3g pose le drapeau : on extrait le volume, on le marque, on le remet
    vol = fabrique.extraire(disque, deb, n, tmp_path / "c.img")
    subprocess.run(["ntfsfix", "-d", str(vol)], capture_output=True)          # remet à zéro d'abord
    import struct
    brut = bytearray(vol.read_bytes())
    s = bytes(brut[:512])
    oct_sect, cluster, lcn, taille_rec = ntfs._geometrie(s)
    rec_pos = lcn * cluster + 3 * taille_rec
    rec = bytearray(brut[rec_pos:rec_pos + taille_rec])
    ntfs._appliquer_correctifs(rec, oct_sect)
    pos = struct.unpack_from("<H", rec, 0x14)[0]
    while True:
        typ, lg = struct.unpack_from("<II", rec, pos)
        if typ == 0x70:
            off = struct.unpack_from("<H", rec, pos + 0x14)[0]
            fl_pos = pos + off + 0x0A
            break
        pos += lg
    # écrire le drapeau dans l'enregistrement brut (hors fin de secteur : pas de fixup à refaire)
    assert fl_pos % oct_sect < oct_sect - 2
    brut[rec_pos + fl_pos] |= 1
    with open(disque, "r+b") as f:
        f.seek(deb * 512 + rec_pos + fl_pos)
        f.write(bytes([brut[rec_pos + fl_pos]]))
    d = ouvrir(str(disque))
    assert ntfs.volume_a_reparer(lambda p, t: d.lire(deb * 512 + p, t))
    d.fermer()
    cible = _vide(tmp_path / "cible.img", 2000)
    plan = clonage.preparer_plan(disques.disque_image(str(disque)), disques.disque_image(str(cible)))
    assert any(c == "plan.ntfs_sale" for c, _ in plan.avertissements)
