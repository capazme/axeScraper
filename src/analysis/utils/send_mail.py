import logging
import subprocess
from config import EMAIL_CONFIG
from logging_config import get_logger

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
        "/home/ec2-user/axeScraper/output/locautorent_com_auth/analysis_output/accessibility_report_locautorent_com_auth_concat.xlsx"
        ])