#!/bin/bash
# run_crawler.sh
#
# Enhanced script for executing the multi-domain crawler with improved configuration handling
# Automatically detects and uses .env file if present
#

# Color codes for better readability
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to show help
show_help() {
    echo -e "${BLUE}MultiDomain Crawler - Execution Script${NC}"
    echo ""
    echo "Usage: $0 [domains] [max_urls_per_domain] [hybrid_mode] [output_format] [env_file]"
    echo ""
    echo "Parameters:"
    echo "  [domains]              - List of domains separated by comma or file .txt/.json (default: from .env)"
    echo "  [max_urls_per_domain]  - Maximum number of URLs per domain (default: from .env or 200)"
    echo "  [hybrid_mode]          - Use Selenium+HTTP (True) or HTTP only (False) (default: from .env or True)"
    echo "  [output_format]        - Output format: all, markdown, json, csv (default: from .env or all)"
    echo "  [env_file]             - Path to custom .env file (default: .env in current directory)"
    echo ""
    echo "Examples:"
    echo "  $0                                  # Use settings from .env file"
    echo "  $0 iper.it                          # Crawl iper.it with other settings from .env"
    echo "  $0 iper.it,esselunga.it 500 True    # Crawl both domains with limit 500 URLs and hybrid mode"
    echo "  $0 domains.txt 100 False json .env.prod # Use domains from file with custom .env"
    echo ""
    exit 1
}

# Show help if requested
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    show_help
fi

# Detect base directory (directory containing this script)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT" || exit 1

echo -e "${GREEN}Working directory: $(pwd)${NC}"

# Find the correct .env file
ENV_FILE=""
if [ -n "$5" ] && [ -f "$5" ]; then
    # Use custom env file if specified as 5th argument
    ENV_FILE="$5"
elif [ -f ".env" ]; then
    # Use .env in current directory
    ENV_FILE=".env"
elif [ -f "$PROJECT_ROOT/.env" ]; then
    # Use .env in project root
    ENV_FILE="$PROJECT_ROOT/.env"
fi

# Activate virtual environment
if [ -d "/home/ec2-user/axeScraper/.venv" ]; then
    source /home/ec2-user/axeScraper/.venv/bin/activate
    echo -e "${GREEN}Virtual environment activated: /home/ec2-user/axeScraper/.venv${NC}"
elif [ -d ".venv" ]; then
    source .venv/bin/activate
    echo -e "${GREEN}Virtual environment activated: .venv${NC}"
elif [ -d "venv" ]; then
    source venv/bin/activate
    echo -e "${GREEN}Virtual environment activated: venv${NC}"
fi

# Load environment variables from .env file if it exists
if [ -n "$ENV_FILE" ]; then
    echo -e "${BLUE}Loading configuration from: $ENV_FILE${NC}"
    # Export variables from .env file
    set -o allexport
    source "$ENV_FILE"
    set +o allexport
fi

# Configuration with command-line parameters taking precedence over environment variables
DOMAINS=${1:-${AXE_BASE_URLS:-"example.com"}}
MAX_URLS_PER_DOMAIN=${2:-${AXE_CRAWLER_MAX_URLS:-200}}
HYBRID_MODE=${3:-${AXE_CRAWLER_HYBRID_MODE:-"True"}}
OUTPUT_FORMAT=${4:-${AXE_PIPELINE_REPORT_FORMAT:-"all"}}

# Common Scrapy settings
CONCURRENT_REQUESTS=${AXE_SCRAPY_CONCURRENT_REQUESTS:-16}
CONCURRENT_PER_DOMAIN=${AXE_SCRAPY_CONCURRENT_PER_DOMAIN:-8}
REQUEST_DELAY=${AXE_SCRAPY_DOWNLOAD_DELAY:-0.25}
LOG_LEVEL=${AXE_LOG_LEVEL:-"INFO"}

# Output settings
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
OUTPUT_DIR=${AXE_OUTPUT_DIR:-"./output_crawler"}
JOB_DIR="$OUTPUT_DIR/crawls/multi-job-$TIMESTAMP"
LOG_FILE="$OUTPUT_DIR/logs/crawler_$TIMESTAMP.log"

