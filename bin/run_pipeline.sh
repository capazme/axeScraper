#!/bin/bash
# run_pipeline.sh
# Script to run the complete web accessibility pipeline

# Color codes
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory and project root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
source "$(dirname "$0")/../config/shell_common.sh"

# Default configuration
DOMAINS=${1:-"iper.it,esselunga.it"}
MAX_URLS_PER_DOMAIN=${2:-50}
HYBRID_MODE=${3:-"True"}
START_STAGE=${4:-"crawler"}
REPEAT_AXE=${5:-1}

# Activate virtual environment if exists
if [ -d "/home/ec2-user/axeScraper/.venv" ]; then
    source /home/ec2-user/axeScraper/.venv/bin/activate
    echo -e "${GREEN}Virtual environment activated${NC}"
else
    echo -e "${YELLOW}No virtual environment found. Using system Python.${NC}"
fi

# Function to show help
show_help() {
    echo "Web Accessibility Pipeline Script"
    echo "Usage: $0 [domains] [max_urls_per_domain] [hybrid_mode] [start_stage] [repeat_axe]"
    echo ""
    echo "Parameters:"
    echo "  [domains]               - Comma-separated list of domains (default: iper.it,esselunga.it)"
    echo "  [max_urls_per_domain]   - Max URLs per domain (default: 50)"
    echo "  [hybrid_mode]           - Use Selenium+HTTP (True/False, default: True)"
    echo "  [start_stage]           - Starting pipeline stage (crawler/axe/final, default: crawler)"
    echo "  [repeat_axe]            - Number of times to repeat Axe analysis (default: 1)"
    echo ""
    echo "Stages:"
    echo "  crawler  - Start from web crawling"
    echo "  axe      - Start from Axe accessibility analysis"
    echo "  final    - Start from generating final reports"
    exit 1
}

# Show help if requested
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    show_help
fi

# Timestamp for output
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
OUTPUT_ROOT="/home/ec2-user/axeScraper/output"
LOGS_DIR="$OUTPUT_ROOT/logs"

# Create output directories
mkdir -p "$OUTPUT_ROOT"
mkdir -p "$LOGS_DIR"

# Log file with timestamp
LOG_FILE="$LOGS_DIR/pipeline_${TIMESTAMP}.log"

echo -e "${GREEN}Starting Web Accessibility Pipeline${NC}"
echo -e "${YELLOW}Domains: $DOMAINS${NC}"
echo -e "${YELLOW}Max URLs per Domain: $MAX_URLS_PER_DOMAIN${NC}"
echo -e "${YELLOW}Hybrid Mode: $HYBRID_MODE${NC}"
echo -e "${YELLOW}Start Stage: $START_STAGE${NC}"
echo -e "${YELLOW}Axe Repeat: $REPEAT_AXE${NC}"

# Prepare Python command
PYTHON_CMD="python -m src.pipeline \
    --domains \"$DOMAINS\" \
    --max-urls-per-domain $MAX_URLS_PER_DOMAIN \
    --hybrid-mode $HYBRID_MODE \
    --start-stage $START_STAGE \
    --repeat-axe $REPEAT_AXE"

# Save command for reference
echo "$PYTHON_CMD" > "$OUTPUT_ROOT/last_pipeline_command.txt"

# Execute pipeline
cd "$PROJECT_ROOT" || exit 1
$PYTHON_CMD 2>&1 | tee "$LOG_FILE"

# Check pipeline result
EXIT_CODE=${PIPESTATUS[0]}

if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}Web Accessibility Pipeline completed successfully!${NC}"
    echo -e "${BLUE}Log saved to: $LOG_FILE${NC}"
    echo -e "${BLUE}Output root: $OUTPUT_ROOT${NC}"
else
    echo -e "${RED}Web Accessibility Pipeline failed with exit code $EXIT_CODE${NC}"
    echo -e "${YELLOW}Check log for details: $LOG_FILE${NC}"
fi

exit $EXIT_CODE