"""Tables de partitions GPT et MBR : lecture, contrôle, réécriture.

Tout est fait ici en Python pur, à partir des secteurs bruts, plutôt qu'en
demandant au système : la même lecture sert sous Windows, sous Linux et sur un
fichier image (tests), et la table écrite sur le disque cible est exactement
celle que l'on a calculée — identifiants compris.

Les identifiants sont CONSERVÉS (GUID du disque et des partitions en GPT,
signature du disque en MBR) : le gestionnaire de démarrage de Windows (BCD)
désigne la partition système par ces identifiants. Un clone qui en change ne
démarre pas — c'est l'une des causes classiques d'un clonage « réussi » qui
n'amorce pas.
"""
from __future__ import annotations

import struct
import uuid
import zlib
from dataclasses import dataclass, field, replace

MIO = 1024 * 1024
SIGNATURE_GPT = b"EFI PART"

# Types GPT connus (GUID en forme texte, minuscules)
GPT_EFI = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
GPT_MSR = "e3c9e316-0b5c-4db8-817d-f92df00215ae"
GPT_DONNEES_MS = "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7"
GPT_RECUPERATION = "de94bba4-06d1-4d40-a16a-bfd50179d6ac"
GPT_LDM_META = "5808c8aa-7e8f-42e0-85d2-e1e90434cfb3"
GPT_LDM_DONNEES = "af9b60a0-1431-4f62-bc68-3311714a69ad"
GPT_ESPACES = "e75caf8f-f680-4cee-afa3-b001e56efc2d"   # Espaces de stockage
GPT_LINUX = "0fc63daf-8483-4772-8e79-3d69d8477de4"

NOMS_TYPES_GPT = {
    GPT_EFI: "efi", GPT_MSR: "msr", GPT_DONNEES_MS: "donnees",
    GPT_RECUPERATION: "recuperation", GPT_LINUX: "linux",
    GPT_LDM_META: "ldm", GPT_LDM_DONNEES: "ldm", GPT_ESPACES: "espaces",
}
NOMS_TYPES_MBR = {0x07: "donnees", 0x0B: "fat32", 0x0C: "fat32", 0x27: "recuperation",
                  0xEF: "efi", 0x83: "linux", 0x42: "ldm", 0x05: "etendue",
                  0x0F: "etendue", 0x85: "etendue", 0xEE: "protection"}


class ErreurTable(Exception):
    """Table de partitions illisible, incohérente ou non prise en charge."""

    def __init__(self, cle: str, **champs):
        super().__init__(cle)
        self.cle, self.champs = cle, champs


@dataclass
class Partition:
    numero: int                 # rang dans la table (1…)
    debut: int                  # premier secteur (LBA)
    secteurs: int               # nombre de secteurs
    type: str                   # GUID (GPT) ou « 0x07 » (MBR)
    nature: str                 # efi, msr, donnees, recuperation, ldm…
    guid: str = ""              # GPT : identifiant unique
    attributs: int = 0          # GPT
    nom: str = ""               # GPT
    active: bool = False        # MBR : partition amorçable
    brut: bytes = b""           # entrée d'origine (GPT : 128 octets…)
    index: int = 0              # GPT : position dans le tableau d'entrées

    @property
    def fin(self) -> int:       # premier secteur APRÈS la partition
        return self.debut + self.secteurs


@dataclass
class Table:
    style: str                  # "gpt" ou "mbr"
    taille_secteur: int
    secteurs_disque: int
    partitions: list[Partition] = field(default_factory=list)
    guid_disque: str = ""       # GPT
    signature: int = 0          # MBR (aussi lue dans le MBR protecteur GPT)
    nb_entrees: int = 128       # GPT
    taille_entree: int = 128    # GPT
    code_amorce: bytes = b""    # 440 premiers octets du secteur 0

    def triees(self) -> list[Partition]:
        return sorted(self.partitions, key=lambda p: p.debut)


# ---------------------------------------------------------------- lecture

