"""Systèmes de fichiers : ce qu'il faut copier, et les retouches d'un volume déplacé.

NTFS : seuls les clusters occupés sont copiés, lus dans la carte d'allocation
du volume ($Bitmap, enregistrement 6 de la MFT). Sur un disque système rempli
à moitié, la copie dure moitié moins.

La carte est lue dans le CLICHÉ du volume (Windows) : elle est donc cohérente
avec les données copiées, même si Windows écrit pendant le clonage.

Ce module ne fait que lire des octets : `lire(position, taille)`.
"""
from __future__ import annotations

import struct

from .table import MIO


class ErreurNTFS(Exception):
    pass


def nature(premier_secteur: bytes) -> str:
    """Nature d'un volume d'après son premier secteur."""
    s = premier_secteur
    if len(s) < 512:
        return "inconnu"
    if s[3:11] == b"NTFS    ":
        return "ntfs"
    if s[3:11] == b"-FVE-FS-":
        return "bitlocker"
    if s[3:11] == b"EXFAT   ":
        return "exfat"
    if s[3:11] == b"ReFS\0\0\0\0":
        return "refs"
    if s[82:90] == b"FAT32   ":
        return "fat32"
    if s[54:62] in (b"FAT16   ", b"FAT12   ", b"FAT     "):
        return "fat"
    return "inconnu"


def _taille_cluster(s: bytes) -> tuple[int, int]:
    octets_secteur = struct.unpack_from("<H", s, 0x0B)[0]
    spc = s[0x0D]
    secteurs_cluster = 1 << (256 - spc) if spc > 0x80 else spc
    return octets_secteur, octets_secteur * secteurs_cluster


def _appliquer_correctifs(rec: bytearray, octets_secteur: int) -> None:
    """Séquence de mise à jour (fixup) d'un enregistrement de la MFT."""
    pos, n = struct.unpack_from("<HH", rec, 4)
    if n == 0:
        return
    usn = rec[pos:pos + 2]
    for i in range(1, n):
        fin = i * octets_secteur - 2
        if fin + 2 > len(rec):
            break
        if rec[fin:fin + 2] != usn:
            raise ErreurNTFS("enregistrement MFT abîmé (séquence de mise à jour)")
        rec[fin:fin + 2] = rec[pos + 2 * i:pos + 2 * i + 2]


def _suites(donnees: bytes, pos: int) -> list[tuple[int, int]]:
    """Liste des suites (LCN, longueur en clusters) d'un attribut non résident."""
    suites, lcn = [], 0
    while pos < len(donnees) and donnees[pos] != 0:
        tete = donnees[pos]
        nl, no = tete & 0x0F, tete >> 4
        pos += 1
        longueur = int.from_bytes(donnees[pos:pos + nl], "little")
        pos += nl
        if no:
            delta = int.from_bytes(donnees[pos:pos + no], "little", signed=True)
            lcn += delta
            suites.append((lcn, longueur))
        else:
            suites.append((-1, longueur))     # zone creuse
        pos += no
    return suites


def carte_ntfs(lire) -> tuple[int, bytes, int]:
    """Rend (taille d'un cluster, carte d'allocation, nombre de clusters)."""
    s = lire(0, 512)
    if nature(s) != "ntfs":
        raise ErreurNTFS("pas un volume NTFS")
    octets_secteur, cluster = _taille_cluster(s)
    total_secteurs = struct.unpack_from("<Q", s, 0x28)[0]
    lcn_mft = struct.unpack_from("<Q", s, 0x30)[0]
    cpr = struct.unpack_from("<b", s, 0x40)[0]
    taille_rec = (1 << -cpr) if cpr < 0 else cpr * cluster
    nb_clusters = total_secteurs * octets_secteur // cluster
    rec = bytearray(lire(lcn_mft * cluster + 6 * taille_rec, taille_rec))
    if rec[:4] != b"FILE":
        raise ErreurNTFS("enregistrement $Bitmap introuvable")
    _appliquer_correctifs(rec, octets_secteur)
    pos = struct.unpack_from("<H", rec, 0x14)[0]
    while pos + 8 <= len(rec):
        typ, long_attr = struct.unpack_from("<II", rec, pos)
        if typ == 0xFFFFFFFF or long_attr == 0:
            break
        if typ == 0x80 and rec[pos + 9] == 0:          # $DATA sans nom
            if rec[pos + 8] == 0:                       # résident (minuscule volume)
                lg, off = struct.unpack_from("<IH", rec, pos + 0x10)
                return cluster, bytes(rec[pos + off:pos + off + lg]), nb_clusters
            off_suites = struct.unpack_from("<H", rec, pos + 0x20)[0]
            taille_reelle = struct.unpack_from("<Q", rec, pos + 0x30)[0]
            morceaux = []
            for lcn, n in _suites(bytes(rec[pos:pos + long_attr]), off_suites):
                if lcn < 0:
                    morceaux.append(b"\0" * (n * cluster))
                else:
                    morceaux.append(lire(lcn * cluster, n * cluster))
            return cluster, b"".join(morceaux)[:taille_reelle], nb_clusters
        pos += long_attr
    raise ErreurNTFS("attribut $DATA de $Bitmap introuvable")


