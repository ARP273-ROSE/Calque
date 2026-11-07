"""Le journal de reprise des tests vit dans un dossier jetable, jamais dans le profil."""
import os
import tempfile

os.environ.setdefault("CALQUE_DONNEES", tempfile.mkdtemp(prefix="calque-essais-"))
