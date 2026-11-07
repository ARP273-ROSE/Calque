"""Inventaire des disques, préparation de la cible, clichés de volumes.

Windows : Get-Disk / Get-Partition / Get-Volume (PowerShell, sortie JSON),
clichés instantanés VSS (Win32_ShadowCopy) pour copier un volume EN SERVICE
— le disque système — dans un état cohérent.
Linux : lsblk ; pas de cliché : un volume monté en écriture est refusé (cloner
depuis un système démarré sur clé USB).
Fichiers image (`--image`) : pour les essais.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field

from .peripherique import ErreurAcces, Fenetre, ouvrir


@dataclass
class Volume:
    debut: int                  # octets depuis le début du disque
    taille: int
    nom: str = ""               # « C: », « /mnt/x »
    chemin: str = ""            # \\?\Volume{…}\ (Windows)
    systeme_fichiers: str = ""
    lecture_seule: bool = False


@dataclass
class Disque:
    chemin: str                 # \\.\PhysicalDrive1, /dev/sdb, image.img
    numero: int | None
    modele: str
    taille: int
    taille_secteur: int = 512
    secteur_physique: int = 512
    bus: str = ""               # USB, NVMe, SATA, image…
    systeme: bool = False       # porte le système en cours ou son démarrage
    hors_ligne: bool = False
    lecture_seule: bool = False
    serie: str = ""
    sante: str = ""             # Windows : Healthy, Warning, Unhealthy…
    volumes: list[Volume] = field(default_factory=list)

    def libelle(self) -> str:
        num = f"{self.numero} · " if self.numero is not None else ""
        bus = f" · {self.bus}" if self.bus else ""
        return f"{num}{self.modele or self.chemin} · {octets_lisibles(self.taille)}{bus}"

    def identite(self) -> tuple:
        return (self.chemin, self.taille, self.modele, self.serie)

    def empreinte(self) -> dict:
        """Ce qui reconnaît le disque même s'il change de numéro (dock rebranché)."""
        return {"taille": self.taille, "modele": self.modele, "serie": self.serie,
                "secteur": self.taille_secteur, "chemin": self.chemin}

    def correspond(self, e: dict) -> bool:
        return (self.taille == e.get("taille") and self.modele == e.get("modele")
                and self.serie == e.get("serie") and self.taille_secteur == e.get("secteur"))


def octets_lisibles(n: int) -> str:
    """Tailles comme les fabricants les annoncent (Go = 10⁹), dans la langue de l'interface."""
    from .i18n import langue
    fr = langue() == "fr"
    unites = ("To", "Go", "Mo", "ko") if fr else ("TB", "GB", "MB", "kB")
    for unite, pas in zip(unites, (10**12, 10**9, 10**6, 10**3)):
        if n >= pas:
            v = n / pas
            texte = f"{v:.0f}" if v >= 100 else f"{v:.1f}"
            return (texte.replace(".", ",") if fr else texte) + " " + unite
    return f"{n} o" if fr else f"{n} B"


# ------------------------------------------------------------ Windows

BUS_WINDOWS = {1: "SCSI", 2: "ATAPI", 3: "ATA", 4: "1394", 5: "SSA", 6: "Fibre", 7: "USB",
               8: "RAID", 9: "iSCSI", 10: "SAS", 11: "SATA", 12: "SD", 13: "MMC",
               14: "Virtual", 15: "VHD", 16: "Storage Spaces", 17: "NVMe"}


def powershell(script: str, delai: float = 120) -> str:
    """Lance un script PowerShell et rend sa sortie (UTF-8)."""
    prefixe = "[Console]::OutputEncoding=[Text.Encoding]::UTF8;$ErrorActionPreference='Stop';"
    r = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", prefixe + script],
        capture_output=True, timeout=delai,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    sortie = r.stdout.decode("utf-8", "replace")
    if r.returncode != 0:
        raise ErreurAcces("acces.powershell", detail=(r.stderr.decode("utf-8", "replace") or sortie).strip()[-1500:])
    return sortie