def zones_occupees(lire, taille_volume: int, bloc: int = MIO) -> list[tuple[int, int]]:
    """Zones (début, longueur) d'un volume NTFS à copier, par blocs de `bloc`.

    Un bloc est copié dès qu'un seul de ses clusters est occupé. Le premier et
    le dernier bloc le sont toujours : secteur d'amorçage et sa copie de secours,
    qui vit dans le dernier secteur de la partition, hors des clusters.
    """
    cluster, carte, nb_clusters = carte_ntfs(lire)
    par_bloc = max(1, bloc // cluster)
    nb_blocs = -(-taille_volume // bloc)
    occupes = bytearray(nb_blocs)
    carte = carte[:-(-nb_clusters // 8)]
    if par_bloc % 8 == 0:
        # cas courant (clusters de 4 Kio : 32 octets de carte par Mio) : une
        # comparaison de tranche par bloc, rapide même pour 2 To
        pas = par_bloc // 8
        for b in range(min(nb_blocs, -(-len(carte) // pas))):
            if carte[b * pas:(b + 1) * pas].strip(b"\0"):
                occupes[b] = 1
    else:
        for i, octet in enumerate(carte):
            if octet:
                for j in range(8):
                    if octet >> j & 1:
                        b = (i * 8 + j) // par_bloc
                        if b < nb_blocs:
                            occupes[b] = 1
    occupes[0] = 1
    occupes[-1] = 1
    zones, debut = [], None
    for b, o in enumerate(occupes):
        if o and debut is None:
            debut = b
        elif not o and debut is not None:
            zones.append((debut * bloc, (b - debut) * bloc))
            debut = None
    if debut is not None:
        zones.append((debut * bloc, (nb_blocs - debut) * bloc))
    # le dernier bloc peut dépasser la fin du volume
    d, n = zones[-1]
    zones[-1] = (d, min(n, taille_volume - d))
    return zones


def retouches_deplacement(lire, taille_volume: int, ss: int, nouveau_debut: int) -> list[tuple[int, bytes]]:
    """Secteurs d'amorçage à corriger quand un volume change de place.

    NTFS et FAT notent dans leur secteur d'amorçage le nombre de « secteurs
    cachés » qui les précèdent (= le début de la partition). Windows ne s'en sert
    pas pour un volume de données, mais le chargeur d'un volume amorçable, si :
    on le corrige, ainsi que la copie de secours. Rend [(position dans le volume, secteur)].
    """
    s = lire(0, ss)
    n = nature(s)
    if n not in ("ntfs", "fat32", "fat"):
        return []
    valeur = struct.pack("<I", nouveau_debut & 0xFFFFFFFF)
    retouches = []

    def corrige(position: int, secteur: bytes) -> None:
        if nature(secteur) == n and secteur[0x1C:0x20] != valeur:
            neuf = bytearray(secteur)
            neuf[0x1C:0x20] = valeur
            retouches.append((position, bytes(neuf)))

    corrige(0, s)
    if n == "ntfs":
        pos = (taille_volume // ss - 1) * ss
        corrige(pos, lire(pos, ss))
    elif n == "fat32":
        secours = struct.unpack_from("<H", s, 0x32)[0]
        if 0 < secours < 32:
            corrige(secours * ss, lire(secours * ss, ss))
    return retouches


def _geometrie(s: bytes) -> tuple[int, int, int, int]:
    octets_secteur, cluster = _taille_cluster(s)
    lcn_mft = struct.unpack_from("<Q", s, 0x30)[0]
    cpr = struct.unpack_from("<b", s, 0x40)[0]
    taille_rec = (1 << -cpr) if cpr < 0 else cpr * cluster
    return octets_secteur, cluster, lcn_mft, taille_rec


def volume_a_reparer(lire) -> bool:
    """Le volume est-il marqué « à vérifier » (drapeau VOLUME_IS_DIRTY) ?

    Même contrôle que ntfsclone et partclone (outils libres), qui refusent de
    copier un tel volume sans --force : Windows y a vu une incohérence et
    lancera chkdsk au prochain démarrage. Copier l'incohérence ne la répare
    pas ; mieux vaut la réparer d'abord (chkdsk C: /f).
    Lit l'attribut $VOLUME_INFORMATION (0x70) de l'enregistrement 3 ($Volume).
    """
    s = lire(0, 512)
    if nature(s) != "ntfs":
        return False
    octets_secteur, cluster, lcn_mft, taille_rec = _geometrie(s)
    rec = bytearray(lire(lcn_mft * cluster + 3 * taille_rec, taille_rec))
    if rec[:4] != b"FILE":
        return False
    _appliquer_correctifs(rec, octets_secteur)
    pos = struct.unpack_from("<H", rec, 0x14)[0]
    while pos + 8 <= len(rec):
        typ, long_attr = struct.unpack_from("<II", rec, pos)
        if typ == 0xFFFFFFFF or long_attr == 0:
            break
        if typ == 0x70 and rec[pos + 8] == 0:
            off = struct.unpack_from("<H", rec, pos + 0x14)[0]
            drapeaux = struct.unpack_from("<H", rec, pos + off + 0x0A)[0]
            return bool(drapeaux & 0x0001)
        pos += long_attr
    return False
