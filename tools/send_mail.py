import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
import subprocess
from config import EMAIL_CONFIG
from logging_config import get_logger
from src.utils.output_manager import OutputManager

logger = get_logger("email_sender")

def send_email_report(files_to_send, recipient_email=EMAIL_CONFIG["recipient_email"]):
    """
    Invia una email con i file specificati come allegati.
    :param files_to_send: lista di percorsi file da allegare
    :param recipient_email: destinatario (default da config)
    """
    attachments = " ".join([f'-a "{f}"' for f in files_to_send])
    command = f'echo "{EMAIL_CONFIG["subject"]}" | {EMAIL_CONFIG["mutt_command"]} "{EMAIL_CONFIG["body"]}" {attachments} -- {recipient_email}'
    logger.info("Invio email con il report: %s", command)
    result = subprocess.run(command, shell=True)
    if result.returncode == 0:
        logger.info("Email inviata con successo.")
    else:
        logger.error("Errore nell'invio dell'email.")

if __name__ == "__main__":
    # Inserisci qui i file che vuoi inviare come allegati
    files_to_send = [
        "/home/ec2-user/axeScraper/output/test_locautorent_com/analysis_output/final_analysis_test_locautorent_com_backup_20250619_122011.xlsx"
    ]
    if not files_to_send:
        logger.warning("Nessun file specificato per l'invio. Modifica 'files_to_send' con i file desiderati.")
    else:
        send_email_report(files_to_send)