SCRIPT_INVENTAIRE = r"""
$d = @(Get-Disk | Select-Object Number,FriendlyName,SerialNumber,Size,BusType,PartitionStyle,IsBoot,IsSystem,IsOffline,IsReadOnly,LogicalSectorSize,PhysicalSectorSize)
$p = @(Get-Partition | Select-Object DiskNumber,PartitionNumber,Offset,Size,@{n='Lettre';e={[string]$_.DriveLetter}},AccessPaths)
$v = @(Get-Volume | Select-Object UniqueId,FileSystem)
$h = @(); try { $h = @(Get-PhysicalDisk | Select-Object DeviceId,@{n='Sante';e={[string]$_.HealthStatus}}) } catch {}
@{disques=$d; partitions=$p; volumes=$v; sante=$h} | ConvertTo-Json -Depth 4 -Compress
"""


def _sante(v) -> str:
    """HealthStatus de Get-PhysicalDisk : texte ou nombre selon la version de PowerShell."""
    if isinstance(v, int) or (isinstance(v, str) and v.isdigit()):
        return {0: "Healthy", 1: "Warning", 2: "Unhealthy"}.get(int(v), "")
    return (v or "").strip()


def _lettre(v) -> str:
    if isinstance(v, int):
        v = chr(v) if v else ""
    v = (v or "").strip("\0 ")
    return v.upper() if len(v) == 1 and v.isalpha() else ""


def analyser_inventaire_windows(texte: str) -> list[Disque]:
    """Inventaire Windows depuis le JSON de SCRIPT_INVENTAIRE (testé hors Windows)."""
    donnees = json.loads(texte)

    def liste(x):
        return x if isinstance(x, list) else ([x] if x else [])

    fs = {v.get("UniqueId"): (v.get("FileSystem") or "") for v in liste(donnees.get("volumes"))}
    sante = {str(h.get("DeviceId")): _sante(h.get("Sante")) for h in liste(donnees.get("sante"))}
    disques = []
    for d in liste(donnees.get("disques")):
        bus = d.get("BusType")
        bus = BUS_WINDOWS.get(bus, str(bus)) if isinstance(bus, int) else str(bus or "")
        n = int(d["Number"])
        disque = Disque(
            chemin=f"\\\\.\\PhysicalDrive{n}", numero=n,
            modele=(d.get("FriendlyName") or "").strip(), taille=int(d.get("Size") or 0),
            taille_secteur=int(d.get("LogicalSectorSize") or 512),
            secteur_physique=int(d.get("PhysicalSectorSize") or 512), bus=bus,
            systeme=bool(d.get("IsBoot") or d.get("IsSystem")),
            hors_ligne=bool(d.get("IsOffline")), lecture_seule=bool(d.get("IsReadOnly")),
            serie=(d.get("SerialNumber") or "").strip(), sante=sante.get(str(n), ""))
        for p in liste(donnees.get("partitions")):
            if int(p.get("DiskNumber", -1)) != n:
                continue
            chemins = liste(p.get("AccessPaths"))
            guid = next((c for c in chemins if c.startswith("\\\\?\\Volume{")), "")
            lettre = _lettre(p.get("Lettre"))
            if not lettre:
                lettre = next((c[0].upper() for c in chemins if len(c) <= 3 and c[1:2] == ":"), "")
            if not (lettre or guid):
                continue
            disque.volumes.append(Volume(
                debut=int(p["Offset"]), taille=int(p["Size"]),
                nom=f"{lettre}:" if lettre else "", chemin=guid, systeme_fichiers=fs.get(guid, "")))
        disques.append(disque)
    return sorted(disques, key=lambda d: d.numero)


def _lister_windows() -> list[Disque]:
    return analyser_inventaire_windows(powershell(SCRIPT_INVENTAIRE))


def preparer_cible_windows(cible: Disque) -> None:
    """Met la cible en ligne, en écriture, et retire ses partitions.

    Un volume monté interdit d'écrire dans sa zone, même à l'administrateur :
    la cible doit donc être vide (« RAW ») avant la copie.
    """
    n = int(cible.numero)
    powershell(f"""
$d = Get-Disk -Number {n}
if ($d.IsBoot -or $d.IsSystem) {{ throw 'disque systeme' }}
if ($d.Size -ne {cible.taille}) {{ throw 'taille inattendue' }}
if ($d.IsOffline) {{ Set-Disk -Number {n} -IsOffline $false }}
if ($d.IsReadOnly) {{ Set-Disk -Number {n} -IsReadOnly $false }}
$d = Get-Disk -Number {n}
if ($d.PartitionStyle -ne 'RAW') {{ Clear-Disk -Number {n} -RemoveData -RemoveOEM -Confirm:$false }}
""", delai=300)


