import logging
import subprocess
from .config import EMAIL_CONFIG
from .logging_config import get_logger

logger = get_logger("email_sender")

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
    send_email_report([
        "/home/ec2-user/axeScraper/output/locautorent_com/screenshots/funnels/account_creation/step_1_end.png",
        "/home/ec2-user/axeScraper/output/locautorent_com/screenshots/funnels/account_creation/step_1_start.png",
        "/home/ec2-user/axeScraper/output/locautorent_com/screenshots/funnels/account_creation/step_2_end.png",
        "/home/ec2-user/axeScraper/output/locautorent_com/screenshots/funnels/account_creation/step_2_start.png",
        "/home/ec2-user/axeScraper/output/locautorent_com/screenshots/funnels/account_creation/step_3_end.png",
        "/home/ec2-user/axeScraper/output/locautorent_com/screenshots/funnels/account_creation/step_3_start.png",
        "/home/ec2-user/axeScraper/output/locautorent_com/screenshots/funnels/account_creation/step_4_end.png",
        "/home/ec2-user/axeScraper/output/locautorent_com/screenshots/funnels/account_creation/step_4_start.png",
        "/home/ec2-user/axeScraper/output/locautorent_com/screenshots/funnels/account_creation/step_5_end.png",
        "/home/ec2-user/axeScraper/output/locautorent_com/screenshots/funnels/account_creation/step_5_start.png"
         ])