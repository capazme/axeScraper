#!/bin/bash
# run_complete_pipeline.sh
#
# Script per eseguire l'intero workflow: crawler multi-dominio + analisi accessibilità
#

# Colori per output
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Directory e impostazioni predefinite
CRAWLER_DIR="/home/ec2-user/axeScraper/src/crawler/hybrid_crawler"
ANALYZER_DIR="/home/ec2-user/axeScraper/src/analyzer"
OUTPUT_DIR="/home/ec2-user/axeScraper/output_crawler"
AXE_OUTPUT_DIR="/home/ec2-user/axeScraper/output_axe"

# Verifica e attiva l'ambiente virtuale
if [ -d "/home/ec2-user/axeScraper/.venv" ]; then
    source /home/ec2-user/axeScraper/.venv/bin/activate
    echo -e "${GREEN}Ambiente virtuale attivato: /home/ec2-user/axeScraper/.venv${NC}"
else
    echo -e "${RED}Ambiente virtuale non trovato. Uscita.${NC}"
    exit 1
fi

# Parametri da linea di comando
DOMAINS=${1:-"iper.it,esselunga.it"}
MAX_URLS_PER_DOMAIN=${2:-50}
MAX_URLS_FOR_ACCESSIBILITY=${3:-50}
HYBRID_MODE=${4:-"True"}

# Crea directory di output se non esistono
mkdir -p "$OUTPUT_DIR"
mkdir -p "$AXE_OUTPUT_DIR"

# Funzione per mostrare aiuto
show_help() {
    echo -e "${BLUE}Pipeline Completa: Crawler Multi-Dominio + Analisi Accessibilità${NC}"
    echo ""
    echo "Utilizzo: $0 [domini] [max_urls_per_dominio] [max_urls_per_accessibilità] [modalità_ibrida]"
    echo ""
    echo "Parametri:"
    echo "  [domini]                    - Lista di domini separati da virgola (default: iper.it,esselunga.it)"
    echo "  [max_urls_per_dominio]      - Numero massimo di URL per dominio per il crawler (default: 50)"
    echo "  [max_urls_per_accessibilità] - Numero massimo di URL per dominio per l'analisi (default: 50)"
    echo "  [modalità_ibrida]           - Usa Selenium+HTTP (True) o solo HTTP (False) (default: True)"
    echo ""
    exit 1
}

# Mostra aiuto se richiesto
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    show_help
fi

# --------------------------------------------------
# Fase 1: Esecuzione crawler multi-dominio
# --------------------------------------------------
echo -e "${BLUE}=== Fase 1: Esecuzione crawler multi-dominio ===${NC}"
echo -e "${YELLOW}Domini: $DOMAINS${NC}"
echo -e "${YELLOW}Max URL per dominio: $MAX_URLS_PER_DOMAIN${NC}"
echo ""

cd "$CRAWLER_DIR" || exit 1

# Esegue il crawler multi-dominio
CRAWLER_CMD="scrapy crawl multi_domain_spider \
  -a domains=\"$DOMAINS\" \
  -a max_urls_per_domain=$MAX_URLS_PER_DOMAIN \
  -a hybrid_mode=$HYBRID_MODE \
  -a selenium_threshold=30 \
  -a request_delay=0.5 \
  -s CONCURRENT_REQUESTS=16 \
  -s CONCURRENT_REQUESTS_PER_DOMAIN=8 \
  -s OUTPUT_DIR=$OUTPUT_DIR \
  -s JOBDIR=$OUTPUT_DIR/crawler_job \
  -s HTTPCACHE_ENABLED=True \
  -s LOG_LEVEL=INFO \
  -s PIPELINE_REPORT_FORMAT=all \
  --logfile=$OUTPUT_DIR/crawler_$(date +%Y%m%d_%H%M%S).log"

echo -e "${YELLOW}Esecuzione crawler con comando:${NC}"
echo "$CRAWLER_CMD"
echo ""

eval "$CRAWLER_CMD"

