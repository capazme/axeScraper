#!/bin/bash
# run_fresh.sh
#
# Script per eseguire il crawler multi-dominio ripartendo da zero
# (senza utilizzare cache o stati precedenti)
#

# Colori per output
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Funzione di aiuto
show_help() {
    echo -e "${BLUE}MultiDomain Crawler - Avvio Pulito${NC}"
    echo ""
    echo "Utilizzo: $0 [domini] [max_urls_per_dominio] [modalità_ibrida] [modalità_output]"
    echo ""
    echo "Parametri:"
    echo "  [domini]              - Lista di domini separati da virgola o file .txt/.json (default: iper.it)"
    echo "  [max_urls_per_dominio]- Numero massimo di URL per dominio (default: 50)"
    echo "  [modalità_ibrida]     - Usa Selenium+HTTP (True) o solo HTTP (False) (default: True)"
    echo "  [modalità_output]     - Formato output: all, markdown, json, csv (default: all)"
    echo ""
    echo "Nota: Questo script elimina tutte le cache e gli stati precedenti prima di avviare un nuovo crawl."
    echo ""
    exit 1
}

# Mostra aiuto se richiesto
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    show_help
fi

# Directory di base (directory corrente se non specificata)
BASE_DIR=$(dirname "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)")
cd "$BASE_DIR" || exit 1

# Attiva l'ambiente virtuale se esiste
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d "../venv" ]; then
    source ../venv/bin/activate
elif [ -d "/home/ec2-user/axeScraper/.venv" ]; then
    source /home/ec2-user/axeScraper/.venv/bin/activate
fi

# Configurazione predefinita
DOMAINS=${1:-"iper.it"}
MAX_URLS_PER_DOMAIN=${2:-50}
HYBRID_MODE=${3:-"True"}
OUTPUT_FORMAT=${4:-"all"}

# Rileva se il primo parametro è un file
if [[ -f "$DOMAINS" ]]; then
    DOMAINS_FILE=$DOMAINS
    DOMAINS=""
else
    DOMAINS_FILE=""
fi

# Configurazione percorsi
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
OUTPUT_DIR="output_crawler"
JOB_DIR="crawls/multi-job-fresh-$TIMESTAMP"
LOG_FILE="$OUTPUT_DIR/crawler_fresh_$TIMESTAMP.log"

# Crea directory se non esistono
mkdir -p "$OUTPUT_DIR"
mkdir -p "$JOB_DIR"

# Configurazione Scrapy avanzata
CONCURRENT_REQUESTS=16
CONCURRENT_PER_DOMAIN=8
REQUEST_DELAY=0.5
SELENIUM_THRESHOLD=30
DEPTH_LIMIT=8
LOG_LEVEL="INFO"

# Pulizia dello stato precedente
echo -e "${YELLOW}Pulizia stato precedente...${NC}"

# Determina i domini per eliminare i file di stato
if [ -n "$DOMAINS_FILE" ]; then
    if [[ "$DOMAINS_FILE" == *.json ]]; then
        # Estrazione domini da file JSON
        if command -v jq &> /dev/null; then
            DOMAIN_LIST=$(jq -r '.domains[]' "$DOMAINS_FILE" 2>/dev/null || echo "")
        else
            DOMAIN_LIST=""
            echo -e "${YELLOW}jq non trovato, impossibile estrarre domini dal file JSON${NC}"
        fi
    else
        # Assume un dominio per riga in file di testo
        DOMAIN_LIST=$(cat "$DOMAINS_FILE")
    fi
