#!/bin/bash
# Common utilities and configurations for shell scripts

# ----- Color codes -----
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ----- Configuration -----
# Project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Load .env file if it exists
ENV_FILE="$PROJECT_ROOT/.env"
if [ -f "$ENV_FILE" ]; then
    # Load environment variables from .env file
    set -o allexport
    source "$ENV_FILE"
    set +o allexport
    echo -e "${BLUE}Loaded environment from $ENV_FILE${NC}"
fi

# Virtual environment path
VENV_PATH="${AXE_VENV_PATH:-$PROJECT_ROOT/.venv}"

# Output root directory
CONFIG_OUTPUT_ROOT="${AXE_OUTPUT_DIR:-/home/ec2-user/axeScraper/output}"

# ----- Functions -----

# Activate virtual environment
activate_venv() {
    if [ -d "$VENV_PATH" ]; then
        source "$VENV_PATH/bin/activate"
        echo -e "${GREEN}Virtual environment activated: $VENV_PATH${NC}"
    else
        echo -e "${YELLOW}No virtual environment found at $VENV_PATH. Using system Python.${NC}"
    fi
}

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO] $(date +"%Y-%m-%d %H:%M:%S")${NC} - $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS] $(date +"%Y-%m-%d %H:%M:%S")${NC} - $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING] $(date +"%Y-%m-%d %H:%M:%S")${NC} - $1"
}

log_error() {
    echo -e "${RED}[ERROR] $(date +"%Y-%m-%d %H:%M:%S")${NC} - $1"
}

# Create domain directory structure 
create_domain_structure() {
    local domain=$1
    local base_dir=${2:-"$CONFIG_OUTPUT_ROOT"}
    
    # Safe domain slug
    local domain_slug=$(echo "$domain" | sed 's/[^a-zA-Z0-9]/_/g')
    
    # Create all directories
    local domain_dir="$base_dir/$domain_slug"
    mkdir -p "$domain_dir/crawler_output"
    mkdir -p "$domain_dir/axe_output"
    mkdir -p "$domain_dir/analysis_output"
    mkdir -p "$domain_dir/reports"
    mkdir -p "$domain_dir/logs"
    mkdir -p "$domain_dir/charts"
    mkdir -p "$domain_dir/temp"
    
    echo "$domain_dir"
}

# Get timestamp string
get_timestamp() {
    date +"%Y%m%d_%H%M%S"
}

# Check if a program is available
check_program() {
    if ! command -v "$1" &> /dev/null; then
        log_error "Required program '$1' is not installed or not available in PATH"
        return 1
    fi
    return 0
}

# Handle exit with status
handle_exit() {
    local exit_code=$1
    local message=$2
    
    if [ $exit_code -eq 0 ]; then
        log_success "$message completed successfully"
    else
        log_error "$message failed with exit code $exit_code"
    fi
    
    exit $exit_code
}

# Create a backup of a file
backup_file() {
    local file_path=$1
    local max_backups=${2:-5}
    
    if [ ! -f "$file_path" ]; then
        return 0
    fi
    
    local timestamp=$(get_timestamp)
    local dir_name=$(dirname "$file_path")
    local base_name=$(basename "$file_path")
    local backup_path="${dir_name}/${base_name%.???*}_backup_${timestamp}.${base_name##*.}"
    
    cp "$file_path" "$backup_path"
    log_info "Created backup: $backup_path"
    
    # Clean up old backups if needed
    if [ $max_backups -gt 0 ]; then
        local pattern="${dir_name}/${base_name%.???*}_backup_*.${base_name##*.}"
        local backups=( $(ls -t $pattern 2>/dev/null) )
        
        if [ ${#backups[@]} -gt $max_backups ]; then
            for (( i=$max_backups; i<${#backups[@]}; i++ )); do
                rm "${backups[$i]}"
                log_info "Removed old backup: ${backups[$i]}"
            done
        fi
    fi
    
    return 0
}

# Wait for a process with timeout and show progress
wait_with_progress() {
    local pid=$1
    local description=$2
    local timeout=${3:-300}  # Default timeout of 5 minutes
    local interval=${4:-5}   # Check every 5 seconds
    
    log_info "Waiting for $description (PID: $pid) to complete..."
    
    local elapsed=0
    while kill -0 $pid 2>/dev/null; do
        echo -n "."
        sleep $interval
        elapsed=$((elapsed + interval))
        
        if [ $elapsed -ge $timeout ]; then
            echo ""
            log_warning "$description is taking longer than expected ($timeout seconds)"
            log_warning "Continue waiting? [Y/n]"
            read -t 10 continue_wait
            
            if [[ $continue_wait == "n" || $continue_wait == "N" ]]; then
                log_warning "Killing process $pid..."
                kill $pid
                return 1
            fi
            
            # Reset timeout
            elapsed=0
        fi
    done
    
    echo ""
    wait $pid
    return $?
}

# Export environment variables from a config file
export_config() {
    local config_file=$1
    
    if [ ! -f "$config_file" ]; then
        log_warning "Config file not found: $config_file"
        return 1
    fi
    
    # Export variables based on file extension
    if [[ "$config_file" == *.env ]]; then
        set -o allexport
        source "$config_file"
        set +o allexport
    elif [[ "$config_file" == *.json ]]; then
        # Requires jq
        if ! check_program "jq"; then
            log_warning "jq is required to parse JSON config"
            return 1
        fi
        
        while IFS="=" read -r key value; do
            export "$key=$value"
        done < <(jq -r "to_entries|map(\"\(.key)=\(.value|tostring)\")|.[]" "$config_file")
    elif [[ "$config_file" == *.yaml || "$config_file" == *.yml ]]; then
        # Requires yq
        if ! check_program "yq"; then
            log_warning "yq is required to parse YAML config"
            return 1
        fi
        
        while IFS="=" read -r key value; do
            export "$key=$value"
        done < <(yq e 'to_entries | .[] | .key + "=" + .value' "$config_file")
    else
        log_warning "Unsupported config file format: $config_file"
        return 1
    fi
    
    log_info "Loaded configuration from $config_file"
    return 0
}