def rafraichir_windows(cible: Disque) -> None:
    try:
        powershell(f"Update-Disk -Number {int(cible.numero)}", delai=60)
    except Exception:
        pass


class ClicheVSS:
    def __init__(self, ident: str, peripherique: str):
        self.ident, self.peripherique = ident, peripherique


def creer_cliche(volume: Volume) -> ClicheVSS:
    cible = volume.chemin or (volume.nom + "\\")
    cible = cible.replace("'", "''")
    sortie = powershell(f"""
$r = Invoke-CimMethod -ClassName Win32_ShadowCopy -MethodName Create -Arguments @{{Volume='{cible}'; Context='ClientAccessible'}}
if ($r.ReturnValue -ne 0) {{ throw ('Win32_ShadowCopy.Create : code ' + $r.ReturnValue) }}
$s = Get-CimInstance Win32_ShadowCopy | Where-Object {{ $_.ID -eq $r.ShadowID }}
@{{id=$s.ID; peripherique=$s.DeviceObject}} | ConvertTo-Json -Compress
""", delai=600)
    d = json.loads(sortie)
    return ClicheVSS(d["id"], d["peripherique"])


def cliche_existe(ident: str) -> bool:
    try:
        sortie = powershell(f"@(Get-CimInstance Win32_ShadowCopy | Where-Object {{ $_.ID -eq '{ident}' }}).Count",
                            delai=120)
        return sortie.strip() == "1"
    except Exception:
        return False


def supprimer_cliche(c: ClicheVSS) -> None:
    try:
        powershell(f"Get-CimInstance Win32_ShadowCopy | Where-Object {{ $_.ID -eq '{c.ident}' }} | Remove-CimInstance",
                   delai=120)
    except Exception:
        pass


def bitlocker_windows() -> set[str]:
    """Lettres des volumes chiffrés par BitLocker (vide si l'outil manque)."""
    try:
        sortie = powershell("@(Get-BitLockerVolume | Where-Object { $_.VolumeStatus -ne 'FullyDecrypted' } "
                            "| ForEach-Object { $_.MountPoint }) | ConvertTo-Json -Compress", delai=60)
        v = json.loads(sortie or "[]")
        v = v if isinstance(v, list) else [v]
        return {str(x)[:2].upper() for x in v if x}
    except Exception:
        return set()


def est_administrateur() -> bool:
    if sys.platform != "win32":
        return os.geteuid() == 0 if hasattr(os, "geteuid") else True
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# ------------------------------------------------------------ Linux

def analyser_lsblk(texte: str, racine: str = "/") -> list[Disque]:
    donnees = json.loads(texte)
    disques = []
    for d in donnees.get("blockdevices", []):
        if d.get("type") != "disk" or str(d.get("name", "")).startswith(("loop", "zram", "ram", "sr")):
            continue
        disque = Disque(
            chemin=d.get("path") or f"/dev/{d['name']}", numero=None,
            modele=(d.get("model") or d.get("name") or "").strip(), taille=int(d.get("size") or 0),
            taille_secteur=int(d.get("log-sec") or 512), secteur_physique=int(d.get("phy-sec") or 512),
            bus=(d.get("tran") or "").upper(), lecture_seule=bool(d.get("ro")),
            serie=(d.get("serial") or "").strip())
        for p in d.get("children") or []:
            points = [m for m in (p.get("mountpoints") or []) if m]
            if not points:
                continue
            if racine in points or any(m in ("/boot", "/boot/efi", "/usr") for m in points):
                disque.systeme = True
            disque.volumes.append(Volume(debut=int(p.get("start") or 0) * 512, taille=int(p.get("size") or 0),
                                         nom=points[0], chemin=p.get("path") or "",
                                         systeme_fichiers=p.get("fstype") or ""))
        disques.append(disque)
    return disques


