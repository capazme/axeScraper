import logging
import subprocess
from .config import EMAIL_CONFIG
from .logging_config import get_logger
from .output_manager import OutputManager
from utils.config_manager import get_config_manager

config_manager = get_config_manager()
base_urls = config_manager.get_list("BASE_URLS")
real_domain = base_urls[0] if base_urls else None
if not real_domain:
    raise ValueError("No BASE_URLS configured in config.json")

logger = get_logger("email_sender", domain=real_domain)

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
        OutputManager.get_path('funnels', 'car_rent', 'step_7_checkout.html')
        ])