else
    # Usa domini dalla lista
    DOMAIN_LIST=${DOMAINS//,/ }
fi

# Elimina file di stato per ogni dominio
for domain in $DOMAIN_LIST; do
    if [ -n "$domain" ]; then
        STATE_FILE="$OUTPUT_DIR/$domain/crawler_state_$domain.pkl"
        if [ -f "$STATE_FILE" ]; then
            echo "Eliminazione $STATE_FILE"
            rm -f "$STATE_FILE"
        fi
    fi
done

# Elimina stato generico
rm -f "$OUTPUT_DIR/crawler_state_multi_domain_spider.pkl"
rm -rf "$JOB_DIR/*"
rm -rf .scrapy/httpcache/multi_domain_spider/*

echo -e "${GREEN}Pulizia completata${NC}"

# Visualizza configurazione
echo -e "${GREEN}=== MultiDomain Crawler - Avvio Pulito ===${NC}"
echo -e "${YELLOW}Configurazione:${NC}"
if [ -n "$DOMAINS_FILE" ]; then
    echo "- Domini: da file $DOMAINS_FILE"
else
    echo "- Domini: $DOMAINS"
fi
echo "- Max URL per dominio: $MAX_URLS_PER_DOMAIN"
echo "- Modalità ibrida: $HYBRID_MODE"
echo "- Formato output: $OUTPUT_FORMAT"
echo "- Directory output: $OUTPUT_DIR"
echo "- File log: $LOG_FILE"
echo -e "${YELLOW}Parametri avanzati:${NC}"
echo "- Richieste concorrenti: $CONCURRENT_REQUESTS"
echo "- Richieste per dominio: $CONCURRENT_PER_DOMAIN"
echo "- Ritardo richieste: ${REQUEST_DELAY}s"
echo "- Soglia Selenium: $SELENIUM_THRESHOLD"
echo "- Limite profondità: $DEPTH_LIMIT"
echo ""
echo -e "${GREEN}Avvio crawler pulito in corso...${NC}"

# Prepara il comando Scrapy
SCRAPY_CMD="scrapy crawl multi_domain_spider"

# Parametri domini
if [ -n "$DOMAINS_FILE" ]; then
    SCRAPY_CMD="$SCRAPY_CMD -a domains_file=\"$DOMAINS_FILE\""
else
    SCRAPY_CMD="$SCRAPY_CMD -a domains=\"$DOMAINS\""
fi

# Altri parametri
SCRAPY_CMD="$SCRAPY_CMD -a max_urls_per_domain=$MAX_URLS_PER_DOMAIN"
SCRAPY_CMD="$SCRAPY_CMD -a hybrid_mode=$HYBRID_MODE"
SCRAPY_CMD="$SCRAPY_CMD -a selenium_threshold=$SELENIUM_THRESHOLD"
SCRAPY_CMD="$SCRAPY_CMD -a request_delay=$REQUEST_DELAY"
SCRAPY_CMD="$SCRAPY_CMD -a depth_limit=$DEPTH_LIMIT"

# Parametri Scrapy - Disabilita cache e imposta debug
SCRAPY_CMD="$SCRAPY_CMD -s CONCURRENT_REQUESTS=$CONCURRENT_REQUESTS"
SCRAPY_CMD="$SCRAPY_CMD -s CONCURRENT_REQUESTS_PER_DOMAIN=$CONCURRENT_PER_DOMAIN"
SCRAPY_CMD="$SCRAPY_CMD -s OUTPUT_DIR=$OUTPUT_DIR"
SCRAPY_CMD="$SCRAPY_CMD -s JOBDIR=$JOB_DIR"
SCRAPY_CMD="$SCRAPY_CMD -s HTTPCACHE_ENABLED=False"  # Disabilita cache HTTP
SCRAPY_CMD="$SCRAPY_CMD -s DUPEFILTER_DEBUG=True"    # Debug per filtro duplicati
SCRAPY_CMD="$SCRAPY_CMD -s LOG_LEVEL=$LOG_LEVEL"
SCRAPY_CMD="$SCRAPY_CMD -s PIPELINE_REPORT_FORMAT=$OUTPUT_FORMAT"
SCRAPY_CMD="$SCRAPY_CMD --logfile=$LOG_FILE"

# Esegui con log dettagliato
echo "$SCRAPY_CMD" > "$OUTPUT_DIR/last_command.txt"
echo -e "${YELLOW}Esecuzione in corso...${NC}"
eval "$SCRAPY_CMD"

# Verifica risultato
EXIT_CODE=$?
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}Crawler completato con successo $(date)${NC}"
    echo -e "${BLUE}Log salvato in: $LOG_FILE${NC}"
    echo -e "${BLUE}Report in: $OUTPUT_DIR${NC}"
else
    echo -e "${RED}Crawler terminato con errori (codice: $EXIT_CODE) $(date)${NC}"
    echo -e "${YELLOW}Controlla il log per i dettagli: $LOG_FILE${NC}"
fi

exit $EXIT_CODE