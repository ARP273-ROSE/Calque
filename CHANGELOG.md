# Journal des versions / Changelog

### 0.1.0

**Français**
- Première version. Clonage d'un disque GPT ou MBR sur un disque au moins aussi grand, identifiants
  conservés (le clone démarre sans réparation).
- Windows : copie à chaud du disque système par cliché instantané (VSS) ; Linux : copie depuis une clé live.
- Seuls les blocs occupés des volumes NTFS sont copiés ; relecture et comparaison de chaque bloc.
- Partition de récupération reportée en fin de disque ; onglet « Après le clonage » : agrandir C:,
  réparer l'environnement de récupération.
- Refus expliqués : secteurs de 4096 octets présentés par un boîtier USB, BitLocker, disque dynamique,
  cible trop petite, source montée (Linux).

**English**
- First version. Clones a GPT or MBR disk to a disk at least as large, identifiers kept (the clone boots
  with no repair).
- Windows: hot copy of the system disk through a snapshot (VSS); Linux: copy from a live stick.
- Only the used blocks of NTFS volumes are copied; every block is read back and compared.
- Recovery partition moved to the end of the disk; “After cloning” tab: extend C:, repair the recovery
  environment.
- Explained refusals: 4096-byte sectors presented by a USB enclosure, BitLocker, dynamic disk, target too
  small, mounted source (Linux).
