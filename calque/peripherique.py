"""Accès brut à un disque, un volume figé (cliché) ou un fichier image.

Deux implémentations, une seule interface : `lire(position, taille)`,
`ecrire(position, donnees)`, `vider()`, `fermer()`, `taille`.

* POSIX (Linux, fichiers image, tests) : os.pread / os.pwrite ;
* Windows : CreateFileW sans tampon système (FILE_FLAG_NO_BUFFERING) et
  écriture directe (WRITE_THROUGH) — la relecture de vérification lit donc le
  disque, pas une copie en mémoire. Ce mode exige des positions, des tailles et
  une mémoire alignées sur le secteur : le tampon vient de VirtualAlloc
  (aligné sur la page), et les accès non alignés sont élargis au secteur.
"""
from __future__ import annotations

import os
import sys

TAMPON = 8 * 1024 * 1024


class ErreurAcces(Exception):
    def __init__(self, cle: str, **champs):
        super().__init__(f"{cle} {champs}")
        self.cle, self.champs = cle, champs


class Posix:
    def __init__(self, chemin: str, ecriture: bool = False, taille_secteur: int = 512):
        drapeaux = (os.O_RDWR if ecriture else os.O_RDONLY) | getattr(os, "O_BINARY", 0)
        try:
            self.fd = os.open(chemin, drapeaux)
        except PermissionError as e:
            raise ErreurAcces("acces.refuse", chemin=chemin, detail=str(e)) from e
        except OSError as e:
            raise ErreurAcces("acces.ouverture", chemin=chemin, detail=str(e)) from e
        self.chemin, self.ecriture, self.taille_secteur = chemin, ecriture, taille_secteur
        self.taille = os.lseek(self.fd, 0, os.SEEK_END)

    def lire(self, position: int, taille: int) -> bytes:
        morceaux, fait = [], 0
        while fait < taille:
            b = os.pread(self.fd, taille - fait, position + fait)
            if not b:
                break
            morceaux.append(b)
            fait += len(b)
        donnees = b"".join(morceaux)
        if len(donnees) < taille:
            donnees += b"\0" * (taille - len(donnees))
        return donnees

    def ecrire(self, position: int, donnees: bytes) -> None:
        vue, fait = memoryview(donnees), 0
        while fait < len(donnees):
            fait += os.pwrite(self.fd, vue[fait:], position + fait)

    def vider(self) -> None:
        os.fsync(self.fd)

    def fermer(self) -> None:
        try:
            os.close(self.fd)
        except OSError:
            pass


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
    FILE_SHARE_READ, FILE_SHARE_WRITE = 1, 2
    OPEN_EXISTING = 3
    FILE_FLAG_NO_BUFFERING, FILE_FLAG_WRITE_THROUGH = 0x20000000, 0x80000000
    IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C
    IOCTL_DISK_UPDATE_PROPERTIES = 0x00070140
    MEM_COMMIT, MEM_RESERVE, MEM_RELEASE, PAGE_READWRITE = 0x1000, 0x2000, 0x8000, 0x04
    INVALID = ctypes.c_void_p(-1).value

    _k32.CreateFileW.restype = wintypes.HANDLE
    _k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                 wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    _k32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                              ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    _k32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    _k32.SetFilePointerEx.argtypes = [wintypes.HANDLE, ctypes.c_longlong,
                                      ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD]
    _k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                     ctypes.c_void_p, wintypes.DWORD,
                                     ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    _k32.VirtualAlloc.restype = ctypes.c_void_p
    _k32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
    _k32.VirtualFree.argtypes = [ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD]
    _k32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]

    class Windows:
        def __init__(self, chemin: str, ecriture: bool = False, taille_secteur: int = 512):
            acces = GENERIC_READ | (GENERIC_WRITE if ecriture else 0)
            drapeaux = FILE_FLAG_NO_BUFFERING | (FILE_FLAG_WRITE_THROUGH if ecriture else 0)
            h = _k32.CreateFileW(chemin, acces, FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                                 OPEN_EXISTING, drapeaux, None)
            if h in (None, INVALID):
                err = ctypes.get_last_error()
                cle = "acces.refuse" if err == 5 else "acces.ouverture"
                raise ErreurAcces(cle, chemin=chemin, detail=f"WinError {err}: {ctypes.FormatError(err)}")
            self.h, self.chemin, self.ecriture = h, chemin, ecriture
            self.taille_secteur = taille_secteur
            self.tampon = _k32.VirtualAlloc(None, TAMPON, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
            if not self.tampon:
                raise MemoryError("VirtualAlloc")
            self.taille = self._longueur()

        def _ioctl(self, code: int, sortie_taille: int = 0) -> bytes:
            sortie = ctypes.create_string_buffer(max(1, sortie_taille))
            rendu = wintypes.DWORD(0)
            ok = _k32.DeviceIoControl(self.h, code, None, 0, sortie, sortie_taille, ctypes.byref(rendu), None)
            if not ok:
                err = ctypes.get_last_error()
                raise ErreurAcces("acces.ioctl", chemin=self.chemin, detail=f"WinError {err}")
            return sortie.raw[:rendu.value]

        def _longueur(self) -> int:
            try:
                return int.from_bytes(self._ioctl(IOCTL_DISK_GET_LENGTH_INFO, 8)[:8], "little")
            except ErreurAcces:
                return 0

        def mettre_a_jour(self) -> None:
            """Demande au système de relire la table de partitions."""
            try:
                self._ioctl(IOCTL_DISK_UPDATE_PROPERTIES)
            except ErreurAcces:
                pass

        def _placer(self, position: int) -> None:
            if not _k32.SetFilePointerEx(self.h, position, None, 0):
                err = ctypes.get_last_error()
                raise ErreurAcces("acces.position", chemin=self.chemin, detail=f"WinError {err}")

        def _bloc_lu(self, position: int, taille: int) -> bytes:
            self._placer(position)
            lu = wintypes.DWORD(0)
            if not _k32.ReadFile(self.h, self.tampon, taille, ctypes.byref(lu), None):
                err = ctypes.get_last_error()
                raise ErreurAcces("acces.lecture", chemin=self.chemin, position=position,
                                  detail=f"WinError {err}: {ctypes.FormatError(err)}")
            return ctypes.string_at(self.tampon, lu.value)

        def lire(self, position: int, taille: int) -> bytes:
            ss = self.taille_secteur
            debut = position - position % ss
            fin = -(-(position + taille) // ss) * ss
            if self.taille:
                fin = min(fin, self.taille)
            morceaux, p = [], debut
            while p < fin:
                n = min(TAMPON, fin - p)
                b = self._bloc_lu(p, n)
                if not b:
                    break
                morceaux.append(b)
                p += len(b)
            donnees = b"".join(morceaux)[position - debut:position - debut + taille]
            return donnees.ljust(taille, b"\0")

        def ecrire(self, position: int, donnees: bytes) -> None:
            ss = self.taille_secteur
            if position % ss or len(donnees) % ss:
                # élargi au secteur : lire, modifier, réécrire
                debut = position - position % ss
                fin = -(-(position + len(donnees)) // ss) * ss
                tout = bytearray(self.lire(debut, fin - debut))
                tout[position - debut:position - debut + len(donnees)] = donnees
                position, donnees = debut, bytes(tout)
            vue, fait = memoryview(donnees), 0
            while fait < len(donnees):
                n = min(TAMPON, len(donnees) - fait)
                ctypes.memmove(self.tampon, bytes(vue[fait:fait + n]), n)
                self._placer(position + fait)
                ecrit = wintypes.DWORD(0)
                if not _k32.WriteFile(self.h, self.tampon, n, ctypes.byref(ecrit), None) or ecrit.value != n:
                    err = ctypes.get_last_error()
                    raise ErreurAcces("acces.ecriture", chemin=self.chemin, position=position + fait,
                                      detail=f"WinError {err}: {ctypes.FormatError(err)}")
                fait += n

        def vider(self) -> None:
            _k32.FlushFileBuffers(self.h)

        def fermer(self) -> None:
            if self.tampon:
                _k32.VirtualFree(self.tampon, 0, MEM_RELEASE)
                self.tampon = None
            if self.h:
                _k32.CloseHandle(self.h)
                self.h = None


def ouvrir(chemin: str, ecriture: bool = False, taille_secteur: int = 512):
    if sys.platform == "win32" and chemin.startswith("\\\\"):
        return Windows(chemin, ecriture, taille_secteur)
    return Posix(chemin, ecriture, taille_secteur)


class Fenetre:
    """Vue d'une partie d'un périphérique (une partition dans un disque)."""

    def __init__(self, dev, debut: int, taille: int):
        self.dev, self.debut, self.taille = dev, debut, taille

    def lire(self, position: int, taille: int) -> bytes:
        return self.dev.lire(self.debut + position, taille)
