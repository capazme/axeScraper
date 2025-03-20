#!/bin/bash
# run_pipeline.sh
#
# Enhanced script to run the complete web accessibility pipeline
# Fully integrated with the configuration system

# Color codes for better readability
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory and project root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Function to show help
show_help() {
    echo -e "${BLUE}Web Accessibility Pipeline Script${NC}"
    echo ""
    echo "Usage: $0 [domains] [max_urls_per_domain] [max_templates] [start_stage] [repeat_axe] [env_file]"
    echo ""
    echo "Parameters:"
    echo "  [domains]               - Comma-separated list of domains (default: from .env)"
    echo "  [max_urls_per_domain]   - Max URLs per domain for crawler (default: from .env or 50)"
    echo "  [max_templates]         - Max templates for axe analysis (default: from .env or 50)"
    echo "  [start_stage]           - Starting pipeline stage (crawler/axe/final, default: from .env or crawler)"
    echo "  [repeat_axe]            - Number of times to repeat Axe analysis (default: from .env or 1)"
    echo "  [env_file]              - Path to custom .env file (default: .env in current directory)"
    echo ""
    echo "Stages:"
    echo "  crawler  - Start from web crawling"
    echo "  axe      - Start from Axe accessibility analysis"
    echo "  final    - Start from generating final reports"
    echo ""
    echo "Examples:"
    echo "  $0                          # Use all settings from .env file"
    echo "  $0 iper.it 200 50           # Custom domains and limits, other settings from .env"
    echo "  $0 iper.it 200 50 axe 2     # Start from axe stage and run it twice"
    echo "  $0 iper.it 200 50 crawler 1 .env.prod # Use custom .env file"
    echo ""
    exit 1
}

# Show help if requested
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    show_help
fi

# Find the correct .env file
ENV_FILE=""
if [ -n "$6" ] && [ -f "$6" ]; then
    # Use custom env file if specified as 6th argument
    ENV_FILE="$6"
elif [ -f "$PROJECT_ROOT/.env" ]; then
    ENV_FILE="$PROJECT_ROOT/.env"
elif [ -f ".env" ]; then
    ENV_FILE=".env"
fi

# Load environment variables from .env file if it exists
if [ -n "$ENV_FILE" ]; then
    echo -e "${BLUE}Loading configuration from: $ENV_FILE${NC}"
    # Export variables from .env file
    set -o allexport
    source "$ENV_FILE"
    set +o allexport
fi

# Activate virtual environment
if [ -d "/home/ec2-user/axeScraper/.venv" ]; then
    source /home/ec2-user/axeScraper/.venv/bin/activate
    echo -e "${GREEN}Virtual environment activated: /home/ec2-user/axeScraper/.venv${NC}"
elif [ -d "$PROJECT_ROOT/.venv" ]; then
    source "$PROJECT_ROOT/.venv/bin/activate
    echo -e "${GREEN}Virtual environment activated: $PROJECT_ROOT/.venv${NC}"
elif [ -d "$PROJECT_ROOT/venv" ]; then
    source "$PROJECT_ROOT/venv/bin/activate
    echo -e "${GREEN}Virtual environment activated: $PROJECT_ROOT/venv${NC}"
else
    echo -e "${YELLOW}No virtual environment found, using system Python${NC}"
fi

# Configuration with command-line parameters taking precedence
DOMAINS=${1:-${AXE_BASE_URLS:-"example.com"}}
MAX_URLS_PER_DOMAIN=${2:-${AXE_CRAWLER_MAX_URLS:-50}}
MAX_TEMPLATES=${3:-${AXE_MAX_TEMPLATES:-50}}
START_STAGE=${4:-${AXE_START_STAGE:-"crawler"}}
REPEAT_AXE=${5:-${AXE_REPEAT_ANALYSIS:-1}}

# Output settings
OUTPUT_ROOT=${AXE_OUTPUT_DIR:-"$PROJECT_ROOT/output"}
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="$OUTPUT_ROOT/logs/pipeline_$TIMESTAMP.log"

# Create directories if needed
mkdir -p "$OUTPUT_ROOT/logs"

# Display configuration
echo -e "${GREEN}=== Web Accessibility Pipeline ====${NC}"
echo -e "${YELLOW}Configuration:${NC}"
echo "- Domains: $DOMAINS"
echo "- Max URLs per domain: $MAX_URLS_PER_DOMAIN"
echo "- Max templates for analysis: $MAX_TEMPLATES"
echo "- Start stage: $START_STAGE"
echo "- Repeat axe analysis: $REPEAT_AXE times"
echo "- Output root: $OUTPUT_ROOT"
echo "- Log file: $LOG_FILE"
echo "- Environment file: ${ENV_FILE:-"Not specified"}"

# Validate start stage
if [[ "$START_STAGE" != "crawler" && "$START_STAGE" != "axe" && "$START_STAGE" != "final" ]]; then
    echo -e "${RED}Invalid start stage: $START_STAGE. Must be 'crawler', 'axe', or 'final'${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}Starting pipeline...${NC}"

# Build the Python command with all necessary parameters
PYTHON_CMD="python -m src.pipeline"

# Command line arguments - these override .env file settings
PYTHON_CMD="$PYTHON_CMD --domains \"$DOMAINS\""
PYTHON_CMD="$PYTHON_CMD --max-urls-per-domain $MAX_URLS_PER_DOMAIN"
PYTHON_CMD="$PYTHON_CMD --max-templates $MAX_TEMPLATES"
PYTHON_CMD="$PYTHON_CMD --start-stage $START_STAGE"
PYTHON_CMD="$PYTHON_CMD --repeat-axe $REPEAT_AXE"

# If a custom .env file was specified, pass it to the pipeline
if [ -n "$ENV_FILE" ]; then
    PYTHON_CMD="$PYTHON_CMD --env-file \"$ENV_FILE\""
fi

# Save command for reference
echo "$PYTHON_CMD" > "$OUTPUT_ROOT/last_pipeline_command.txt"
echo -e "${YELLOW}Executing command:${NC}"
echo "$PYTHON_CMD"
echo ""

# Execute the pipeline
cd "$PROJECT_ROOT" || exit 1
mkdir -p "$(dirname "$LOG_FILE")"
$PYTHON_CMD 2>&1 | tee "$LOG_FILE"

# Check the result
EXIT_CODE=${PIPESTATUS[0]}

if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}Web Accessibility Pipeline completed successfully!${NC}"
    echo -e "${BLUE}Log saved to: $LOG_FILE${NC}"
    echo -e "${BLUE}Output files in: $OUTPUT_ROOT${NC}"
else
    echo -e "${RED}Web Accessibility Pipeline failed with exit code $EXIT_CODE${NC}"
    echo -e "${YELLOW}Check log for details: $LOG_FILE${NC}"
fi

exit $EXIT_CODE