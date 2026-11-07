"""Tables GPT et MBR : écriture puis relecture, sans outil externe."""
import struct
import sys
import uuid
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from calque import ntfs, table as T  # noqa: E402

MIO = 1024 * 1024


def _disque(t: T.Table) -> bytearray:
    d = bytearray(t.secteurs_disque * t.taille_secteur)
    for pos, donnees in T.zones_table(t):
        d[pos:pos + len(donnees)] = donnees
    return d


def _gpt(secteurs: int, ss: int = 512) -> T.Table:
    pas = MIO // ss
    t = T.Table("gpt", ss, secteurs, guid_disque=str(uuid.uuid4()), signature=0x12345678)
    defs = [(pas, 100 * pas, T.GPT_EFI, "efi"), (101 * pas, 16 * pas, T.GPT_MSR, "msr"),
            (117 * pas, secteurs - 117 * pas - 40 * pas, T.GPT_DONNEES_MS, "donnees")]
    fin_c = defs[-1][0] + defs[-1][1]
    defs.append((fin_c, 30 * pas, T.GPT_RECUPERATION, "recuperation"))
    for i, (deb, n, typ, nat) in enumerate(defs):
        t.partitions.append(T.Partition(i + 1, deb, n, typ, nat, guid=str(uuid.uuid4()),
                                        nom=f"p{i + 1}", index=i, attributs=1 if nat == "recuperation" else 0))
    return t


@pytest.mark.parametrize("ss", [512, 4096])
def test_gpt_aller_retour(ss):
    t = _gpt(400 * MIO // ss, ss)
    d = _disque(t)
    lu = T.lire(lambda p, n: bytes(d[p:p + n]), len(d), ss)
    assert lu.style == "gpt" and lu.guid_disque == t.guid_disque
    assert [(p.debut, p.secteurs, p.guid, p.type, p.nom, p.attributs) for p in lu.triees()] == \
        [(p.debut, p.secteurs, p.guid, p.type, p.nom, p.attributs) for p in t.triees()]
    # en-tête de secours valide, au bon endroit
    fin = bytes(d[-ss:])
    assert fin[:8] == b"EFI PART" and struct.unpack_from("<Q", fin, 24)[0] == t.secteurs_disque - 1


def test_transposer_vers_le_double():
    ss = 512
    t = _gpt(400 * MIO // ss)
    neuve, debuts = T.transposer(t, 800 * MIO // ss)
    rec = neuve.triees()[-1]
    assert rec.nature == "recuperation"
    assert rec.fin - 1 <= T.dernier_utilisable(neuve, neuve.secteurs_disque)
    assert rec.debut % (MIO // ss) == 0
    assert neuve.triees()[2].debut == t.triees()[2].debut
    d = _disque(neuve)
    assert T.lire(lambda p, n: bytes(d[p:p + n]), len(d), ss).triees()[-1].debut == rec.debut


def test_transposer_sans_deplacement():
    t = _gpt(400 * MIO // 512)
    neuve, _ = T.transposer(t, 800 * MIO // 512, deplacer_fin=False)
    assert [p.debut for p in neuve.triees()] == [p.debut for p in t.triees()]


def test_cible_trop_petite():
    t = _gpt(400 * MIO // 512)
    with pytest.raises(T.ErreurTable) as e:
        T.transposer(t, 300 * MIO // 512)
    assert e.value.cle == "table.cible_trop_petite"


def test_crc_abime_refuse():
    t = _gpt(200 * MIO // 512)
    d = _disque(t)
    d[1024 + 5] ^= 0xFF          # premier octet du tableau d'entrées
    with pytest.raises(T.ErreurTable) as e:
        T.lire(lambda p, n: bytes(d[p:p + n]), len(d), 512)
    assert e.value.cle == "table.gpt_crc"


def test_mbr_aller_retour_et_etendue_refusee():
    t = T.Table("mbr", 512, 200 * MIO // 512, signature=0xCAFEBABE, code_amorce=b"\xeb\x63" + b"\x90" * 438)
    t.partitions = [T.Partition(1, 2048, 100 * 2048, "0x07", "donnees", active=True),
                    T.Partition(2, 102 * 2048, 50 * 2048, "0x27", "recuperation")]
    d = _disque(t)
    lu = T.lire(lambda p, n: bytes(d[p:p + n]), len(d), 512)
    assert lu.signature == 0xCAFEBABE and lu.code_amorce[:2] == b"\xeb\x63"
    assert [(p.debut, p.secteurs, p.active, p.type) for p in lu.triees()] == \
        [(2048, 204800, True, "0x07"), (208896, 102400, False, "0x27")]
    d[446 + 16 + 4] = 0x0F
    with pytest.raises(T.ErreurTable) as e:
        T.lire(lambda p, n: bytes(d[p:p + n]), len(d), 512)
    assert e.value.cle == "table.etendue"


def test_disque_dynamique_refuse():
    t = _gpt(200 * MIO // 512)
    t.partitions[2].type = T.GPT_LDM_DONNEES
    t.partitions[2].brut = b""
    d = _disque(t)
    with pytest.raises(T.ErreurTable) as e:
        T.lire(lambda p, n: bytes(d[p:p + n]), len(d), 512)
    assert e.value.cle == "table.dynamique"


def test_nature_des_volumes():
    s = bytearray(512)
    s[3:11] = b"-FVE-FS-"
    assert ntfs.nature(bytes(s)) == "bitlocker"
    s[3:11] = b"NTFS    "
    assert ntfs.nature(bytes(s)) == "ntfs"
    assert ntfs.nature(bytes(512)) == "inconnu"
