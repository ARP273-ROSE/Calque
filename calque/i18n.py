"""Textes de Calque en français et en anglais, langue détectée automatiquement.

Règles (les mêmes que MountMonitor) :
* chaque clé existe dans les deux langues — un test l'exige ;
* les champs de format ({n}, {nom}…) sont les mêmes d'une langue à l'autre,
  sinon le texte lèverait une erreur à l'exécution, chez l'utilisateur ;
* une clé manquante retombe sur l'anglais, puis sur la clé elle-même :
  un texte non traduit est un défaut cosmétique, un bouton vide est une panne.

Ce module ne dépend pas de Qt : le moteur l'utilise aussi.
"""
from __future__ import annotations

import os
import sys

LANGUES = ("fr", "en")
_langue = None


def detecter() -> str:
    """Langue d'AFFICHAGE du système (pas celle des formats de date).

    Windows : GetUserDefaultUILanguage (la locale de format peut être
    britannique chez un francophone, et inversement). macOS : la liste
    AppleLanguages des préférences globales, lue sans lancer de commande.
    Linux : variables d'environnement.
    """
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var, "")
        if val and val not in ("C", "POSIX") and not val.startswith("C."):
            return "fr" if val.lower().startswith("fr") else "en"
    if sys.platform == "win32":
        try:
            import ctypes
            langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return "fr" if (langid & 0x3FF) == 0x0C else "en"
        except Exception:
            pass
    if sys.platform == "darwin":
        try:
            import plistlib
            from pathlib import Path
            chemin = Path.home() / "Library" / "Preferences" / ".GlobalPreferences.plist"
            with open(chemin, "rb") as f:
                langues = plistlib.load(f).get("AppleLanguages") or []
            if langues:
                return "fr" if str(langues[0]).lower().startswith("fr") else "en"
        except Exception:
            pass
    return "en"


def definir_langue(code: str | None) -> str:
    """Fixe la langue ('fr', 'en', ou None/'auto' pour la détection)."""
    global _langue
    _langue = code if code in LANGUES else detecter()
    return _langue


def langue() -> str:
    return _langue or definir_langue(None)


def tr(cle: str, **champs) -> str:
    textes = TEXTES.get(cle)
    if not textes:
        return cle
    modele = textes.get(langue()) or textes.get("en") or cle
    try:
        return modele.format(**champs) if champs else modele
    except (KeyError, IndexError, ValueError):
        return modele


def pluriel(n: int, cle_un: str, cle_plusieurs: str, **champs) -> str:
    return tr(cle_un if n == 1 else cle_plusieurs, n=n, **champs)


