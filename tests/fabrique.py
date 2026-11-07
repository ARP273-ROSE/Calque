"""Fabrique de disques image « façon Windows » pour les essais.

GPT : EFI (FAT32) · MSR · C: (NTFS, fichiers dedans) · récupération (NTFS) en
fin de disque — la disposition d'une installation de Windows 10/11.
MBR : réservé au système (NTFS, actif) · C: · récupération.

Il faut sgdisk, mkntfs, ntfscp, mkfs.vfat (gdisk, ntfs-3g, dosfstools).
"""
from __future__ import annotations

import os
import random
import shutil
import subprocess
from pathlib import Path

MIO = 1024 * 1024
OUTILS = ("sgdisk", "mkntfs", "ntfscp", "ntfscat", "mkfs.vfat", "sfdisk")


def outils_presents() -> bool:
    return all(shutil.which(o) for o in OUTILS)


def _run(*args):
    subprocess.run(args, check=True, capture_output=True)


def _ntfs(chemin: Path, taille: int, etiquette: str, fichiers: dict[str, bytes], debut_secteur: int):
    with open(chemin, "wb") as f:
        f.truncate(taille)
    _run("mkntfs", "-F", "-Q", "-q", "-L", etiquette, "-p", str(debut_secteur), "-H", "255", "-S", "63",
         str(chemin))
    dossier = chemin.parent / (chemin.name + ".src")
    dossier.mkdir(exist_ok=True)
    for nom, contenu in fichiers.items():
        (dossier / nom).write_bytes(contenu)
        _run("ntfscp", "-f", "-q", str(chemin), str(dossier / nom), nom)
    shutil.rmtree(dossier)


def _poser(disque: Path, image: Path, debut_secteur: int):
    with open(disque, "r+b") as d, open(image, "rb") as i:
        d.seek(debut_secteur * 512)
        shutil.copyfileobj(i, d, 4 * MIO)
    image.unlink()


def fichiers_temoins(graine: int = 7, n: int = 6, taille: int = 9 * MIO) -> dict[str, bytes]:
    r = random.Random(graine)
    return {f"temoin{i}.bin": r.randbytes(taille + i * 12345) for i in range(n)}


def disque_gpt(dossier: Path, taille_mio: int = 1200, fichiers=None) -> tuple[Path, dict]:
    """Rend (chemin, {nom: (début secteur, secteurs)})."""
    fichiers = fichiers if fichiers is not None else fichiers_temoins()
    disque = dossier / "source-gpt.img"
    with open(disque, "wb") as f:
        f.truncate(taille_mio * MIO)
    _run("sgdisk", "-o", "-a", "2048",
         "-n", "1:2048:+100M", "-t", "1:ef00", "-c", "1:EFI system partition",
         "-n", "2:0:+16M", "-t", "2:0c01", "-c", "2:Microsoft reserved partition",
         "-n", "3:0:-300M", "-t", "3:0700", "-c", "3:Basic data partition",
         "-n", "4:0:0", "-t", "4:2700", "-c", "4:Basic data partition",
         "-A", "4:set:0", str(disque))
    parts = {}
    sortie = subprocess.run(["sgdisk", "-p", str(disque)], capture_output=True, text=True).stdout
    for ligne in sortie.splitlines():
        champs = ligne.split()
        if champs and champs[0].isdigit():
            n, deb, fin = int(champs[0]), int(champs[1]), int(champs[2])
            parts[n] = (deb, fin - deb + 1)
    efi = dossier / "efi.img"
    with open(efi, "wb") as f:
        f.truncate(parts[1][1] * 512)
    _run("mkfs.vfat", "-F", "32", "-n", "SYSTEM", "-h", str(parts[1][0]), str(efi))
    _poser(disque, efi, parts[1][0])
    c = dossier / "c.img"
    _ntfs(c, parts[3][1] * 512, "Windows", fichiers, parts[3][0])
    _poser(disque, c, parts[3][0])
    rec = dossier / "rec.img"
    _ntfs(rec, parts[4][1] * 512, "Recovery", {"winre.wim": b"WINRE" * 300000}, parts[4][0])
    _poser(disque, rec, parts[4][0])
    return disque, parts


def disque_mbr(dossier: Path, taille_mio: int = 900, fichiers=None) -> tuple[Path, dict]:
    fichiers = fichiers if fichiers is not None else fichiers_temoins(n=3)
    disque = dossier / "source-mbr.img"
    with open(disque, "wb") as f:
        f.truncate(taille_mio * MIO)
    secteurs = taille_mio * MIO // 512
    sys_res = (2048, 100 * 2048)
    rec_n = 200 * 2048
    c = (sys_res[0] + sys_res[1], secteurs - rec_n - (sys_res[0] + sys_res[1]) - 2048)
    rec = (c[0] + c[1], rec_n)
    script = (f"label: dos\nlabel-id: 0x1a2b3c4d\n"
              f"start={sys_res[0]}, size={sys_res[1]}, type=7, bootable\n"
              f"start={c[0]}, size={c[1]}, type=7\n"
              f"start={rec[0]}, size={rec[1]}, type=27\n")
    subprocess.run(["sfdisk", "-q", str(disque)], input=script.encode(), check=True, capture_output=True)
    parts = {1: sys_res, 2: c, 3: rec}
    for n, (deb, nb) in parts.items():
        img = dossier / f"p{n}.img"
        _ntfs(img, nb * 512, ["Reserve", "Windows", "Recovery"][n - 1],
              fichiers if n == 2 else {"bootmgr": os.urandom(400000)}, deb)
        _poser(disque, img, deb)
    return disque, parts


def extraire(disque: Path, debut: int, secteurs: int, sortie: Path) -> Path:
    with open(disque, "rb") as d, open(sortie, "wb") as o:
        d.seek(debut * 512)
        reste = secteurs * 512
        while reste:
            b = d.read(min(4 * MIO, reste))
            o.write(b)
            reste -= len(b)
    return sortie


def lire_fichier_ntfs(volume: Path, nom: str) -> bytes:
    return subprocess.run(["ntfscat", str(volume), nom], check=True, capture_output=True).stdout
