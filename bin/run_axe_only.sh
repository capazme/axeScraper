#!/bin/bash
# run_axe_only.sh
# Script to run only the Axe accessibility analysis for specific domains

# Load common utilities and configurations
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPT_DIR/../config/shell_common.sh"

# Get parameters with defaults from environment variables or use script arguments
DOMAINS=${1:-${AXE_BASE_URLS:-"example.com"}}
MAX_TEMPLATES_PER_DOMAIN=${2:-${AXE_MAX_TEMPLATES:-50}}
POOL_SIZE=${3:-${AXE_POOL_SIZE:-6}}

# Get timestamp for this run
TIMESTAMP=$(get_timestamp)

# Function to show help
show_help() {
    echo "Axe Accessibility Analysis Script"
    echo "Usage: $0 [domains] [max_templates_per_domain] [pool_size]"
    echo ""
    echo "Parameters:"
    echo "  [domains]                 - Comma-separated list of domains (default: $DOMAINS)"
    echo "  [max_templates_per_domain] - Max number of templates per domain (default: $MAX_TEMPLATES_PER_DOMAIN)"
    echo "  [pool_size]               - Number of concurrent workers (default: $POOL_SIZE)"
    echo ""
    echo "Environment Variables:"
    echo "  AXE_BASE_URLS            - Default domains to analyze"
    echo "  AXE_MAX_TEMPLATES        - Default max templates per domain"
    echo "  AXE_POOL_SIZE            - Default pool size"
    echo "  AXE_OUTPUT_DIR           - Base output directory"
    echo "  AXE_HEADLESS             - Run in headless mode (true/false)"
    echo "  AXE_RESUME               - Resume from previous run (true/false)"
    exit 1
}

# Show help if requested
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    show_help
fi

# Activate virtual environment
activate_venv

# Process domains and create a safe slug for filenames
DOMAIN_SLUG=$(echo "$DOMAINS" | sed 's/,/_/g' | sed 's/[^a-zA-Z0-9]/_/g')
log_info "Processing domains: $DOMAINS (slug: $DOMAIN_SLUG)"

# Create domain-specific output structure for each domain
IFS=',' read -ra DOMAIN_ARRAY <<< "$DOMAINS"
for DOMAIN in "${DOMAIN_ARRAY[@]}"; do
    DOMAIN_DIR=$(create_domain_structure "$DOMAIN")
    log_info "Created directory structure for $DOMAIN at $DOMAIN_DIR"
done

# Main domain for output (use first domain or combined slug for multiple)
if [ ${#DOMAIN_ARRAY[@]} -eq 1 ]; then
    MAIN_DOMAIN=${DOMAIN_ARRAY[0]}
    MAIN_DOMAIN_SLUG=$(echo "$MAIN_DOMAIN" | sed 's/[^a-zA-Z0-9]/_/g')
else
    MAIN_DOMAIN="multiple_domains"
    MAIN_DOMAIN_SLUG="$DOMAIN_SLUG"
fi

MAIN_DOMAIN_DIR="$CONFIG_OUTPUT_ROOT/$MAIN_DOMAIN_SLUG"

# Define output paths
AXE_DIR="$MAIN_DOMAIN_DIR/axe_output"
LOG_DIR="$MAIN_DOMAIN_DIR/logs"

# Create output directories if they don't exist
mkdir -p "$AXE_DIR" "$LOG_DIR"

# Excel filename with timestamp and domain info
EXCEL_FILENAME="$AXE_DIR/accessibility_report_${MAIN_DOMAIN_SLUG}_${TIMESTAMP}.xlsx"
VISITED_FILE="$AXE_DIR/visited_urls_${MAIN_DOMAIN_SLUG}_${TIMESTAMP}.txt"
LOG_FILE="$LOG_DIR/axe_analysis_${TIMESTAMP}.log"

# Check if Python is available
if ! check_program "python"; then
    log_error "Python is not installed or not available in PATH"
    exit 1
fi

# Fallback URL list (add https://www. to each domain)
FALLBACK_URLS=$(echo "$DOMAINS" | tr ',' '\n' | sed 's/^/https:\/\/www\./')

log_info "Starting Axe Accessibility Analysis"
log_info "Domains: $DOMAINS"
log_info "Max Templates per Domain: $MAX_TEMPLATES_PER_DOMAIN"
log_info "Pool Size: $POOL_SIZE"
log_info "Output Excel: $EXCEL_FILENAME"
log_info "Log File: $LOG_FILE"

# Additional parameters from environment
HEADLESS_FLAG=$([ "${AXE_HEADLESS:-true}" = "true" ] && echo "--headless" || echo "")
RESUME_FLAG=$([ "${AXE_RESUME:-true}" = "true" ] && echo "--resume" || echo "")

# Run Axe Analysis with appropriate parameters
python -m src.axcel.axcel \
    --domains "$DOMAINS" \
    --max-templates-per-domain "$MAX_TEMPLATES_PER_DOMAIN" \
    --pool-size "$POOL_SIZE" \
    --excel-filename "$EXCEL_FILENAME" \
    --visited-file "$VISITED_FILE" \
    --log-file "$LOG_FILE" \
    $HEADLESS_FLAG \
    $RESUME_FLAG \
    2>&1 | tee -a "$LOG_FILE"

# Check analysis result
EXIT_CODE=$?

# Log outcome
if [ $EXIT_CODE -eq 0 ]; then
    log_success "Axe Accessibility Analysis completed successfully!"
    log_info "Report saved to: $EXCEL_FILENAME"
    log_info "Log saved to: $LOG_FILE"
else
    log_error "Axe Accessibility Analysis failed with exit code $EXIT_CODE"
    log_info "Check log for details: $LOG_FILE"
fi

exit $EXIT_CODE