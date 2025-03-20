#!/bin/bash
# run_crawler.sh
#
# Script per eseguire il crawler multi-dominio con parametri configurabili
# Esempio: ./run_crawler.sh iper.it,esselunga.it 200 True
#

# Colori per output
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Funzione di aiuto
show_help() {
    echo -e "${BLUE}MultiDomain Crawler - Script di esecuzione${NC}"
    echo ""
    echo "Utilizzo: $0 [domini] [max_urls_per_dominio] [modalità_ibrida] [modalità_output]"
    echo ""
    echo "Parametri:"
    echo "  [domini]              - Lista di domini separati da virgola o file .txt/.json (default: iper.it)"
    echo "  [max_urls_per_dominio]- Numero massimo di URL per dominio (default: 200)"
    echo "  [modalità_ibrida]     - Usa Selenium+HTTP (True) o solo HTTP (False) (default: True)"
    echo "  [modalità_output]     - Formato output: all, markdown, json, csv (default: all)"
    echo ""
    echo "Esempi:"
    echo "  $0 iper.it                        # Crawla iper.it con impostazioni predefinite"
    echo "  $0 iper.it,esselunga.it 500 True  # Crawla entrambi i domini con limite 500 URL e modo ibrido"
    echo "  $0 domains.txt 100 False json     # Crawla i domini dal file domains.txt con limite 100 URL, senza Selenium"
    echo ""
    exit 1
}

# Mostra aiuto se richiesto
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    show_help
fi

# Directory di base (directory dello script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR"

# Trova la directory src/multi_domain_crawler
# Prima cerca nella directory dello script
if [ -d "$SCRIPT_DIR/src/multi_domain_crawler" ]; then
    CRAWLER_DIR="$SCRIPT_DIR/src/multi_domain_crawler"
elif [ -d "$SCRIPT_DIR/multi_domain_crawler" ]; then
    CRAWLER_DIR="$SCRIPT_DIR/multi_domain_crawler"
