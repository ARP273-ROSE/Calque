# Calque — progression

## État au 07/11/2026 — version 0.1.0 publiée (Release en cours de construction)

Dépôt public `ARP273-ROSE/Calque`, branche `main`, tag `v0.1.0`.

### Fait et vérifié
- Moteur pur Python : tables GPT/MBR (`calque/table.py`), clusters NTFS occupés et drapeau « à vérifier »
  (`calque/ntfs.py`), plan, copie, relecture, table écrite en dernier (`calque/clonage.py`).
- Robustesse (`calque/clonage.py`) : cible qui décroche → attente 90 s, retrouvée à son empreinte (taille,
  modèle, série) même sous un autre numéro ; sinon arrêt propre + journal `reprise.json` (dossier des
  données) + clichés VSS GARDÉS → « Reprendre » relit le même cliché. Secteurs illisibles : relecture
  morceau par morceau, arrêt, puis « Continuer malgré tout » (zéros, comptés). Copie bridée (200 Mo/s)
  pour boîtier USB, veille Windows bloquée (SetThreadExecutionState). Cliché supprimé par Windows en
  cours de route : détecté, message dédié.
- Alertes (recherches web 07/11) en trois niveaux, en tête du plan : 4K (bloque), BitLocker (bloque),
  place pour le cliché < 1 Go (bloque) / < 5 Go (attention), cible non vide, batterie, santé du disque,
  volume NTFS « à vérifier » (comme ntfsclone/partclone), démarrage rapide (Linux). Dialogue « point de
  non-retour » + liste avant de lancer (sauvegarde, secteur, dock, Windows Update) ; message final :
  BIOS, ne pas démarrer avec les deux, garder l'ancien disque quelques jours.
- Outils libres en seconde opinion sous Linux : `sgdisk -v`, `ntfsfix -n` sur le clone.
- 50 tests Linux verts (vrais disques image sgdisk/mkntfs/ntfscp : GPT, MBR, reconnexion, reprise,
  secteur illisible, copie bridée, interface hors écran).
- **CI Windows verte (07/11)** : clonage À CHAUD réel entre deux VHDX (diskpart), cliché VSS, écritures
  sur la source pendant la copie, interruption à 30 % puis reprise sur le même cliché, clichés supprimés
  à la fin, clone mis en ligne : fichiers identiques, `chkdsk` OK, `Resize-Partition` au maximum.
  Bug trouvé par cet essai : VSS refusait la partition EFI (code 4) → seuls les volumes NTFS/ReFS avec
  lettre sont figés.

### PAS encore vérifié
- Sur un vrai PC : élévation UAC, dock USB réel qui décroche pour de vrai, boutons « Agrandir C: »
  et « Réparer WinRE » (reagentc), démarrage réel sur le clone.
- Paquets de la Release (installeur, tar.gz) : voir l'exécution `release.yml` du tag v0.1.0.
- macOS : paquet construit par le gabarit, mais aucun accès disque (lister() vide).

### Prochaines étapes
1. Vérifier la Release v0.1.0 par l'API (fichiers, SHA256SUMS).
2. Premier essai réel (PC Windows, cible NVMe en dock USB) : `calque --lister` pour voir les secteurs,
   puis clonage avec « Ménager le boîtier USB ».
3. Si le dock décroche à répétition : carte adaptateur PCIe → M.2, ou clonage sous Linux.

### Pièges
- diskpart « convert gpt » pose une MSR en tête ; Windows attribue tout seul une lettre au clone mis en ligne.
- Un volume monté interdit l'écriture brute dans sa zone → Clear-Disk d'abord.
- Ne jamais démarrer avec source et clone branchés (mêmes GUID → collision de signature).