def _guid_texte(b: bytes) -> str:
    return str(uuid.UUID(bytes_le=bytes(b)))


def _guid_octets(s: str) -> bytes:
    return uuid.UUID(s).bytes_le


def lire(lire_octets, taille_disque: int, taille_secteur: int) -> Table:
    """Lit la table d'un disque. `lire_octets(position, taille)` rend des octets."""
    if taille_secteur not in (512, 4096):
        raise ErreurTable("table.secteur_inconnu", taille=taille_secteur)
    ss = taille_secteur
    s0 = lire_octets(0, ss)
    if len(s0) < 512 or s0[510:512] != b"\x55\xaa":
        raise ErreurTable("table.vide")
    entrees = [s0[446 + 16 * i: 462 + 16 * i] for i in range(4)]
    types = [e[4] for e in entrees]
    signature = struct.unpack_from("<I", s0, 440)[0]
    if 0xEE in types:
        return _lire_gpt(lire_octets, taille_disque, ss, s0, signature)
    return _lire_mbr(s0, taille_disque, ss, signature)


def _lire_mbr(s0: bytes, taille_disque: int, ss: int, signature: int) -> Table:
    t = Table("mbr", ss, taille_disque // ss, signature=signature, code_amorce=s0[:440])
    for i in range(4):
        e = s0[446 + 16 * i: 462 + 16 * i]
        typ = e[4]
        debut, n = struct.unpack_from("<II", e, 8)
        if typ == 0 or n == 0:
            continue
        nature = NOMS_TYPES_MBR.get(typ, "autre")
        if nature == "etendue":
            raise ErreurTable("table.etendue")
        t.partitions.append(Partition(i + 1, debut, n, f"0x{typ:02X}", nature,
                                      active=e[0] == 0x80, brut=bytes(e)))
    _controler(t)
    return t


def _lire_gpt(lire_octets, taille_disque, ss, s0, signature) -> Table:
    tete = lire_octets(ss, ss)
    if tete[:8] != SIGNATURE_GPT:
        raise ErreurTable("table.gpt_entete")
    taille_tete = struct.unpack_from("<I", tete, 12)[0]
    crc = struct.unpack_from("<I", tete, 16)[0]
    copie = bytearray(tete[:taille_tete])
    copie[16:20] = b"\0\0\0\0"
    if zlib.crc32(bytes(copie)) & 0xFFFFFFFF != crc:
        raise ErreurTable("table.gpt_crc")
    (lba_entrees, nb, taille_e, crc_e) = struct.unpack_from("<QIII", tete, 72)
    guid_disque = _guid_texte(tete[56:72])
    tableau = lire_octets(lba_entrees * ss, nb * taille_e)
    if zlib.crc32(tableau) & 0xFFFFFFFF != crc_e:
        raise ErreurTable("table.gpt_crc")
    t = Table("gpt", ss, taille_disque // ss, guid_disque=guid_disque, signature=signature,
              nb_entrees=nb, taille_entree=taille_e, code_amorce=s0[:440])
    rang = 0
    for i in range(nb):
        e = tableau[i * taille_e:(i + 1) * taille_e]
        if e[:16] == b"\0" * 16:
            continue
        rang += 1
        typ = _guid_texte(e[:16])
        premier, dernier, attr = struct.unpack_from("<QQQ", e, 32)
        nom = e[56:128].decode("utf-16-le", "replace").split("\0")[0]
        t.partitions.append(Partition(
            rang, premier, dernier - premier + 1, typ, NOMS_TYPES_GPT.get(typ, "autre"),
            guid=_guid_texte(e[16:32]), attributs=attr, nom=nom, brut=bytes(e), index=i))
    _controler(t)
    return t


def _controler(t: Table) -> None:
    precedente = None
    for p in t.triees():
        if p.fin > t.secteurs_disque:
            raise ErreurTable("table.hors_disque", numero=p.numero)
        if precedente and p.debut < precedente.fin:
            raise ErreurTable("table.chevauchement", numero=p.numero)
        precedente = p
    if any(p.nature in ("ldm", "espaces") for p in t.partitions):
        raise ErreurTable("table.dynamique")


# ---------------------------------------------------------------- plan

def aligner(secteur: int, ss: int, haut: bool = True) -> int:
    pas = MIO // ss
    return -(-secteur // pas) * pas if haut else (secteur // pas) * pas


def partition_principale(t: Table) -> Partition | None:
    """La partition qui recevra l'espace gagné : la plus grande partition de
    données (C: sur un disque Windows)."""
    candidates = [p for p in t.partitions if p.nature in ("donnees", "linux", "autre", "fat32")]
    return max(candidates, key=lambda p: p.secteurs) if candidates else None


def premier_utilisable(t: Table) -> int:
    if t.style == "mbr":
        return 1
    return 2 + (t.nb_entrees * t.taille_entree + t.taille_secteur - 1) // t.taille_secteur


def dernier_utilisable(t: Table, secteurs_disque: int) -> int:
    """Dernier secteur utilisable (inclus)."""
    if t.style == "mbr":
        return min(secteurs_disque, 0xFFFFFFFF) - 1
    return secteurs_disque - 1 - (premier_utilisable(t) - 1)


def transposer(t: Table, secteurs_cible: int, deplacer_fin: bool = True) -> tuple[Table, dict[int, int]]:
    """Table du disque cible.

    Les partitions situées APRÈS la partition principale (récupération de
    Windows, le plus souvent) sont reportées en fin du disque cible, dans le
    même ordre et avec les mêmes écarts : l'espace gagné se retrouve juste
    derrière C:, et Windows peut l'agrandir d'un clic (« Étendre le volume »).
    Laissée en place, la partition de récupération bloquerait l'agrandissement.

    Rend la nouvelle table et la correspondance {numéro: nouveau début}.
    """
    if secteurs_cible < 34 * 2:
        raise ErreurTable("table.cible_trop_petite", besoin=0)
    principale = partition_principale(t)
    triees = t.triees()
    apres = [p for p in triees if principale and p.debut > principale.debut] if deplacer_fin else []
    dernier = dernier_utilisable(t, secteurs_cible)
    nouveaux: dict[int, int] = {p.numero: p.debut for p in triees}
    if apres:
        # bloc des partitions de fin, collé à la fin du disque (aligné sur 1 Mio)
        debut_bloc, fin_bloc = apres[0].debut, apres[-1].fin
        nouveau_debut_bloc = aligner(dernier + 1 - (fin_bloc - debut_bloc), t.taille_secteur, haut=False)
        decalage = nouveau_debut_bloc - debut_bloc
        if decalage > 0:
            for p in apres:
                nouveaux[p.numero] = p.debut + decalage
    besoin = max(nouveaux[p.numero] + p.secteurs for p in triees) if triees else 0
    if besoin - 1 > dernier:
        raise ErreurTable("table.cible_trop_petite",
                          besoin=(besoin + premier_utilisable(t)) * t.taille_secteur)
    neuve = replace(t, secteurs_disque=secteurs_cible,
                    partitions=[replace(p, debut=nouveaux[p.numero]) for p in t.partitions])
    _controler(neuve)
    return neuve, nouveaux


# ---------------------------------------------------------------- écriture

def _chs(lba: int) -> bytes:
    """Adresse CHS fictive (255 têtes, 63 secteurs) ; au-delà de 8 Go, la valeur
    conventionnelle « maximale » que Windows écrit lui-même."""
    if lba >= 1024 * 255 * 63:
        return b"\xfe\xff\xff"
    c, reste = divmod(lba, 255 * 63)
    h, s = divmod(reste, 63)
    s += 1
    return bytes([h, ((c >> 2) & 0xC0) | s, c & 0xFF])


def secteurs_mbr(t: Table) -> bytes:
    """Secteur 0 d'un disque MBR (code d'amorçage d'origine conservé)."""
    s = bytearray(t.taille_secteur)
    s[:440] = (t.code_amorce or b"").ljust(440, b"\0")[:440]
    struct.pack_into("<I", s, 440, t.signature)
    for p in t.partitions:
        i = p.numero - 1
        typ = int(p.type, 16)
        e = bytes([0x80 if p.active else 0]) + _chs(p.debut) + bytes([typ]) + \
            _chs(p.fin - 1) + struct.pack("<II", p.debut, p.secteurs)
        s[446 + 16 * i: 462 + 16 * i] = e
    s[510:512] = b"\x55\xaa"
    return bytes(s)


def zones_gpt(t: Table) -> list[tuple[int, bytes]]:
    """Ce qu'il faut écrire pour une GPT complète : [(position octets, données)].

    MBR protecteur, en-tête principal et son tableau d'entrées, tableau et
    en-tête de secours en fin de disque.
    """
    ss = t.taille_secteur
    n = t.secteurs_disque
    tableau = bytearray(t.nb_entrees * t.taille_entree)
    for p in t.partitions:
        e = bytearray(p.brut.ljust(t.taille_entree, b"\0")[:t.taille_entree]) if p.brut \
            else bytearray(t.taille_entree)
        e[0:16] = _guid_octets(p.type)
        e[16:32] = _guid_octets(p.guid) if p.guid else uuid.uuid4().bytes_le
        struct.pack_into("<QQQ", e, 32, p.debut, p.fin - 1, p.attributs)
        if not p.brut:
            nom = p.nom.encode("utf-16-le")[:72]
            e[56:128] = nom.ljust(72, b"\0")
        tableau[p.index * t.taille_entree:(p.index + 1) * t.taille_entree] = e
    tableau = bytes(tableau)
    crc_tableau = zlib.crc32(tableau) & 0xFFFFFFFF
    secteurs_tableau = (len(tableau) + ss - 1) // ss
    premier = 2 + secteurs_tableau
    dernier = n - 2 - secteurs_tableau
    lba_tableau_secours = n - 1 - secteurs_tableau

    def entete(courant: int, autre: int, lba_entrees: int) -> bytes:
        h = bytearray(ss)
        struct.pack_into("<8sIII4xQQQQ16sQIII", h, 0, SIGNATURE_GPT, 0x00010000, 92, 0,
                         courant, autre, premier, dernier, _guid_octets(t.guid_disque),
                         lba_entrees, t.nb_entrees, t.taille_entree, crc_tableau)
        struct.pack_into("<I", h, 16, zlib.crc32(bytes(h[:92])) & 0xFFFFFFFF)
        return bytes(h)

    pmbr = bytearray(ss)
    pmbr[:440] = (t.code_amorce or b"").ljust(440, b"\0")[:440]
    struct.pack_into("<I", pmbr, 440, t.signature)
    pmbr[446:462] = b"\x00\x00\x02\x00" + bytes([0xEE]) + b"\xff\xff\xff" + \
        struct.pack("<II", 1, min(n - 1, 0xFFFFFFFF))
    pmbr[510:512] = b"\x55\xaa"
    rembourre = tableau.ljust(secteurs_tableau * ss, b"\0")
    return [
        (0, bytes(pmbr)),
        (ss, entete(1, n - 1, 2)),
        (2 * ss, rembourre),
        (lba_tableau_secours * ss, rembourre),
        ((n - 1) * ss, entete(n - 1, 1, lba_tableau_secours)),
    ]


def zones_table(t: Table) -> list[tuple[int, bytes]]:
    if t.style == "gpt":
        return zones_gpt(t)
    return [(0, secteurs_mbr(t))]


def zones_effacement(secteurs_disque: int, ss: int) -> list[tuple[int, int]]:
    """Début et fin du disque cible à effacer AVANT la copie : aucune ancienne
    table ne doit survivre (une GPT de secours oubliée en fin de disque suffit
    à faire « réparer » le disque par un outil trop zélé)."""
    debut = (0, MIO)
    fin_debut = max(0, secteurs_disque * ss - MIO)
    return [debut, (fin_debut, secteurs_disque * ss - fin_debut)]
