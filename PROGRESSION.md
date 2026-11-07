# Calque — progression

## État au 07/11/2026 — version 0.1.0, NON publiée

Dépôt local seulement (branche `main`, un commit). Pas encore de dépôt GitHub, donc ni CI ni Release.

### Fait et vérifié
- Moteur pur Python : tables GPT/MBR (`calque/table.py`), carte des clusters NTFS occupés
  (`calque/ntfs.py`), plan + copie + relecture + table écrite en dernier (`calque/clonage.py`).
- Accès disque : POSIX (Linux, fichiers image) et Windows sans tampon (`calque/peripherique.py`) ;
  inventaire Get-Disk / lsblk, clichés VSS, préparation de la cible par Clear-Disk (`calque/disques.py`).
- 41 tests verts sous Linux, dont des clonages de bout en bout sur de VRAIS disques image fabriqués par
  sgdisk/mkntfs/ntfscp (GPT et MBR façon Windows) : fichiers relus à l'identique par ntfscat, `sgdisk -v`
  sans problème, identifiants conservés, récupération en fin de disque et alignée, secteurs cachés
  corrigés, annulation qui laisse la cible sans table, refus 4K / cible trop petite.
- Ligne de commande éprouvée (`--lister`, `--cloner image image --oui`).
- Interface hors écran (test + captures), manuel FR/EN (9 p., 0 débordement), logo, kit posé
  (multiplateforme + garde-fou de confidentialité, vert).

### PAS encore vérifié
- **Rien n'a tourné sous Windows.** Le chemin Windows (PowerShell Get-Disk, VSS, CreateFileW sans
  tampon, Clear-Disk, IOCTL) est écrit mais non exécuté. `tests/test_windows_vhd.py` (clonage à chaud
  réel entre deux VHDX, cliché VSS, chkdsk, Resize-Partition) l'éprouvera dans la CI Windows
  (`tests.yml`) dès que le dépôt sera poussé.
- Élévation UAC au lancement, boutons « Agrandir C: » et « Réparer WinRE » sur un vrai PC.
- Paquets (installeur, tar.gz) : jamais construits ; le gabarit build_package du kit a reçu le
  correctif pip (roue au lieu de get-pip.py) sans essai CI ici.
- macOS : le paquet sera construit par le gabarit mais `disques.lister()` y rend une liste vide.

### Prochaines étapes
1. Créer le dépôt public `ARP273-ROSE/Calque`, pousser `main` ; suivre `tests.yml` (surtout le job
   Windows / VHDX) et corriger.
2. Tag `v0.1.0` → `release.yml` (gabarit du kit) ; vérifier la Release par l'API.
3. Premier essai réel : PC Windows, disque cible en boîtier USB (lire la ligne « secteurs » de
   `calque --lister`).

### Pièges
- Boîtier USB qui présente 4096 o/secteur : clone non amorçable une fois monté en interne → refus.
- Ne pas démarrer avec source et clone branchés (mêmes GUID → collision, disque hors ligne).
- Une partition montée interdit l'écriture brute dans sa zone sous Windows → Clear-Disk d'abord.
