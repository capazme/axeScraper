import logging
import subprocess
from .config import EMAIL_CONFIG

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)

def send_email_report(excel_files, recipient_email=EMAIL_CONFIG["recipient_email"]):
    
    # Costruisci l'elenco degli allegati
    attachments = " ".join([f'-a "{f}"' for f in excel_files])
    command = f'echo "{EMAIL_CONFIG["subject"]}" | {EMAIL_CONFIG["mutt_command"]} "{EMAIL_CONFIG["body"]}" {attachments} -- {recipient_email}'
    logger.info("Invio email con il report: %s", command)
    result = subprocess.run(command, shell=True)
    if result.returncode == 0:
        logger.info("Email inviata con successo.")
    else:
        logger.error("Errore nell'invio dell'email.")
        
if __name__ == "__main__":
    send_email_report(["/home/ec2-user/axeScraper/output/locautorent_com/markdown_output/site_locauto_v2.md", "/home/ec2-user/axeScraper/save/locauto/site_locauto_v1.md"])