def _lister_linux() -> list[Disque]:
    r = subprocess.run(["lsblk", "-J", "-b", "-o",
                        "NAME,PATH,TYPE,SIZE,MODEL,SERIAL,TRAN,LOG-SEC,PHY-SEC,RO,START,FSTYPE,MOUNTPOINTS"],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise ErreurAcces("acces.inventaire", detail=r.stderr.strip())
    return analyser_lsblk(r.stdout)


def montages_ecriture_linux(chemin_disque: str) -> list[str]:
    """Points de montage en écriture des partitions d'un disque (/proc/mounts)."""
    base = os.path.realpath(chemin_disque)
    trouves = []
    try:
        with open("/proc/mounts", encoding="utf-8") as f:
            for ligne in f:
                dev, point, _fs, options = ligne.split()[:4]
                dev = os.path.realpath(dev) if dev.startswith("/dev/") else dev
                if dev.startswith(base) and dev != base or dev == base:
                    if "rw" in options.split(","):
                        trouves.append(point)
    except OSError:
        pass
    return trouves


# ------------------------------------------------------------ commun

def lister() -> list[Disque]:
    if sys.platform == "win32":
        return _lister_windows()
    if sys.platform.startswith("linux"):
        return _lister_linux()
    return []


def disque_image(chemin: str, taille_secteur: int = 512) -> Disque:
    taille = os.path.getsize(chemin)
    return Disque(chemin=chemin, numero=None, modele=os.path.basename(chemin), taille=taille,
                  taille_secteur=taille_secteur, secteur_physique=taille_secteur, bus="image")


def retrouver(empreinte: dict) -> Disque | None:
    """Le disque qui porte cette empreinte, même sous un autre numéro."""
    chemin = empreinte.get("chemin", "")
    if chemin and os.path.isfile(chemin):
        return disque_image(chemin, empreinte.get("secteur", 512))
    try:
        candidats = [d for d in lister() if d.correspond(empreinte)]
    except Exception:
        return None
    if len(candidats) == 1:
        return candidats[0]
    return next((d for d in candidats if d.chemin == chemin), None)


def preparer_cible(cible: Disque) -> None:
    if sys.platform == "win32" and cible.numero is not None:
        preparer_cible_windows(cible)


def rafraichir(cible: Disque) -> None:
    if sys.platform == "win32" and cible.numero is not None:
        rafraichir_windows(cible)
    elif sys.platform.startswith("linux") and cible.chemin.startswith("/dev/"):
        subprocess.run(["blockdev", "--rereadpt", cible.chemin], capture_output=True)


class Figes:
    """Lecteurs des partitions de la source, et les clichés qui les portent."""

    def __init__(self):
        self.lecteurs: dict[int, object] = {}
        self.cliches: dict[int, ClicheVSS] = {}
        self.garder = False          # True : clichés conservés pour une reprise


@contextmanager
def lecteurs_figes(source: Disque, dev_source, parts: list[tuple[int, int, int]], journal=None,
                   existants: dict[int, tuple[str, str]] | None = None):
    """Lecteurs des partitions de la source, figés par un cliché quand il le faut.

    `parts` : [(numéro, début octets, taille)]. Sous Windows, une partition qui
    porte un volume monté (C:, D:…) est lue dans un cliché VSS ; les autres
    (EFI, récupération) directement sur le disque. `existants` : clichés d'un
    clonage interrompu, réutilisés tels quels (la reprise doit lire EXACTEMENT
    le même état du disque). Les clichés sont supprimés à la sortie, sauf si
    l'appelant a demandé de les garder (`garder`) pour une reprise.
    """
    f, ouverts = Figes(), []
    existants = existants or {}
    try:
        for numero, debut, taille in parts:
            vol = next((v for v in source.volumes if v.debut == debut), None)
            if sys.platform == "win32" and vol is not None and source.numero is not None:
                if numero in existants:
                    ident, peripherique = existants[numero]
                    if not cliche_existe(ident):
                        from .clonage import ErreurClonage
                        raise ErreurClonage("clone.cliche_perdu")
                    c = ClicheVSS(ident, peripherique)
                else:
                    if journal:
                        journal("cliche", nom=vol.nom or vol.chemin)
                    c = creer_cliche(vol)
                f.cliches[numero] = c
                dev = ouvrir(c.peripherique, False, source.taille_secteur)
                ouverts.append(dev)
                f.lecteurs[numero] = dev
            else:
                f.lecteurs[numero] = Fenetre(dev_source, debut, taille)
        yield f
    finally:
        for d in ouverts:
            d.fermer()
        if not f.garder:
            for c in f.cliches.values():
                supprimer_cliche(c)


def supprimer_cliches(idents: list[str]) -> None:
    if sys.platform == "win32":
        for i in idents:
            supprimer_cliche(ClicheVSS(i, ""))