else
    # Cerca in altre posizioni comuni
    for dir in "$SCRIPT_DIR"/* "$SCRIPT_DIR/src"/*; do
        if [ -d "$dir" ] && [ -d "$dir/multi_domain_crawler" ]; then
            CRAWLER_DIR="$dir"
            break
        elif [ -d "$dir" ] && [ "$(basename "$dir")" = "multi_domain_crawler" ]; then
            CRAWLER_DIR="$dir"
            break
        fi
    done
fi

if [ -z "$CRAWLER_DIR" ]; then
    echo -e "${RED}Errore: Impossibile trovare la directory multi_domain_crawler${NC}"
    echo -e "${YELLOW}Cercato in: $SCRIPT_DIR/src/multi_domain_crawler e altre posizioni comuni${NC}"
    echo -e "${YELLOW}Verifica la tua installazione o specifica il percorso manualmente${NC}"
    exit 1
fi

echo -e "${GREEN}Directory multi_domain_crawler trovata: ${CRAWLER_DIR}${NC}"
echo -e "${GREEN}Directory di lavoro: $(pwd)${NC}"

# Attiva l'ambiente virtuale se esiste
if [ -d "$SCRIPT_DIR/.venv" ]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
    echo -e "${GREEN}Ambiente virtuale attivato: $SCRIPT_DIR/.venv${NC}"
elif [ -d "$BASE_DIR/venv" ]; then
    source "$BASE_DIR/venv/bin/activate"
elif [ -d "/home/ec2-user/axeScraper/.venv" ]; then
    source "/home/ec2-user/axeScraper/.venv/bin/activate"
    echo -e "${GREEN}Ambiente virtuale attivato: /home/ec2-user/axeScraper/.venv${NC}"
fi

# Configurazione predefinita
DOMAINS=${1:-"iper.it"}
MAX_URLS_PER_DOMAIN=${2:-200}
HYBRID_MODE=${3:-"True"}
OUTPUT_FORMAT=${4:-"all"}

echo -e "${YELLOW}Parametri ricevuti:${NC}"
echo "DOMAINS=$DOMAINS"
echo "MAX_URLS_PER_DOMAIN=$MAX_URLS_PER_DOMAIN"
echo "HYBRID_MODE=$HYBRID_MODE"
echo "OUTPUT_FORMAT=$OUTPUT_FORMAT"

# Rileva se il primo parametro è un file
if [[ -f "$DOMAINS" ]]; then
    DOMAINS_FILE=$DOMAINS
    DOMAINS=""
    echo -e "${YELLOW}Rilevato file domini: $DOMAINS_FILE${NC}"
else
    DOMAINS_FILE=""
fi

# Configurazione percorsi
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
OUTPUT_DIR="$SCRIPT_DIR/output"
JOB_DIR="$OUTPUT_DIR/crawls/multi-job-$TIMESTAMP"
LOG_FILE="$OUTPUT_DIR/logs/crawler_$TIMESTAMP.log"

# Crea directory se non esistono
mkdir -p "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR/logs"
mkdir -p "$JOB_DIR"

# Configurazione Scrapy avanzata
CONCURRENT_REQUESTS=16
CONCURRENT_PER_DOMAIN=8
REQUEST_DELAY=0.5
SELENIUM_THRESHOLD=30
DEPTH_LIMIT=8
LOG_LEVEL="INFO"

# Visualizza configurazione
echo -e "${GREEN}=== MultiDomain Crawler - Avvio ===${NC}"
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

# Controllo se Scrapy è disponibile
if ! command -v scrapy &> /dev/null; then
    echo -e "${RED}Errore: Scrapy non trovato. Verificare che sia installato e accessibile.${NC}"
    echo "Percorso Python attuale: $(which python)"
    echo "Versione Python: $(python --version)"
    echo "Installato in ambiente virtuale: $(pip freeze | grep scrapy)"
    exit 1
fi

echo -e "${GREEN}Avvio crawler in corso...${NC}"

# Prepara il comando Scrapy
if [ -n "$DOMAINS_FILE" ]; then
    # Con file domini
    SCRAPY_CMD="scrapy crawl multi_domain_spider -a domains_file=\"$DOMAINS_FILE\""
else
    # Con domini diretti (assicurati che siano quotati correttamente)
    SCRAPY_CMD="scrapy crawl multi_domain_spider -a domains=\"$DOMAINS\""
fi

# Altri parametri
SCRAPY_CMD="$SCRAPY_CMD -a max_urls_per_domain=$MAX_URLS_PER_DOMAIN"
SCRAPY_CMD="$SCRAPY_CMD -a hybrid_mode=$HYBRID_MODE"
SCRAPY_CMD="$SCRAPY_CMD -a selenium_threshold=$SELENIUM_THRESHOLD"
SCRAPY_CMD="$SCRAPY_CMD -a request_delay=$REQUEST_DELAY"
SCRAPY_CMD="$SCRAPY_CMD -a depth_limit=$DEPTH_LIMIT"

# Parametri Scrapy
SCRAPY_CMD="$SCRAPY_CMD -s CONCURRENT_REQUESTS=$CONCURRENT_REQUESTS"
SCRAPY_CMD="$SCRAPY_CMD -s CONCURRENT_REQUESTS_PER_DOMAIN=$CONCURRENT_PER_DOMAIN"
SCRAPY_CMD="$SCRAPY_CMD -s OUTPUT_DIR=$OUTPUT_DIR"
SCRAPY_CMD="$SCRAPY_CMD -s JOBDIR=$JOB_DIR"
SCRAPY_CMD="$SCRAPY_CMD -s HTTPCACHE_ENABLED=True"
SCRAPY_CMD="$SCRAPY_CMD -s LOG_LEVEL=$LOG_LEVEL"
SCRAPY_CMD="$SCRAPY_CMD -s PIPELINE_REPORT_FORMAT=$OUTPUT_FORMAT"
SCRAPY_CMD="$SCRAPY_CMD --logfile=$LOG_FILE"

# Salva e mostra il comando esatto che verrà eseguito
echo "$SCRAPY_CMD" > "$OUTPUT_DIR/last_command.txt"
echo -e "${YELLOW}Comando esatto che verrà eseguito:${NC}"
echo "$SCRAPY_CMD"
echo ""
echo -e "${YELLOW}Esecuzione in corso...${NC}"

# Verifica directory corrente
if [ ! -d "$CRAWLER_DIR" ]; then
    echo -e "${RED}Errore: Directory del crawler non trovata: $CRAWLER_DIR${NC}"
    exit 1
fi

echo -e "${GREEN}Cambio nella directory del crawler: $CRAWLER_DIR${NC}"
# Esegui il comando nella directory corretta
cd "$CRAWLER_DIR" || {
    echo -e "${RED}Errore: Impossibile accedere alla directory $CRAWLER_DIR${NC}"
    exit 1
}

# Verifica se lo spider è disponibile
if ! python -m scrapy list 2>/dev/null | grep -q "multi_domain_spider"; then
    echo -e "${RED}Errore: Spider 'multi_domain_spider' non trovato${NC}"
    echo -e "${YELLOW}Spider disponibili:${NC}"
    python -m scrapy list
    exit 1
fi

# Esegui il comando
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
    echo -e "${YELLOW}Ultimi 20 errori dal log:${NC}"
    grep -i "error" "$LOG_FILE" | tail -20
fi

exit $EXIT_CODE