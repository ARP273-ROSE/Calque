# Journal des versions / Changelog

### 0.1.1

**Français**
- Avertissement de place pour le cliché proportionné à la taille du volume (plus de fausse alerte sur un
  petit volume presque vide).
- La partition réservée de Microsoft (MSR) n'est plus affichée « inconnu ».

**English**
- Snapshot free-space warning scaled to the volume size (no more false alarm on a small, nearly empty volume).
- The Microsoft reserved partition (MSR) is no longer shown as "unknown".

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
- Boîtier USB qui décroche : attente et reconnexion automatiques (même sous un autre numéro) ; sinon arrêt
  propre et bouton « Reprendre », qui repart du même cliché là où la copie s'était arrêtée.
- Copie bridée pour ménager un boîtier USB qui chauffe ; mise en veille de Windows bloquée pendant la copie.
- Secteurs illisibles sur la source : avertissement, puis « Continuer malgré tout » (remplis de zéros, comptés).
- Plan avec quantité à copier et durée estimée ; état de santé du disque source signalé.

**English**
- First version. Clones a GPT or MBR disk to a disk at least as large, identifiers kept (the clone boots
  with no repair).
- Windows: hot copy of the system disk through a snapshot (VSS); Linux: copy from a live stick.
- Only the used blocks of NTFS volumes are copied; every block is read back and compared.
- Recovery partition moved to the end of the disk; “After cloning” tab: extend C:, repair the recovery
  environment.
- Explained refusals: 4096-byte sectors presented by a USB enclosure, BitLocker, dynamic disk, target too
  small, mounted source (Linux).
- USB enclosure dropping out: automatic wait and reconnection (even under a new number); otherwise a clean
  stop and a “Resume” button that restarts from the same snapshot where the copy stopped.
- Capped copy speed to spare a USB enclosure that heats up; Windows sleep blocked during the copy.
- Unreadable sectors on the source: warning, then “Continue anyway” (filled with zeros, counted).
- Plan with the amount to copy and an estimated time; source disk health reported.
