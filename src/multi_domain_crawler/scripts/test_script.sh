#!/bin/bash
# Test script per il multi_domain_spider con le correzioni

# Colori per output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Test Multi Domain Spider ===${NC}"
echo "Test con configurazioni conservative per evitare blocchi"
echo ""

# Test 1: Minimo numero di URL per verificare che funzioni
echo -e "${YELLOW}Test 1: Crawl minimo (3 URL)${NC}"
scrapy crawl multi_domain_spider \
  -a domains="nortbeachwear.com" \
  -a max_urls_per_domain=3 \
  -a hybrid_mode=true \
  -a selenium_threshold=10 \
  -a request_delay=3.0 \
  -s CONCURRENT_REQUESTS=2 \
  -s CONCURRENT_REQUESTS_PER_DOMAIN=1 \
  -s DOWNLOAD_DELAY=3 \
  -s AUTOTHROTTLE_ENABLED=True \
  -s AUTOTHROTTLE_START_DELAY=2 \
  -s AUTOTHROTTLE_TARGET_CONCURRENCY=1.0 \
  -s LOG_LEVEL=INFO \
  -s ROBOTSTXT_OBEY=False

echo ""
echo -e "${GREEN}Test completato!${NC}"
echo ""

# Verifica se ci sono stati risultati
OUTPUT_DIR="output_crawler"
if [ -d "$OUTPUT_DIR" ]; then
    echo -e "${YELLOW}File generati:${NC}"
    find "$OUTPUT_DIR" -name "*.json" -o -name "*.csv" -o -name "*.md" | head -10
    
    # Conta gli URL processati
    if [ -f "$OUTPUT_DIR/consolidated_report_*.json" ]; then
        URLS=$(grep -c '"url"' $OUTPUT_DIR/consolidated_report_*.json 2>/dev/null || echo "0")
        echo -e "${GREEN}URL processati: $URLS${NC}"
    fi
fi

echo ""
echo -e "${YELLOW}Suggerimenti:${NC}"
echo "- Se il test funziona, aumenta gradualmente max_urls_per_domain"
echo "- Se ricevi ancora 403/429, aumenta request_delay e DOWNLOAD_DELAY"
echo "- Per debug dettagliato, usa -s LOG_LEVEL=DEBUG"
echo "- Controlla i log in output_crawler/*.log"

echo ""
echo -e "${BLUE}=== Test 2: Configurazione Cloudflare Aggressiva ===${NC}"
echo "Se il test 1 fallisce, prova questo comando per siti con Cloudflare:"
echo ""
cat << 'EOF'
scrapy crawl multi_domain_spider \
  -a domains="nortbeachwear.com" \
  -a max_urls_per_domain=5 \
  -a hybrid_mode=true \
  -a selenium_threshold=999 \
  -a request_delay=5.0 \
  -s CONCURRENT_REQUESTS=1 \
  -s CONCURRENT_REQUESTS_PER_DOMAIN=1 \
  -s DOWNLOAD_DELAY=5 \
  -s RANDOMIZE_DOWNLOAD_DELAY=True \
  -s AUTOTHROTTLE_ENABLED=True \
  -s AUTOTHROTTLE_START_DELAY=5 \
  -s AUTOTHROTTLE_MAX_DELAY=60 \
  -s AUTOTHROTTLE_TARGET_CONCURRENCY=0.5 \
  -s ROBOTSTXT_OBEY=False \
  -s HTTPCACHE_ENABLED=False \
  -s RETRY_TIMES=5 \
  -s LOG_LEVEL=INFO
EOF