CRAWLER_EXIT_CODE=$?
if [ $CRAWLER_EXIT_CODE -ne 0 ]; then
    echo -e "${RED}Errore durante l'esecuzione del crawler (codice: $CRAWLER_EXIT_CODE)${NC}"
    echo -e "${YELLOW}Vedi il log per dettagli.${NC}"
    echo -e "${YELLOW}Continuazione con la fase 2 comunque...${NC}"
fi

# --------------------------------------------------
# Fase 2: Analisi accessibilità
# --------------------------------------------------
echo -e "${BLUE}=== Fase 2: Analisi accessibilità ===${NC}"
echo -e "${YELLOW}Max URL per dominio per analisi accessibilità: $MAX_URLS_FOR_ACCESSIBILITY${NC}"
echo ""

cd "$ANALYZER_DIR" || exit 1

# Genera lo script Python temporaneo con i parametri corretti
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
TEMP_SCRIPT="temp_analyzer_$TIMESTAMP.py"

cat > "$TEMP_SCRIPT" << PYEOF
import sys
import os
from axe_analysis import AxeAnalysis

def main():
    print("Avvio analisi accessibilità...")
    
    domains = "$DOMAINS"
    crawler_output_dir = "$OUTPUT_DIR"
    max_urls_per_domain = $MAX_URLS_FOR_ACCESSIBILITY
    
    # Domini di fallback in caso di problemi
    fallback_domains = domains.split(',')
    fallback_urls = [f"https://www.{d}" for d in fallback_domains]
    
    # Nome del report basato sui domini
    domain_prefix = '_'.join([d.replace('.', '_') for d in fallback_domains[:2]])
    if len(fallback_domains) > 2:
        domain_prefix += "_etc"
    
    excel_filename = os.path.join("$AXE_OUTPUT_DIR", f"accessibility_report_{domain_prefix}_{max_urls_per_domain}.xlsx")
    visited_file = os.path.join("$AXE_OUTPUT_DIR", f"visited_urls_{domain_prefix}.txt")
    
    analyzer = AxeAnalysis(
        crawler_output_dir=crawler_output_dir,
        domains=domains,
        max_urls_per_domain=max_urls_per_domain,
        fallback_urls=fallback_urls,
        pool_size=6,
        sleep_time=1.5,
        excel_filename=excel_filename,
        visited_file=visited_file,
        headless=True,
        resume=True,
        output_folder="$AXE_OUTPUT_DIR"
    )
    
    analyzer.start()
    print(f"Analisi completata. Report salvato in: {excel_filename}")

if __name__ == "__main__":
    main()
PYEOF

# Esegue lo script di analisi accessibilità
echo -e "${YELLOW}Esecuzione analisi accessibilità...${NC}"
python "$TEMP_SCRIPT"

AXE_EXIT_CODE=$?
rm "$TEMP_SCRIPT"  # Pulizia

if [ $AXE_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}Analisi accessibilità completata con successo!${NC}"
else
    echo -e "${RED}Errore durante l'analisi accessibilità (codice: $AXE_EXIT_CODE)${NC}"
fi

# --------------------------------------------------
# Conclusione
# --------------------------------------------------
echo ""
echo -e "${BLUE}=== Pipeline completa ===${NC}"
if [ $CRAWLER_EXIT_CODE -eq 0 ] && [ $AXE_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}Pipeline completata con successo!${NC}"
else
    echo -e "${YELLOW}Pipeline completata con alcuni errori.${NC}"
    [ $CRAWLER_EXIT_CODE -ne 0 ] && echo -e "${YELLOW}- Crawler: Codice errore $CRAWLER_EXIT_CODE${NC}"
    [ $AXE_EXIT_CODE -ne 0 ] && echo -e "${YELLOW}- Analisi accessibilità: Codice errore $AXE_EXIT_CODE${NC}"
fi

echo -e "${BLUE}Output:${NC}"
echo -e "- Output crawler: $OUTPUT_DIR"
echo -e "- Report accessibilità: $AXE_OUTPUT_DIR"