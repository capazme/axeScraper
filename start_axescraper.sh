#!/bin/bash
# start_axescraper.sh
#
# Main startup script for axeScraper with configuration detection
# and enhanced logging for better diagnosability.

# Color codes for better readability
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory and project root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$SCRIPT_DIR"

# Banner for visual identification
echo -e "${BLUE}"
echo "  _____          _____                                "
echo " |  _  |___ ___|   __|___ ___ ___ ___ ___ ___ ___ ___ "
echo " |     |  _| -_|__   |  _|  _| .'| . | -_|  _|  _|  _|"
echo " |__|__|___|___|_____|___|_| |__,|  _|___|_| |_| |_|  "
echo "                                  |_|                  "
echo -e "${NC}"
echo "Automated Web Accessibility Testing Pipeline"
echo ""

# Function to show help
show_help() {
    echo -e "${BLUE}axeScraper - Web Accessibility Testing Tool${NC}"
    echo ""
    echo "Usage: $0 [options]"
    echo ""
    echo "Options:"
    echo "  --help, -h             Show this help message"
    echo "  --daemon, -d           Run in daemon mode (background process)"
    echo "  --config=FILE, -c FILE Specify custom .env configuration file"
    echo "  --domains=LIST         Comma-separated list of domains to test"
    echo "  --stage=STAGE          Starting stage (crawler, axe, final)"
    echo "  --verbose, -v          Enable verbose output"
    echo "  --force, -f            Force run even if another instance seems to be running"
    echo ""
    echo "Examples:"
    echo "  $0                     # Run with default settings from .env"
    echo "  $0 -c .env.production  # Use production configuration"
    echo "  $0 --domains=example.com,example.org --stage=axe # Start from axe stage"
    echo "  $0 -d                  # Run in background"
    echo ""
    exit 0
}

# Process command line arguments
DAEMON_MODE=false
CONFIG_FILE=""
DOMAINS=""
START_STAGE=""
VERBOSE=false
FORCE=false

for arg in "$@"; do
    case $arg in
        --help|-h)
            show_help
            ;;
        --daemon|-d)
            DAEMON_MODE=true
            shift
            ;;
        --config=*|-c)
            if [[ $arg == --config=* ]]; then
                CONFIG_FILE="${arg#*=}"
            else
                # Next argument is the config file
                shift
                CONFIG_FILE="$1"
            fi
            shift
            ;;
        --domains=*)
            DOMAINS="${arg#*=}"
            shift
            ;;
        --stage=*)
            START_STAGE="${arg#*=}"
            shift
            ;;
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        --force|-f)
            FORCE=true
            shift
            ;;
        *)
            # Unknown option
            echo -e "${RED}Unknown option: $arg${NC}"
            show_help
            ;;
    esac
done

# Find the correct .env file
if [ -z "$CONFIG_FILE" ]; then
    if [ -f "$PROJECT_ROOT/.env" ]; then
        CONFIG_FILE="$PROJECT_ROOT/.env"
        echo -e "${BLUE}Using configuration from: $CONFIG_FILE${NC}"
    else
        echo -e "${YELLOW}No .env file found. Creating default from template...${NC}"
        if [ -f "$PROJECT_ROOT/.env.template" ]; then
            cp "$PROJECT_ROOT/.env.template" "$PROJECT_ROOT/.env"
            CONFIG_FILE="$PROJECT_ROOT/.env"
            echo -e "${GREEN}Created default .env file from template${NC}"
        else
            echo -e "${YELLOW}No .env.template found. Will use default values.${NC}"
        fi
    fi
fi

# Activate virtual environment
if [ -d "$PROJECT_ROOT/.venv" ]; then
    source "$PROJECT_ROOT/.venv/bin/activate"
    echo -e "${GREEN}Activated virtual environment: $PROJECT_ROOT/.venv${NC}"
elif [ -d "/home/ec2-user/axeScraper/.venv" ]; then
    source "/home/ec2-user/axeScraper/.venv/bin/activate"
    echo -e "${GREEN}Activated virtual environment: /home/ec2-user/axeScraper/.venv${NC}"
else
    echo -e "${YELLOW}No virtual environment found. Using system Python.${NC}"
fi

# Check if another instance is running
PID_FILE="/tmp/axescraper.pid"
if [ -f "$PID_FILE" ] && ! $FORCE; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null; then
        echo -e "${RED}Another instance of axeScraper appears to be running (PID: $PID)${NC}"
        echo -e "${YELLOW}Use --force to run anyway, or kill the other process first.${NC}"
        exit 1
    else
        echo -e "${YELLOW}Found stale PID file. Previous run may have crashed.${NC}"
    fi
fi

# Create PID file
echo $$ > "$PID_FILE"

# Prepare command arguments
CMD_ARGS=""

if [ -n "$DOMAINS" ]; then
    CMD_ARGS="$CMD_ARGS --domains \"$DOMAINS\""
fi

if [ -n "$START_STAGE" ]; then
    CMD_ARGS="$CMD_ARGS --start-stage $START_STAGE"
fi

if [ -n "$CONFIG_FILE" ]; then
    CMD_ARGS="$CMD_ARGS --env-file \"$CONFIG_FILE\""
fi

if $VERBOSE; then
    CMD_ARGS="$CMD_ARGS --verbose"
fi

# Setup log directory and file
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_DIR="$PROJECT_ROOT/output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/axescraper_$TIMESTAMP.log"

# Function to clean up on exit
cleanup() {
    echo -e "${YELLOW}Cleaning up...${NC}"
    rm -f "$PID_FILE"
    echo -e "${GREEN}Done. Log file: $LOG_FILE${NC}"
    exit 0
}

# Register cleanup function for termination signals
trap cleanup EXIT INT TERM

# Execute the pipeline
echo -e "${GREEN}Starting axeScraper...${NC}"
echo -e "${BLUE}Log file: $LOG_FILE${NC}"

# Construct the command
PIPELINE_CMD="python -m src.pipeline $CMD_ARGS"
echo -e "${YELLOW}Executing: $PIPELINE_CMD${NC}"

# Run in daemon mode or foreground
if $DAEMON_MODE; then
    echo -e "${GREEN}Running in daemon mode...${NC}"
    nohup $PIPELINE_CMD > "$LOG_FILE" 2>&1 &
    PID=$!
    echo $PID > "$PID_FILE"
    echo -e "${GREEN}Process started with PID: $PID${NC}"
    echo -e "${BLUE}Use 'tail -f $LOG_FILE' to monitor progress${NC}"
else
    echo -e "${GREEN}Running in foreground mode...${NC}"
    $PIPELINE_CMD 2>&1 | tee "$LOG_FILE"
fi