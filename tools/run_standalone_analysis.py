import sys
import os
import logging
from pathlib import Path
import re

# Aggiungi la root del progetto a sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Importa l'analyzer e OutputManager
from src.analysis.report_analysis import AccessibilityAnalyzer
from src.utils.output_manager import OutputManager
from src.utils.config import OUTPUT_ROOT
from src.utils.config_manager import get_config_manager


def slug_from_filename(filename):
    # Usa solo il nome senza estensione, sostituisci caratteri non alfanumerici
    base = Path(filename).stem
    return re.sub(r'[^\w\-]+', '_', base.lower())


def main():
    if len(sys.argv) < 2:
        print("Usage: python run_standalone_analysis.py <input_excel_path>")
        sys.exit(1)

    input_excel = sys.argv[1]
    if not os.path.exists(input_excel):
        print(f"File not found: {input_excel}")
        sys.exit(2)

    # Determina la cartella di output e lo slug dominio
    input_path = Path(input_excel)
    output_dir = input_path.parent
    domain_slug = "nortbeachwear_com"

    # Setup OutputManager per questa run
    config_manager = get_config_manager()
    base_urls = config_manager.get_list("BASE_URLS")
    real_domain = base_urls[0] if base_urls else domain_slug
    if not real_domain:
        raise ValueError("No BASE_URLS configured in config.json")
    domain_slug = config_manager.domain_to_slug(real_domain)
    output_manager = OutputManager(base_dir=output_dir, domain=real_domain, create_dirs=True)

    # Setup logging su file e console
    log_file = output_manager.get_path('logs', f'standalone_analysis_{domain_slug}.log')
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    logger = logging.getLogger("standalone_analysis")
    logger.info(f"Avvio analisi standalone su: {input_excel}")

    # Esegui l'analisi
    analyzer = AccessibilityAnalyzer(output_manager=output_manager, log_level=logging.INFO)
    report_path = analyzer.run_analysis(input_excel=str(input_path))
    logger.info(f"Analisi completata. Report generato: {report_path}")

if __name__ == "__main__":
    main() 