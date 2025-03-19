#!/bin/bash
# run_crawler_only.sh
# Script to run only the multi-domain crawler for specific domains

source "$(dirname "$0")/../config/shell_common.sh"

# Color codes
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Default configuration
DOMAINS=${1:-"iper.it"}
MAX_URLS_PER_DOMAIN=${2:-200}
HYBRID_MODE=${3:-"True"}
OUTPUT_DIR="/home/ec2-user/axeScraper/output_crawler"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

# Activate virtual environment if exists
if [ -d "/home/ec2-user/axeScraper/.venv" ]; then
    source /home/ec2-user/axeScraper/.venv/bin/activate
    echo -e "${GREEN}Virtual environment activated${NC}"
else
    echo -e "${YELLOW}No virtual environment found. Using system Python.${NC}"
fi

# Ensure output directory exists
mkdir -p "$OUTPUT_DIR"

# Function to show help
show_help() {
    echo "Multi-Domain Crawler Script"
    echo "Usage: $0 [domains] [max_urls_per_domain] [hybrid_mode]"
    echo ""
    echo "Parameters:"
    echo "  [domains]               - Comma-separated list of domains (default: iper.it)"
    echo "  [max_urls_per_domain]   - Max URLs per domain (default: 200)"
    echo "  [hybrid_mode]           - Use Selenium+HTTP (True/False, default: True)"
    exit 1
}

# Show help if requested
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    show_help
fi

# Prepare domain output directory
DOMAIN_SLUG=$(echo "$DOMAINS" | sed 's/,/_/g')
JOB_DIR="$OUTPUT_DIR/multi-job-$TIMESTAMP"
LOG_FILE="$OUTPUT_DIR/crawler_${DOMAIN_SLUG}_${TIMESTAMP}.log"

# Prepare Scrapy command
cd /home/ec2-user/axeScraper/src/multi_domain_crawler || exit 1

echo -e "${GREEN}Starting Multi-Domain Crawler${NC}"
echo -e "${YELLOW}Domains: $DOMAINS${NC}"
echo -e "${YELLOW}Max URLs per Domain: $MAX_URLS_PER_DOMAIN${NC}"
echo -e "${YELLOW}Hybrid Mode: $HYBRID_MODE${NC}"
echo -e "${YELLOW}Output Directory: $OUTPUT_DIR${NC}"

# Advanced Scrapy parameters
SCRAPY_CMD="scrapy crawl multi_domain_spider \
    -a domains=\"$DOMAINS\" \
    -a max_urls_per_domain=$MAX_URLS_PER_DOMAIN \
    -a hybrid_mode=$HYBRID_MODE \
    -s OUTPUT_DIR=$OUTPUT_DIR \
    -s JOBDIR=$JOB_DIR \
    -s CONCURRENT_REQUESTS=16 \
    -s CONCURRENT_REQUESTS_PER_DOMAIN=8 \
    -s DOWNLOAD_DELAY=0.25 \
    -s HTTPCACHE_ENABLED=True \
    -s LOG_LEVEL=INFO \
    -s PIPELINE_REPORT_FORMAT=all \
    --logfile=$LOG_FILE"

# Save the command for reference
echo "$SCRAPY_CMD" > "$OUTPUT_DIR/last_crawler_command.txt"

# Execute the crawler
eval "$SCRAPY_CMD"

# Check crawler result
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}Multi-Domain Crawler completed successfully!${NC}"
    echo -e "${YELLOW}Log saved to: $LOG_FILE${NC}"
    echo -e "${YELLOW}Output saved to: $OUTPUT_DIR${NC}"
else
    echo -e "${RED}Multi-Domain Crawler failed with exit code $EXIT_CODE${NC}"
    echo -e "${YELLOW}Check log for details: $LOG_FILE${NC}"
fi

exit $EXIT_CODE