# Create directories if they don't exist
mkdir -p "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR/logs"
mkdir -p "$JOB_DIR"

# Display configuration
echo -e "${GREEN}=== MultiDomain Crawler - Starting ====${NC}"
echo -e "${YELLOW}Configuration:${NC}"
echo "- Domains: $DOMAINS"
echo "- Max URLs per domain: $MAX_URLS_PER_DOMAIN"
echo "- Hybrid mode: $HYBRID_MODE"
echo "- Output format: $OUTPUT_FORMAT"
echo "- Output directory: $OUTPUT_DIR"
echo "- Log file: $LOG_FILE"

echo -e "${YELLOW}Advanced parameters:${NC}"
echo "- Concurrent requests: $CONCURRENT_REQUESTS"
echo "- Requests per domain: $CONCURRENT_PER_DOMAIN"
echo "- Request delay: ${REQUEST_DELAY}s"
echo "- Log level: $LOG_LEVEL"
echo "- Environment file: ${ENV_FILE:-"Not specified"}"

echo ""
echo -e "${GREEN}Starting crawler...${NC}"

# Build the Scrapy command
SCRAPY_CMD="python -m scrapy crawl multi_domain_spider"

# Command line arguments - these override .env file settings
SCRAPY_CMD="$SCRAPY_CMD -a domains=\"$DOMAINS\""
SCRAPY_CMD="$SCRAPY_CMD -a max_urls_per_domain=$MAX_URLS_PER_DOMAIN"
SCRAPY_CMD="$SCRAPY_CMD -a hybrid_mode=$HYBRID_MODE"

# If a custom .env file was specified, pass it to the spider
if [ -n "$ENV_FILE" ]; then
    SCRAPY_CMD="$SCRAPY_CMD -a env_file=\"$ENV_FILE\""
fi

# Scrapy settings
SCRAPY_CMD="$SCRAPY_CMD -s CONCURRENT_REQUESTS=$CONCURRENT_REQUESTS"
SCRAPY_CMD="$SCRAPY_CMD -s CONCURRENT_REQUESTS_PER_DOMAIN=$CONCURRENT_PER_DOMAIN"
SCRAPY_CMD="$SCRAPY_CMD -s DOWNLOAD_DELAY=$REQUEST_DELAY"
SCRAPY_CMD="$SCRAPY_CMD -s OUTPUT_DIR=$OUTPUT_DIR"
SCRAPY_CMD="$SCRAPY_CMD -s JOBDIR=$JOB_DIR"
SCRAPY_CMD="$SCRAPY_CMD -s HTTPCACHE_ENABLED=True"
SCRAPY_CMD="$SCRAPY_CMD -s LOG_LEVEL=$LOG_LEVEL"
SCRAPY_CMD="$SCRAPY_CMD -s PIPELINE_REPORT_FORMAT=$OUTPUT_FORMAT"
SCRAPY_CMD="$SCRAPY_CMD --logfile=$LOG_FILE"

# Save command for reference
echo "$SCRAPY_CMD" > "$OUTPUT_DIR/last_command.txt"
echo -e "${YELLOW}Executing command:${NC}"
echo "$SCRAPY_CMD"
echo ""

# Execute the command
cd "$PROJECT_ROOT/src/multi_domain_crawler" || exit 1
eval "$SCRAPY_CMD"

# Check result
EXIT_CODE=$?
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}Crawler completed successfully $(date)${NC}"
    echo -e "${BLUE}Log saved to: $LOG_FILE${NC}"
    echo -e "${BLUE}Output files in: $OUTPUT_DIR${NC}"
else
    echo -e "${RED}Crawler exited with error code $EXIT_CODE $(date)${NC}"
    echo -e "${YELLOW}Check the log for details: $LOG_FILE${NC}"
    echo -e "${YELLOW}Last few errors:${NC}"
    grep -i "error" "$LOG_FILE" | tail -10
fi

exit $EXIT_CODE