TEXTES: dict[str, dict[str, str]] = {
    # ---- fenêtre
    "app.sous_titre": {"fr": "Copier un disque — Windows compris — sur un disque plus grand, prêt à démarrer.",
                       "en": "Copy a disk — Windows included — to a larger disk, ready to boot."},
    "onglet.cloner": {"fr": "Cloner", "en": "Clone"},
    "onglet.apres": {"fr": "Après le clonage", "en": "After cloning"},
    "zone.disques": {"fr": "1. Les disques", "en": "1. The disks"},
    "zone.plan": {"fr": "2. Ce qui va se passer", "en": "2. What will happen"},
    "zone.lancer": {"fr": "3. Cloner", "en": "3. Clone"},
    "champ.source": {"fr": "Disque à copier (source) :", "en": "Disk to copy (source):"},
    "champ.cible": {"fr": "Disque qui reçoit la copie (cible) :", "en": "Disk receiving the copy (target):"},
    "bouton.actualiser": {"fr": "Actualiser la liste", "en": "Refresh the list"},
    "astuce.actualiser": {"fr": "Après avoir branché ou débranché un disque",
                          "en": "After plugging in or unplugging a disk"},
    "disque.aucun": {"fr": "(aucun disque)", "en": "(no disk)"},
    "disque.systeme": {"fr": "système en cours", "en": "running system"},
    "barre.source": {"fr": "Aujourd'hui", "en": "Today"},
    "barre.cible": {"fr": "Après", "en": "After"},
    "barre.libre": {"fr": "libre", "en": "free"},
    "nature.efi": {"fr": "EFI", "en": "EFI"},
    "nature.msr": {"fr": "réservée", "en": "reserved"},
    "nature.donnees": {"fr": "données", "en": "data"},
    "nature.recuperation": {"fr": "récupération", "en": "recovery"},
    "nature.linux": {"fr": "Linux", "en": "Linux"},
    "nature.fat32": {"fr": "FAT32", "en": "FAT32"},
    "nature.autre": {"fr": "autre", "en": "other"},
    "plan.resume": {
        "fr": "{n} partitions ({style}) copiées sur « {cible} ». Identifiants du disque conservés : "
              "Windows démarrera sur la copie sans réparation.",
        "en": "{n} partitions ({style}) copied to “{cible}”. Disk identifiers kept: "
              "Windows will boot from the copy with no repair."},
    "plan.deplacees": {
        "fr": "La partition de récupération est reportée en fin de disque : les {gain} gagnés se "
              "trouvent juste derrière {nom}, prêts à l'agrandir.",
        "en": "The recovery partition is moved to the end of the disk: the {gain} gained sit right "
              "after {nom}, ready to extend it."},
    "plan.gain": {"fr": "Espace libre ajouté derrière {nom} : {gain}.", "en": "Free space added after {nom}: {gain}."},
    "plan.choisir": {"fr": "Choisissez une source et une cible différentes.",
                     "en": "Choose a different source and target."},
    "plan.bloque": {"fr": "Clonage impossible :", "en": "Cloning is not possible:"},
    "plan.attention": {"fr": "À savoir :", "en": "Good to know:"},
    "option.verifier": {"fr": "Relire la cible pour vérifier la copie (recommandé, double la durée)",
                        "en": "Read the target back to check the copy (recommended, doubles the time)"},
    "option.deplacer": {"fr": "Reporter la partition de récupération en fin de disque (pour agrandir C:)",
                        "en": "Move the recovery partition to the end of the disk (to extend C:)"},
    "option.confirmer": {"fr": "Je sais que TOUT le contenu actuel de « {cible} » sera effacé.",
                         "en": "I understand that ALL the current content of “{cible}” will be erased."},
    "bouton.cloner": {"fr": "Cloner", "en": "Clone"},
    "bouton.annuler": {"fr": "Annuler", "en": "Cancel"},
    "etape.attente": {"fr": "Prêt.", "en": "Ready."},
    "etape.preparation": {"fr": "Préparation de la cible…", "en": "Preparing the target…"},
    "etape.cliche": {"fr": "Cliché instantané de {nom} (Windows continue de tourner)…",
                     "en": "Snapshot of {nom} (Windows keeps running)…"},
    "etape.analyse": {"fr": "Lecture de la place occupée…", "en": "Reading the used space…"},
    "etape.zones": {"fr": "Partition {numero} ({fs}) : {octets} à copier", "en": "Partition {numero} ({fs}): {octets} to copy"},
    "etape.copie": {"fr": "Copie", "en": "Copying"},
    "etape.verification": {"fr": "Vérification", "en": "Checking"},
    "etape.table": {"fr": "Écriture de la table de partitions…", "en": "Writing the partition table…"},
    "etape.fini": {"fr": "Terminé.", "en": "Done."},
    "etape.progres": {"fr": "{etape} : {fait} sur {total} — {debit}/s — reste {reste}",
                      "en": "{etape}: {fait} of {total} — {debit}/s — {reste} left"},
    "dlg.confirmer_titre": {"fr": "Dernière vérification", "en": "Last check"},
    "dlg.confirmer": {
        "fr": "Copier <b>{source}</b><br>sur <b>{cible}</b> ?<br><br><b>Point de non-retour :</b> tout ce que "
              "contient aujourd'hui le disque cible sera <b>définitivement effacé</b>. Le disque source, lui, "
              "ne sera pas touché.",
        "en": "Copy <b>{source}</b><br>to <b>{cible}</b>?<br><br><b>Point of no return:</b> everything the "
              "target disk holds today will be <b>permanently erased</b>. The source disk will not be touched."},
    "dlg.effacer": {"fr": "Effacer et cloner", "en": "Erase and clone"},
    "dlg.quitter_en_cours": {"fr": "Un clonage est en cours. L'interrompre ? Le disque cible restera vide.",
                             "en": "Cloning is in progress. Stop it? The target disk will be left empty."},
    "dlg.oui": {"fr": "Oui", "en": "Yes"},
    "dlg.non": {"fr": "Non", "en": "No"},
    "fin.titre": {"fr": "Clonage réussi", "en": "Cloning succeeded"},
    "fin.texte": {
        "fr": "<p>{copie} copiés{verifie} en {duree}.</p>{remarques}"
              "<p><b>Et maintenant :</b></p><ol>"
              "<li>Éteignez l'ordinateur.</li>"
              "<li>Mettez le nouveau disque à la place de l'ancien (ou débranchez l'ancien). "
              "<b>Ne démarrez pas avec les deux branchés</b> : ils portent les mêmes identifiants.</li>"
              "<li>Démarrez ; Windows s'ouvre comme avant.</li>"
              "<li>Relancez Calque, onglet <i>Après le clonage</i> : <b>Agrandir C:</b>.</li></ol>"
              "<p>Si le PC ne démarre pas : au démarrage, entrez dans le BIOS (touche Suppr ou F2) et choisissez "
              "« Windows Boot Manager » du nouveau disque en premier.</p>"
              "<p><b>Gardez l'ancien disque intact quelques jours</b>, rangé : c'est votre copie de secours tant que "
              "vous n'avez pas vérifié que tout marche sur le nouveau.</p>",
        "en": "<p>{copie} copied{verifie} in {duree}.</p>{remarques}"
              "<p><b>What next:</b></p><ol>"
              "<li>Shut the computer down.</li>"
              "<li>Put the new disk in place of the old one (or unplug the old one). "
              "<b>Do not start with both connected</b>: they carry the same identifiers.</li>"
              "<li>Start; Windows opens as before.</li>"
              "<li>Run Calque again, <i>After cloning</i> tab: <b>Extend C:</b>.</li></ol>"
              "<p>If the PC does not start: at power-on, enter the BIOS (Del or F2 key) and put the new disk's "
              "“Windows Boot Manager” first.</p>"
              "<p><b>Keep the old disk untouched for a few days</b>, put away: it is your safety copy until you "
              "have checked that everything works on the new one.</p>"},
    "fin.verifie": {"fr": " et vérifiés", "en": " and checked"},
    "fin.annule": {"fr": "Clonage interrompu. Le disque cible n'a pas encore de table : rien ne démarrera dessus par erreur. "
                         "« Reprendre » continuera là où il s'est arrêté.",
                   "en": "Cloning stopped. The target disk has no table yet: nothing will boot from it by mistake. "
                         "“Resume” will continue where it stopped."},
    "fin.echec": {"fr": "Le clonage a échoué.\n\n{detail}\n\nLe disque source n'a pas été modifié.",
                  "en": "Cloning failed.\n\n{detail}\n\nThe source disk was not modified."},
    "admin.requis": {
        "fr": "Calque doit être lancé en administrateur pour lire et écrire des disques entiers.",
        "en": "Calque must run as administrator to read and write whole disks."},
    "admin.linux": {
        "fr": "Lancez Calque avec sudo pour accéder aux disques : sudo calque",
        "en": "Run Calque with sudo to access the disks: sudo calque"},
    "inventaire.echec": {"fr": "Impossible de lister les disques :\n{detail}", "en": "Could not list the disks:\n{detail}"},
    # ---- robustesse : reprise, reconnexion, secteurs illisibles
    "plan.sante": {"fr": "Windows juge le disque source en mauvais état ({etat}). Sauvegardez vos documents AVANT de cloner.",
                   "en": "Windows rates the source disk as unhealthy ({etat}). Back up your documents BEFORE cloning."},
    "plan.estimation": {"fr": "À copier : environ {octets}. Durée estimée : entre {min} et {max}.",
                        "en": "To copy: about {octets}. Estimated time: between {min} and {max}."},
    "option.doux": {"fr": "Ménager le boîtier USB : copie bridée à 200 Mo/s (plus lente, mais il chauffe moins et décroche moins)",
                    "en": "Go easy on the USB enclosure: copy capped at 200 MB/s (slower, but it heats less and drops out less)"},
    "reprise.titre": {"fr": "Un clonage a été interrompu le {date} ({pourcent} % copiés).",
                      "en": "A cloning was interrupted on {date} ({pourcent} % copied)."},
    "reprise.memes": {"fr": "Il reprendra là où il s'était arrêté.", "en": "It will resume where it stopped."},
    "reprise.autres": {"fr": "Pour le reprendre, choisissez les mêmes disques (rebranchez le nouveau disque, puis « Actualiser la liste »).",
                       "en": "To resume it, choose the same disks (plug the new disk back in, then “Refresh the list”)."},
    "reprise.reprendre": {"fr": "Reprendre", "en": "Resume"},
    "reprise.abandonner": {"fr": "Oublier ce clonage", "en": "Forget this cloning"},
    "reprise.abandon_confirmer": {"fr": "Oublier le clonage interrompu ? Il faudra tout recommencer.",
                                  "en": "Forget the interrupted cloning? Everything will have to start again."},
    "etape.cible_attente": {"fr": "Le nouveau disque a décroché… attente de son retour (jusqu'à 1 min 30)",
                            "en": "The new disk dropped out… waiting for it to come back (up to 1 min 30)"},
    "etape.cible_revenue": {"fr": "Le nouveau disque est revenu, la copie continue.", "en": "The new disk is back, copying continues."},
    "clone.cible_perdue": {
        "fr": "Le nouveau disque s'est déconnecté et n'est pas revenu.\n\nRien n'est perdu, la copie déjà faite est gardée.\n"
              "1. Débranchez le boîtier USB, attendez une minute qu'il refroidisse.\n"
              "2. Rebranchez-le sur un port à l'arrière du PC, posé à plat, à l'air.\n"
              "3. Cliquez sur « Actualiser la liste », puis sur « Reprendre ».",
        "en": "The new disk disconnected and did not come back.\n\nNothing is lost, the copy done so far is kept.\n"
              "1. Unplug the USB enclosure, wait a minute for it to cool down.\n"
              "2. Plug it back into a port at the back of the PC, lying flat, in the open air.\n"
              "3. Click “Refresh the list”, then “Resume”."},
    "clone.cible_erreur": {"fr": "Le nouveau disque refuse l'écriture :\n{detail}", "en": "The new disk refuses writing:\n{detail}"},
    "clone.source_illisible": {
        "fr": "Une zone du disque source est illisible (position {position}).\n\nVotre disque actuel est peut-être en train "
              "de s'abîmer. Commencez par copier vos documents importants ailleurs.\n\nVous pouvez ensuite continuer le "
              "clonage malgré tout : les zones illisibles seront remplies de zéros (un fichier pourra être abîmé sur le clone).",
        "en": "An area of the source disk cannot be read (position {position}).\n\nYour current disk may be failing. Start by "
              "copying your important documents elsewhere.\n\nYou can then continue cloning anyway: unreadable areas will "
              "be filled with zeros (a file may be damaged on the clone)."},
    "clone.continuer_malgre": {"fr": "Continuer malgré tout", "en": "Continue anyway"},
    "clone.arreter": {"fr": "Arrêter", "en": "Stop"},
    "clone.cliche_perdu": {
        "fr": "Le cliché de Windows pris au début du clonage n'existe plus (redémarrage, nettoyage du disque). "
              "La reprise est impossible : il faut recommencer de zéro.",
        "en": "The Windows snapshot taken when cloning started no longer exists (restart, disk clean-up). "
              "Resuming is not possible: start again from scratch."},
    "clone.reprise_impossible": {"fr": "Ce clonage ne peut pas être repris (disques ou contenu différents). Recommencez de zéro.",
                                 "en": "This cloning cannot be resumed (different disks or content). Start again from scratch."},
    "fin.illisibles": {"fr": "<p style='color:#A33'><b>{n} secteur(s) illisible(s)</b> ont été remplacés par des zéros. "
                             "Faites vérifier le disque (chkdsk C: /f au premier démarrage).</p>",
                       "en": "<p style='color:#A33'><b>{n} unreadable sector(s)</b> were replaced with zeros. "
                             "Have the disk checked (chkdsk C: /f on first start).</p>"},
    "fin.reconnexions": {"fr": "<p>Le boîtier USB a décroché {n} fois ; Calque a repris tout seul.</p>",
                         "en": "<p>The USB enclosure dropped out {n} time(s); Calque carried on by itself.</p>"},
    "fin.reprise": {"fr": "Clonage interrompu. Ce qui est copié est gardé : « Reprendre » continuera là où il s'est arrêté.",
                    "en": "Cloning stopped. What was copied is kept: “Resume” will continue where it stopped."},
    "dlg.avant": {
        "fr": "<p><b>Avant de lancer :</b></p><ul>"
              "<li>vos documents importants sont sauvegardés ailleurs ;</li>"
              "<li>portable : branché sur le secteur ;</li>"
              "<li>boîtier USB : posé à plat, à l'air, sur un port à l'arrière du PC ;</li>"
              "<li>Windows Update : suspendez les mises à jour (Paramètres → Windows Update → Suspendre), "
              "un redémarrage automatique interromprait la copie.</li></ul>"
              "<p>La mise en veille de Windows est bloquée pendant la copie. Ne débranchez rien tant que la "
              "barre n'est pas au bout.</p>",
        "en": "<p><b>Before starting:</b></p><ul>"
              "<li>your important documents are backed up elsewhere;</li>"
              "<li>laptop: plugged into the mains;</li>"
              "<li>USB enclosure: lying flat, in the open air, on a port at the back of the PC;</li>"
              "<li>Windows Update: pause updates (Settings → Windows Update → Pause), an automatic restart "
              "would interrupt the copy.</li></ul>"
              "<p>Windows sleep is blocked during the copy. Do not unplug anything until the bar reaches the "
              "end.</p>"},
    "dlg.reprendre_maintenant": {"fr": "J'ai rebranché : reprendre", "en": "Plugged back in: resume"},
    # ---- alertes (recherches : causes connues d'échec d'un clonage)
    "niveau.bloque": {"fr": "IMPOSSIBLE", "en": "NOT POSSIBLE"},
    "niveau.important": {"fr": "ATTENTION", "en": "WARNING"},
    "niveau.info": {"fr": "À SAVOIR", "en": "GOOD TO KNOW"},
    "plan.cible_non_vide": {
        "fr": "Le disque cible n'est PAS vide : il contient {n} partition(s), {taille} en tout. Tout sera effacé, "
              "sans retour possible. Vérifiez que c'est bien le nouveau disque et que rien dessus ne vous manquera.",
        "en": "The target disk is NOT empty: it holds {n} partition(s), {taille} in all. Everything will be erased, "
              "with no way back. Check that it is really the new disk and that you will not miss anything on it."},
    "plan.batterie": {"fr": "L'ordinateur est sur batterie. Branchez-le sur le secteur : une coupure en pleine copie oblige à reprendre.",
                      "en": "The computer is on battery. Plug it into the mains: a power cut mid-copy means resuming."},
    "plan.place_cliche": {
        "fr": "Il ne reste que {libre} de libre sur {nom}. Le cliché de Windows y garde ce qui change pendant la copie ; "
              "s'il manque de place, Windows le supprime et il faut tout recommencer. Libérez de la place, et évitez "
              "les gros téléchargements pendant le clonage.",
        "en": "Only {libre} is free on {nom}. The Windows snapshot keeps there what changes during the copy; if it runs "
              "out of space, Windows deletes it and everything has to start again. Free some space, and avoid large "
              "downloads during cloning."},
    "plan.place_cliche_bloque": {
        "fr": "Trop peu de place libre sur {nom} ({libre}) pour le cliché de Windows. Libérez au moins quelques Go "
              "(Nettoyage de disque, corbeille, téléchargements), puis « Actualiser la liste ».",
        "en": "Too little free space on {nom} ({libre}) for the Windows snapshot. Free at least a few GB (Disk Cleanup, "
              "recycle bin, downloads), then “Refresh the list”."},
    "plan.demarrage_rapide": {
        "fr": "Windows doit avoir été éteint COMPLÈTEMENT avant de démarrer sur la clé Linux (démarrage rapide désactivé, "
              "ou Maj enfoncée en cliquant sur Arrêter). Sinon la copie emporte une session en veille prolongée.",
        "en": "Windows must have been shut down COMPLETELY before starting from the Linux stick (fast startup off, or "
              "Shift held while clicking Shut down). Otherwise the copy carries a hibernated session."},
    "clone.cliche_disparu": {
        "fr": "Windows a supprimé le cliché pendant la copie (le plus souvent : plus assez de place libre sur C:). "
              "La copie ne peut pas être reprise. Libérez de la place sur C:, puis recommencez de zéro.",
        "en": "Windows deleted the snapshot during the copy (most often: not enough free space on C:). The copy cannot "
              "be resumed. Free some space on C:, then start again from scratch."},
    "clone.cliche_refuse": {
        "fr": "Windows refuse de prendre le cliché de {nom} (code {detail}). Vérifiez que le service « Cliché "
              "instantané des volumes » n'est pas désactivé et qu'il reste de la place sur {nom} ; sinon, clonez "
              "depuis une clé Linux.",
        "en": "Windows refuses to take the snapshot of {nom} (code {detail}). Check that the “Volume Shadow Copy” "
              "service is not disabled and that {nom} has free space; otherwise, clone from a Linux stick."},
    "plan.ntfs_sale": {
        "fr": "Windows a marqué {nom} « à vérifier » (erreurs du système de fichiers). Copier ces erreurs ne les "
              "répare pas : lancez d'abord « chkdsk {nom} /f » dans un terminal administrateur, redémarrez, puis "
              "revenez ici. (Les outils libres ntfsclone et partclone refusent eux aussi un tel volume.)",
        "en": "Windows flagged {nom} as “needs checking” (file system errors). Copying those errors does not fix "
              "them: first run “chkdsk {nom} /f” in an administrator terminal, restart, then come back. (The free "
              "tools ntfsclone and partclone also refuse such a volume.)"},
    "fin.controles": {"fr": "<p>Contrôle par des outils libres : {resultat}</p>", "en": "<p>Check by free tools: {resultat}</p>"},
    "fin.controle_ok": {"fr": "tout est bon", "en": "all good"},
    "fin.controle_ko": {"fr": "<b style='color:#A33'>problème signalé par {outil}</b>", "en": "<b style='color:#A33'>problem reported by {outil}</b>"},
    "apres.disque_actuel": {"fr": "Windows a démarré sur : {disque}. Vérifiez que c'est bien le NOUVEAU disque.",
                            "en": "Windows started from: {disque}. Check that it is the NEW disk."},
    # ---- après le clonage
    "apres.intro": {
        "fr": "<p>À faire <b>une fois démarré sur le nouveau disque</b>.</p>"
              "<p>La copie a gardé à C: sa taille d'origine ; l'espace gagné est juste derrière. "
              "<b>Agrandir C:</b> le lui donne, sans redémarrer ni rien effacer.</p>",
        "en": "<p>To do <b>once started from the new disk</b>.</p>"
              "<p>The copy kept C: at its original size; the space gained is right after it. "
              "<b>Extend C:</b> gives it that space, without restarting or erasing anything.</p>"},
    "apres.etat": {"fr": "C: : {taille} aujourd'hui, {maximum} possibles.", "en": "C: {taille} today, {maximum} possible."},
    "apres.etat_inconnu": {"fr": "État de C: inconnu.", "en": "State of C: unknown."},
    "apres.deja": {"fr": "C: occupe déjà toute la place disponible.", "en": "C: already uses all the available space."},
    "apres.agrandir": {"fr": "Agrandir C:", "en": "Extend C:"},
    "apres.winre": {"fr": "Réparer l'environnement de récupération", "en": "Repair the recovery environment"},
    "apres.winre_astuce": {
        "fr": "Après le déplacement de la partition de récupération : désactive puis réactive WinRE (reagentc)",
        "en": "After the recovery partition was moved: turns WinRE off then on again (reagentc)"},
    "apres.fait": {"fr": "C: agrandi : {taille}.", "en": "C: extended: {taille}."},
    "apres.echec": {"fr": "L'opération a échoué :\n{detail}", "en": "The operation failed:\n{detail}"},
    "apres.windows": {"fr": "Ces opérations ne concernent que Windows.", "en": "These operations only apply to Windows."},
    "apres.linux_conseil": {
        "fr": "<p>Sous Linux, après le clonage, éteignez, mettez le nouveau disque à la place de l'ancien, "
              "démarrez Windows puis utilisez cet onglet depuis Calque pour Windows — ou, dans Windows, "
              "<i>Gestion des disques</i> → clic droit sur C: → <i>Étendre le volume</i>.</p>",
        "en": "<p>On Linux, after cloning, shut down, put the new disk in place of the old one, start "
              "Windows and use this tab from Calque for Windows — or, in Windows, <i>Disk Management</i> "
              "→ right-click C: → <i>Extend Volume</i>.</p>"},
    # ---- erreurs du moteur
    "table.secteur_inconnu": {"fr": "Taille de secteur non prise en charge ({taille} octets).",
                              "en": "Unsupported sector size ({taille} bytes)."},
    "table.vide": {"fr": "Le disque source n'a pas de table de partitions.", "en": "The source disk has no partition table."},
    "table.etendue": {"fr": "Partitions étendues (MBR) non prises en charge.", "en": "Extended (MBR) partitions are not supported."},
    "table.gpt_entete": {"fr": "En-tête GPT illisible sur la source.", "en": "Unreadable GPT header on the source."},
    "table.gpt_crc": {"fr": "Table GPT de la source abîmée (somme de contrôle fausse).",
                      "en": "Damaged GPT on the source (wrong checksum)."},
    "table.hors_disque": {"fr": "La partition {numero} dépasse la fin du disque.", "en": "Partition {numero} goes past the end of the disk."},
    "table.chevauchement": {"fr": "La partition {numero} en chevauche une autre.", "en": "Partition {numero} overlaps another one."},
    "table.dynamique": {"fr": "Disque dynamique ou Espaces de stockage : non pris en charge.",
                        "en": "Dynamic disk or Storage Spaces: not supported."},
    "table.cible_trop_petite": {"fr": "La cible ({cible}) est trop petite : il faut au moins {besoin}.",
                                "en": "The target ({cible}) is too small: at least {besoin} is needed."},
    "plan.meme_disque": {"fr": "La source et la cible sont le même disque.", "en": "The source and the target are the same disk."},
    "plan.cible_systeme": {"fr": "« {disque} » porte le système en cours : il ne peut pas être la cible.",
                           "en": "“{disque}” holds the running system: it cannot be the target."},
    "plan.secteurs": {
        "fr": "Secteurs de {source} octets sur la source, {cible} sur la cible. Certains boîtiers USB "
              "présentent le disque en secteurs de 4096 octets : une copie faite ainsi ne démarre plus une "
              "fois le disque monté dans le PC. Branchez la cible autrement (adaptateur SATA/NVMe interne, "
              "autre boîtier) ou clonez sous Linux avec le disque monté à l'intérieur.",
        "en": "{source}-byte sectors on the source, {cible} on the target. Some USB enclosures present the "
              "disk with 4096-byte sectors: a copy made that way no longer boots once the disk is installed in "
              "the PC. Connect the target another way (internal SATA/NVMe, another enclosure) or clone on Linux "
              "with the disk installed inside."},
    "plan.cible_lecture_seule": {"fr": "La cible est en lecture seule : Calque la remettra en écriture.",
                                 "en": "The target is read-only: Calque will make it writable."},
    "plan.bitlocker": {
        "fr": "Un volume est chiffré par BitLocker. Déchiffrez-le d'abord (Paramètres → Chiffrement de "
              "l'appareil, ou « manage-bde -off C: »), attendez la fin, puis relancez.",
        "en": "A volume is encrypted with BitLocker. Decrypt it first (Settings → Device encryption, or "
              "“manage-bde -off C:”), wait until it finishes, then try again."},
    "plan.cible_occupee": {"fr": "La cible contient des volumes ({volumes}) : ils seront effacés.",
                           "en": "The target holds volumes ({volumes}): they will be erased."},
    "plan.cible_usb": {
        "fr": "La cible est branchée en USB : c'est bien pour copier, mais Windows ne démarre pas depuis "
              "l'USB. Montez ensuite le disque dans le PC à la place de l'ancien.",
        "en": "The target is connected over USB: fine for copying, but Windows does not boot from USB. "
              "Install the disk in the PC in place of the old one afterwards."},
    "plan.mbr_2to": {"fr": "Disque MBR : au-delà de 2 To, l'espace ne sera pas utilisable.",
                     "en": "MBR disk: space beyond 2 TB will not be usable."},
    "plan.source_montee": {
        "fr": "Des partitions de la source sont montées en écriture ({points}). Sous Linux, démontez-les "
              "(ou démarrez sur une clé USB) : sans cliché, elles changeraient pendant la copie.",
        "en": "Partitions of the source are mounted read-write ({points}). On Linux, unmount them (or boot "
              "from a USB stick): without a snapshot they would change during the copy."},
    "plan.cible_montee": {"fr": "Des partitions de la cible sont montées : démontez-les.",
                          "en": "Partitions of the target are mounted: unmount them."},
    "plan.volume_sans_cliche": {
        "fr": "{nom} ({fs}) ne peut pas être figé par un cliché : il sera copié tel quel. Évitez d'y écrire pendant le clonage.",
        "en": "{nom} ({fs}) cannot be frozen by a snapshot: it is copied as is. Avoid writing to it during cloning."},
    "plan.impossible": {"fr": "Le plan de clonage n'est pas réalisable.", "en": "The cloning plan cannot be carried out."},
    "clone.cible_changee": {"fr": "Le disque cible a changé depuis le choix (débranché ou remplacé). Actualisez la liste.",
                            "en": "The target disk changed since it was chosen (unplugged or replaced). Refresh the list."},
    "clone.verification": {"fr": "La relecture a trouvé {blocs} bloc(s) différent(s) : la cible ou sa liaison USB n'est pas fiable.",
                           "en": "Reading back found {blocs} different block(s): the target or its USB link is not reliable."},
    "acces.refuse": {"fr": "Accès refusé à {chemin} (droits d'administrateur ?).\n{detail}",
                     "en": "Access denied to {chemin} (administrator rights?).\n{detail}"},
    "acces.ouverture": {"fr": "Impossible d'ouvrir {chemin}.\n{detail}", "en": "Could not open {chemin}.\n{detail}"},
    "acces.lecture": {"fr": "Erreur de lecture sur {chemin}.\n{detail}", "en": "Read error on {chemin}.\n{detail}"},
    "acces.ecriture": {"fr": "Erreur d'écriture sur {chemin}.\n{detail}", "en": "Write error on {chemin}.\n{detail}"},
    "acces.position": {"fr": "Erreur de positionnement sur {chemin}.\n{detail}", "en": "Seek error on {chemin}.\n{detail}"},
    "acces.ioctl": {"fr": "Le système a refusé une commande sur {chemin}.\n{detail}",
                    "en": "The system refused a command on {chemin}.\n{detail}"},
    "acces.powershell": {"fr": "Une commande Windows a échoué :\n{detail}", "en": "A Windows command failed:\n{detail}"},
    "acces.inventaire": {"fr": "Inventaire des disques impossible :\n{detail}", "en": "Could not list the disks:\n{detail}"},
    # ---- ligne de commande
    "cli.description": {"fr": "Calque — cloner un disque sur un disque plus grand.",
                        "en": "Calque — clone a disk to a larger disk."},
    "cli.plan": {"fr": "Plan :", "en": "Plan:"},
    "cli.confirmer": {"fr": "Tout le contenu de {cible} sera effacé. Tapez OUI pour continuer : ",
                      "en": "All the content of {cible} will be erased. Type YES to continue: "},
    "cli.mot": {"fr": "OUI", "en": "YES"},
    "cli.abandon": {"fr": "Abandon.", "en": "Aborted."},
    "cli.introuvable": {"fr": "Disque introuvable : {nom}", "en": "Disk not found: {nom}"},
    # ---- menus, aide, kit
    "menu.fichier": {"fr": "&Fichier", "en": "&File"},
    "menu.quitter": {"fr": "Quitter", "en": "Quit"},
    "menu.langue": {"fr": "&Langue", "en": "&Language"},
    "menu.langue.auto": {"fr": "Automatique (langue du système)", "en": "Automatic (system language)"},
    "menu.langue.redemarrer": {"fr": "La nouvelle langue s'appliquera au prochain démarrage de Calque.",
                               "en": "The new language will apply the next time Calque starts."},
    "menu.aide": {"fr": "&Aide", "en": "&Help"},
    "menu.manuel": {"fr": "Manuel (PDF)", "en": "User guide (PDF)"},
    "menu.mode_emploi": {"fr": "Mode d'emploi rapide", "en": "Quick help"},
    "menu.maj": {"fr": "Rechercher une mise à jour", "en": "Check for updates"},
    "menu.signaler": {"fr": "Signaler un problème…", "en": "Report a problem…"},
    "menu.rapports_auto": {"fr": "Envoi automatique des rapports d'incident", "en": "Send error reports automatically"},
    "menu.a_propos": {"fr": "À propos", "en": "About"},
    "aide.titre": {"fr": "Mode d'emploi", "en": "Quick help"},
    "aide.texte": {
        "fr": "<h3>Calque en trois gestes</h3>"
              "<ol><li>Branchez le nouveau disque (boîtier USB ou à l'intérieur).</li>"
              "<li>Source = le disque actuel, cible = le nouveau. Lisez le plan.</li>"
              "<li>Cochez la case d'effacement, puis <b>Cloner</b>.</li></ol>"
              "<p>Sous Windows, Calque copie le disque <b>en service</b> grâce à un cliché instantané : vous "
              "pouvez continuer à travailler, mais ce qui change pendant la copie ne sera pas sur le clone.</p>"
              "<p>Ensuite : remplacez l'ancien disque par le nouveau, démarrez, et utilisez l'onglet "
              "<i>Après le clonage</i>. Le manuel complet est dans le menu <i>Aide</i> (F1).</p>",
        "en": "<h3>Calque in three steps</h3>"
              "<ol><li>Connect the new disk (USB enclosure or inside).</li>"
              "<li>Source = the current disk, target = the new one. Read the plan.</li>"
              "<li>Tick the erase box, then <b>Clone</b>.</li></ol>"
              "<p>On Windows, Calque copies the disk <b>while in use</b> through a snapshot: you can keep "
              "working, but what changes during the copy will not be on the clone.</p>"
              "<p>Then: replace the old disk with the new one, start, and use the <i>After cloning</i> tab. "
              "The full user guide is in the <i>Help</i> menu (F1).</p>"},
    "a_propos.texte": {
        "fr": "<b>Calque {version}</b><br>Cloner un disque — Windows compris — sur un disque plus grand.<br><br>"
              "<i>Calque</i> : la copie fidèle d'un dessin, trait pour trait.<br><br>"
              "Tables GPT et MBR recopiées identifiants compris ; seuls les blocs occupés des volumes NTFS sont "
              "copiés ; chaque bloc est relu et comparé. Le disque source n'est jamais modifié.<br><br>"
              "Polices : Source Sans 3 et EB Garamond (SIL Open Font License).",
        "en": "<b>Calque {version}</b><br>Clone a disk — Windows included — to a larger disk.<br><br>"
              "<i>Calque</i>: French for a tracing, a faithful line-for-line copy of a drawing.<br><br>"
              "GPT and MBR tables copied with their identifiers; only the used blocks of NTFS volumes are "
              "copied; every block is read back and compared. The source disk is never modified.<br><br>"
              "Fonts: Source Sans 3 and EB Garamond (SIL Open Font License)."},
    "manuel.absent": {"fr": "Le manuel est introuvable dans le dossier du programme.",
                      "en": "The user guide could not be found in the program folder."},
    "accord.titre": {"fr": "Envoyer automatiquement un rapport si Calque rencontre un problème ?",
                     "en": "Send a report automatically if Calque runs into a problem?"},
    "accord.texte": {
        "fr": "Le rapport contient la version du programme et du système et l'erreur rencontrée. "
              "Votre nom d'utilisateur est masqué. Vous pourrez changer d'avis dans le menu Aide.",
        "en": "The report contains the program and system versions and the error. "
              "Your user name is hidden. You can change your mind in the Help menu."},
    "maj.titre": {"fr": "Mise à jour", "en": "Update"},
    "maj.recherche": {"fr": "Recherche d'une mise à jour…", "en": "Checking for updates…"},
    "maj.a_jour": {"fr": "Calque {version} est à jour.", "en": "Calque {version} is up to date."},
    "maj.dispo": {"fr": "La version {nouvelle} est disponible (vous avez la {version}).",
                  "en": "Version {nouvelle} is available (you have {version})."},
    "maj.installer": {"fr": "Installer maintenant", "en": "Install now"},
    "maj.page": {"fr": "Ouvrir la page", "en": "Open the page"},
    "maj.plus_tard": {"fr": "Plus tard", "en": "Later"},
    "maj.telechargement": {"fr": "Téléchargement de la mise à jour…", "en": "Downloading the update…"},
    "maj.verrou": {"fr": "Un fichier de Calque est en cours d'utilisation : fermez les autres fenêtres de Calque et réessayez.",
                   "en": "A Calque file is in use: close the other Calque windows and try again."},
    "maj.echec": {"fr": "La mise à jour a échoué : {erreur}", "en": "The update failed: {erreur}"},
    "maj.redemarre": {"fr": "Mise à jour installée : Calque va redémarrer.", "en": "Update installed: Calque will now restart."},
    "maj.pas_pendant": {"fr": "Pas de mise à jour pendant un clonage.", "en": "No update while cloning."},
    "signal.titre": {"fr": "Signaler un problème", "en": "Report a problem"},
    "signal.invite": {"fr": "Décrivez ce qui s'est passé :", "en": "Describe what happened:"},
    "signal.exemple": {"fr": "Par exemple : source SSD 500 Go, cible 1 To en boîtier USB, le message suivant est apparu…",
                       "en": "For example: 500 GB SSD source, 1 TB target in a USB enclosure, this message appeared…"},
    "signal.note": {"fr": "Le message part avec la version de Calque, du système et la liste des disques (modèles, tailles). "
                          "Votre nom d'utilisateur est masqué.",
                    "en": "The message is sent with the Calque and system versions and the list of disks (models, sizes). "
                          "Your user name is hidden."},
    "signal.envoyer": {"fr": "Envoyer", "en": "Send"},
    "signal.merci": {"fr": "Merci", "en": "Thank you"},
    "signal.parti": {"fr": "Merci, le signalement est parti.", "en": "Thank you, the report was sent."},
    "signal.local": {"fr": "Pas de réseau : le signalement a été enregistré ici :\n{chemin}",
                     "en": "No network: the report was saved here:\n{chemin}"},
    "demarrage.echec": {"fr": "Le programme n'a pas pu démarrer.\n\n{erreur}\n\nDétails enregistrés dans :\n{chemin}",
                        "en": "The program could not start.\n\n{erreur}\n\nDetails saved in:\n{chemin}"},
}


def message(erreur) -> str:
    """Texte d'une erreur du moteur (clé + champs) dans la langue de l'interface."""
    cle = getattr(erreur, "cle", None)
    if cle:
        return tr(cle, **getattr(erreur, "champs", {}))
    return f"{type(erreur).__name__}: {erreur}"


def duree(secondes: float, approx: bool = False) -> str:
    if approx:                      # estimation : arrondie à 5 minutes
        m = max(5, int(round(secondes / 300.0)) * 5)
        return f"{m // 60} h {m % 60:02d}" if m >= 60 else f"{m} min"
    s = int(secondes)
    if s >= 3600:
        return f"{s // 3600} h {s % 3600 // 60:02d}"
    if s >= 60:
        return f"{s // 60} min {s % 60:02d} s"
    return f"{s} s"
