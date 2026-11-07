"""Essai réel sous Windows : deux disques virtuels VHDX, clonage À CHAUD.

Lancé par la CI (runner Windows, administrateur) avec CALQUE_ESSAI_VHD=1.
Source « façon Windows » (GPT : EFI, MSR, volume NTFS avec lettre, partition
de récupération en fin de disque), cible deux fois plus grande, vierge.

Ce qui est éprouvé : l'inventaire Get-Disk, le cliché VSS d'un volume monté
pendant qu'on y écrit, la mise à zéro de la cible (Clear-Disk), l'écriture brute
sans tampon, la relecture, la table finale ; puis, la source débranchée, le
clone est mis en ligne, ses fichiers relus et son volume agrandi par
Resize-Partition — ce que fera l'onglet « Après le clonage ».
"""
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

pytestmark = pytest.mark.skipif(sys.platform != "win32" or os.environ.get("CALQUE_ESSAI_VHD") != "1",
                                reason="essai Windows réel (CI, administrateur)")
MIO = 1024 * 1024
LETTRE = "R"
TYPE_RECUP = "de94bba4-06d1-4d40-a16a-bfd50179d6ac"


def diskpart(script: str) -> str:
    f = Path(os.environ.get("RUNNER_TEMP", ".")) / "calque-diskpart.txt"
    f.write_text(script, encoding="ascii")
    r = subprocess.run(["diskpart", "/s", str(f)], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def ps(script: str) -> str:
    from calque.disques import powershell
    return powershell(script, delai=600)


def numero(vhdx: Path) -> int:
    return int(ps(f"(Get-DiskImage -ImagePath '{vhdx}' | Get-Disk).Number").strip())


@pytest.fixture(scope="module")
def vhd(tmp_path_factory):
    d = tmp_path_factory.mktemp("vhd")
    src, cib = d / "source.vhdx", d / "cible.vhdx"
    diskpart(f"""create vdisk file="{src}" maximum=3072 type=expandable
attach vdisk
convert gpt
create partition efi size=100
format quick fs=fat32 label=SYSTEM
create partition msr size=16
create partition primary size=2200
format quick fs=ntfs label=Essai
assign letter={LETTRE}
create partition primary
format quick fs=ntfs label=Recovery
set id="{TYPE_RECUP}"
gpt attributes=0x8000000000000001
""")
    diskpart(f"""create vdisk file="{cib}" maximum=6144 type=expandable
attach vdisk
""")
    temoins = {}
    for i in range(5):
        contenu = os.urandom(7 * MIO + i * 4321)
        (Path(f"{LETTRE}:/") / f"temoin{i}.bin").write_bytes(contenu)
        temoins[f"temoin{i}.bin"] = hashlib.sha256(contenu).hexdigest()
    yield src, cib, temoins
    for v in (src, cib):
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"Dismount-DiskImage -ImagePath '{v}' -ErrorAction SilentlyContinue"], capture_output=True)


def test_clonage_a_chaud_vers_vhdx(vhd):
    from calque import clonage, disques
    src, cib, temoins = vhd
    n_src, n_cib = numero(src), numero(cib)
    tous = {d.numero: d for d in disques.lister()}
    source, cible = tous[n_src], tous[n_cib]
    assert any(v.nom == f"{LETTRE}:" for v in source.volumes), source.volumes
    plan = clonage.preparer_plan(source, cible)
    assert plan.possible, plan.bloquants
    assert [t.partition.nature for t in plan.travaux] == ["efi", "msr", "donnees", "recuperation"]
    assert plan.travaux[-1].deplacee

    # on écrit sur le volume source PENDANT le clonage : le cliché doit l'ignorer
    stop = threading.Event()

    def ecrivain():
        k = 0
        while not stop.is_set():
            (Path(f"{LETTRE}:/") / f"pendant{k % 3}.bin").write_bytes(os.urandom(MIO))
            k += 1
            time.sleep(0.05)

    t = threading.Thread(target=ecrivain, daemon=True)
    t.start()
    etapes = []
    arret = threading.Event()
    try:
        # 1re passe interrompue vers 30 % : le cliché doit être GARDÉ pour la reprise
        with pytest.raises(clonage.Annule):
            clonage.cloner(plan, journal=lambda c, **k: etapes.append(c), annulation=arret,
                           rappel=lambda **k: k["etape"] == "copie" and k["fait"] > 0.3 * k["total"] and arret.set())
        assert ps("@(Get-CimInstance Win32_ShadowCopy).Count").strip() == "1"
        assert clonage.reprise_possible(plan)
        bilan = clonage.cloner(plan, journal=lambda c, **k: etapes.append(c), reprendre=True)
    finally:
        stop.set()
        t.join()
    assert etapes.count("cliche") == 1 and bilan.blocs_differents == 0 and bilan.repris_a > 0
    # cliché supprimé
    assert ps("@(Get-CimInstance Win32_ShadowCopy).Count").strip() == "0"

    # la source débranchée, le clone est mis en ligne et lu
    ps(f"Dismount-DiskImage -ImagePath '{src}'")
    ps(f"Set-Disk -Number {n_cib} -IsOffline $false; Set-Disk -Number {n_cib} -IsReadOnly $false; "
       f"Update-Disk -Number {n_cib}")
    parts = json.loads(ps(f"@(Get-Partition -DiskNumber {n_cib} | Select-Object PartitionNumber,Offset,Size,GptType) "
                          "| ConvertTo-Json -Compress"))
    parts = sorted(parts, key=lambda p: p["Offset"])
    assert len(parts) == 4
    assert parts[3]["GptType"].strip("{}").lower() == TYPE_RECUP
    assert parts[3]["Offset"] + parts[3]["Size"] > 6000 * MIO          # récupération en fin de disque
    num_c = next(p["PartitionNumber"] for p in parts if p["Size"] == 2200 * MIO)
    lettre = ps(f"Add-PartitionAccessPath -DiskNumber {n_cib} -PartitionNumber {num_c} -AssignDriveLetter; "
                f"(Get-Partition -DiskNumber {n_cib} -PartitionNumber {num_c}).DriveLetter").strip()
    assert lettre
    for nom, empreinte in temoins.items():
        assert hashlib.sha256((Path(f"{lettre}:/") / nom).read_bytes()).hexdigest() == empreinte, nom
    r = subprocess.run(["chkdsk", f"{lettre}:"], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout[-2000:]
    # « Agrandir C: » : tout l'espace libre derrière le volume est récupérable
    sortie = json.loads(ps(f"""
$s = Get-PartitionSupportedSize -DriveLetter {lettre}
Resize-Partition -DriveLetter {lettre} -Size $s.SizeMax
@{{taille=(Get-Partition -DriveLetter {lettre}).Size}} | ConvertTo-Json -Compress"""))
    assert sortie["taille"] > 5000 * MIO
