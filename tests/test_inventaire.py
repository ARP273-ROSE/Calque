"""Inventaire des disques : sorties de Get-Disk (Windows) et de lsblk (Linux)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from calque import disques as D  # noqa: E402

WINDOWS = {
    "disques": [
        {"Number": 0, "FriendlyName": "NVMe SSD 500GB", "SerialNumber": "0001 ",
         "Size": 500107862016, "BusType": 17, "PartitionStyle": "GPT", "IsBoot": True, "IsSystem": True,
         "IsOffline": False, "IsReadOnly": False, "LogicalSectorSize": 512, "PhysicalSectorSize": 512},
        {"Number": 2, "FriendlyName": "USB3.0 Dock", "SerialNumber": None, "Size": 1000204886016,
         "BusType": 7, "PartitionStyle": "RAW", "IsBoot": False, "IsSystem": False,
         "IsOffline": False, "IsReadOnly": False, "LogicalSectorSize": 4096, "PhysicalSectorSize": 4096}],
    "partitions": [
        {"DiskNumber": 0, "PartitionNumber": 1, "Offset": 1048576, "Size": 104857600, "Lettre": "",
         "AccessPaths": ["\\\\?\\Volume{aaaa}\\"]},
        {"DiskNumber": 0, "PartitionNumber": 2, "Offset": 105906176, "Size": 16777216, "Lettre": "",
         "AccessPaths": None},
        {"DiskNumber": 0, "PartitionNumber": 3, "Offset": 122683392, "Size": 499000000000, "Lettre": "C",
         "AccessPaths": ["C:\\", "\\\\?\\Volume{cccc}\\"]}],
    "volumes": [{"UniqueId": "\\\\?\\Volume{cccc}\\", "FileSystem": "NTFS"},
                {"UniqueId": "\\\\?\\Volume{aaaa}\\", "FileSystem": "FAT32"}],
}


def setup_module():
    from calque import i18n
    i18n.definir_langue("fr")


def test_inventaire_windows():
    d0, d2 = D.analyser_inventaire_windows(json.dumps(WINDOWS))
    assert d0.chemin == "\\\\.\\PhysicalDrive0" and d0.systeme and d0.bus == "NVMe"
    assert [(v.nom, v.systeme_fichiers) for v in d0.volumes] == [("", "FAT32"), ("C:", "NTFS")]
    assert d2.bus == "USB" and d2.taille_secteur == 4096 and not d2.systeme
    assert d2.libelle() == "2 · USB3.0 Dock · 1,0 To · USB"


def test_inventaire_windows_un_seul_disque():
    """ConvertTo-Json rend un objet seul au lieu d'une liste : accepté."""
    seul = dict(WINDOWS, disques=WINDOWS["disques"][1], partitions=None, volumes=None)
    (d,) = D.analyser_inventaire_windows(json.dumps(seul))
    assert d.numero == 2 and d.volumes == []


def test_lsblk():
    texte = json.dumps({"blockdevices": [
        {"name": "nvme0n1", "path": "/dev/nvme0n1", "type": "disk", "size": 500107862016,
         "model": "NVMe SSD 500GB", "serial": "0001", "tran": "nvme", "log-sec": 512,
         "phy-sec": 512, "ro": False, "children": [
             {"name": "nvme0n1p3", "path": "/dev/nvme0n1p3", "start": 239616, "size": 499000000000,
              "fstype": "ntfs", "mountpoints": [None]}]},
        {"name": "sda", "path": "/dev/sda", "type": "disk", "size": 64000000000, "model": "Live",
         "tran": "usb", "log-sec": 512, "phy-sec": 512, "ro": False, "children": [
             {"name": "sda1", "path": "/dev/sda1", "start": 2048, "size": 63000000000, "fstype": "iso9660",
              "mountpoints": ["/"]}]},
        {"name": "loop0", "type": "loop", "size": 1}]})
    nvme, cle = D.analyser_lsblk(texte)
    assert nvme.bus == "NVME" and not nvme.systeme and nvme.volumes == []
    assert cle.systeme and cle.volumes[0].debut == 2048 * 512


def test_tailles_lisibles():
    assert D.octets_lisibles(500107862016) == "500 Go"
    assert D.octets_lisibles(1000204886016) == "1,0 To"
    assert D.octets_lisibles(104857600) == "105 Mo"
    from calque import i18n
    i18n.definir_langue("en")
    assert D.octets_lisibles(1000204886016) == "1.0 TB"
    i18n.definir_langue("fr")
