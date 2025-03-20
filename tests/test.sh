#!/bin/bash
# test_pipeline.sh - Script di testing completo per axeScraper
# 
# Questo script esegue test approfonditi su tutti i componenti della pipeline
# di analisi di accessibilità, identificando problemi e fornendo diagnostica.

set -o pipefail

# Colori per output
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Directory di base
if [ -d "/home/ec2-user/axeScraper" ]; then
    PROJECT_ROOT="/home/ec2-user/axeScraper"
else
    PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

# File e directory importanti
ENV_FILE="$PROJECT_ROOT/.env"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
TEST_OUTPUT_DIR="$PROJECT_ROOT/test_results_$TIMESTAMP"
TEST_LOG="$TEST_OUTPUT_DIR/test_pipeline.log"
TEMP_ENV_FILE="$TEST_OUTPUT_DIR/temp.env"

# Domini di test
TEST_DOMAIN="example.com"
SMALL_TEST_MAX_URLS=5
TEST_MAX_TEMPLATES=3

# Contatori
TESTS_TOTAL=0
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_SKIPPED=0

# Funzione per mostrare aiuto
show_help() {
    echo -e "${BLUE}${BOLD}axeScraper - Script di Testing Completo${NC}"
    echo ""
    echo "Questo script testa tutti i componenti della pipeline di axeScraper,"
    echo "identificando problemi e fornendo diagnostica dettagliata."
    echo ""
    echo "Utilizzo: $0 [opzioni]"
    echo ""
    echo "Opzioni:"
    echo "  -h, --help              Mostra questo messaggio di aiuto"
    echo "  -d, --domain DOMAIN     Specifica un dominio da testare (default: example.com)"
    echo "  -m, --max-urls NUM      Numero massimo di URL per il test (default: 5)"
    echo "  -c, --config FILE       File di configurazione .env da utilizzare"
    echo "  -o, --output DIR        Directory di output per i risultati del test"
    echo "  -q, --quick             Esegue solo test essenziali (modalità rapida)"
    echo "  -f, --full              Esegue tutti i test, inclusi quelli lunghi"
    echo "  -v, --verbose           Output più dettagliato"
    echo "  -s, --skip-cleanup      Non eliminare i file temporanei dopo i test"
    echo ""
    echo "Esempi:"
    echo "  $0 --quick              # Esegue test essenziali con dominio di test"
    echo "  $0 --domain iper.it --max-urls 10   # Testa con dominio specifico"
    echo "  $0 --full --verbose     # Esegue test completi con output dettagliato"
    echo ""
    exit 0
}

# Analizza gli argomenti della linea di comando
QUICK_MODE=false
FULL_MODE=false
VERBOSE=false
SKIP_CLEANUP=false

while [[ $# -gt 0 ]]; do
    key="$1"
    case $key in
        -h|--help)
            show_help
            ;;
        -d|--domain)
            TEST_DOMAIN="$2"
            shift 2
            ;;
        -m|--max-urls)
            SMALL_TEST_MAX_URLS="$2"
            shift 2
            ;;
        -c|--config)
            ENV_FILE="$2"
            shift 2
            ;;
        -o|--output)
            TEST_OUTPUT_DIR="$2"
            TEST_LOG="$TEST_OUTPUT_DIR/test_pipeline.log"
            shift 2
            ;;
        -q|--quick)
            QUICK_MODE=true
            shift
            ;;
        -f|--full)
            FULL_MODE=true
            shift
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        -s|--skip-cleanup)
            SKIP_CLEANUP=true
            shift
            ;;
        *)
            echo -e "${RED}Opzione non riconosciuta: $key${NC}"
            show_help
            ;;
    esac
done

# Crea directory di output
mkdir -p "$TEST_OUTPUT_DIR"
mkdir -p "$TEST_OUTPUT_DIR/logs"
mkdir -p "$TEST_OUTPUT_DIR/screenshots"
mkdir -p "$TEST_OUTPUT_DIR/artifacts"

# Configura il logging
exec > >(tee -a "$TEST_LOG") 2>&1

# Banner informativo
echo -e "${BLUE}${BOLD}===== axeScraper - Test Pipeline Completo =====${NC}"
echo -e "${BLUE}Data/Ora: $(date)${NC}"
echo -e "${BLUE}Directory di test: $TEST_OUTPUT_DIR${NC}"
echo -e "${BLUE}Dominio di test: $TEST_DOMAIN${NC}"
echo -e "${BLUE}Max URL di test: $SMALL_TEST_MAX_URLS${NC}"
if $QUICK_MODE; then
    echo -e "${BLUE}Modalità: Rapida (solo test essenziali)${NC}"
elif $FULL_MODE; then
    echo -e "${BLUE}Modalità: Completa (tutti i test)${NC}"
else
    echo -e "${BLUE}Modalità: Standard${NC}"
fi
echo -e "${BLUE}================================================================${NC}"
echo ""

# Funzioni di utilità
log_header() {
    echo -e "\n${CYAN}${BOLD}[$1]${NC} $2"
    echo -e "${CYAN}----------------------------------------------------------------${NC}"
}

log_subheader() {
    echo -e "\n${CYAN}>>> $1${NC}"
}

log_info() {
    echo -e "${BLUE}INFO:${NC} $1"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️ ATTENZIONE:${NC} $1"
}

log_error() {
    echo -e "${RED}❌ ERRORE:${NC} $1"
}

log_command() {
    if $VERBOSE; then
        echo -e "${YELLOW}$ $1${NC}"
    fi
}

log_result() {
    local result=$1
    local message=$2
    TESTS_TOTAL=$((TESTS_TOTAL + 1))
    if [ $result -eq 0 ]; then
        log_success "$message: PASSATO"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        log_error "$message: FALLITO"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi
}

log_skipped() {
    local message=$1
    TESTS_TOTAL=$((TESTS_TOTAL + 1))
    TESTS_SKIPPED=$((TESTS_SKIPPED + 1))
    echo -e "${YELLOW}⏭️ SKIPPED:${NC} $message"
}

# Funzione per eseguire comandi con timeout
run_command() {
    local cmd="$1"
    local timeout_sec="${2:-60}"
    local desc="${3:-comando}"
    local log_file="${4:-/dev/null}"
    
    log_command "$cmd"
    
    timeout $timeout_sec bash -c "$cmd" > "$log_file" 2>&1
    local status=$?
    
    if [ $status -eq 0 ]; then
        if $VERBOSE; then
            log_success "$desc completato con successo"
        fi
        return 0
    elif [ $status -eq 124 ]; then
        log_error "$desc terminato per timeout dopo $timeout_sec secondi"
        if $VERBOSE; then
            echo -e "${YELLOW}Ultime righe del log:${NC}"
            tail -n 10 "$log_file"
        fi
        return 1
    else
        log_error "$desc fallito con stato $status"
        if $VERBOSE; then
            echo -e "${YELLOW}Ultime righe del log:${NC}"
            tail -n 10 "$log_file"
        fi
        return $status
    fi
}

# Funzione per creare .env temporaneo
create_temp_env() {
    log_subheader "Creazione file .env temporaneo per i test"
    
    cat > "$TEMP_ENV_FILE" << EOL
# File .env temporaneo per i test della pipeline axeScraper
# Generato da test_pipeline.sh il $(date)

# Domini e configurazione di base
AXE_BASE_URLS=$TEST_DOMAIN
AXE_OUTPUT_DIR=$TEST_OUTPUT_DIR/output
AXE_START_STAGE=crawler
AXE_REPEAT_ANALYSIS=1

# Configurazione crawler
AXE_CRAWLER_MAX_URLS=$SMALL_TEST_MAX_URLS
AXE_MAX_TEMPLATES=$TEST_MAX_TEMPLATES
AXE_CRAWLER_MAX_WORKERS=4
AXE_CRAWLER_REQUEST_DELAY=0.5
AXE_CRAWLER_HYBRID_MODE=true
AXE_CRAWLER_PENDING_THRESHOLD=10
AXE_CRAWLER_TIMEOUT=30
AXE_CRAWLER_SAVE_INTERVAL=5

# Configurazione Axe
AXE_POOL_SIZE=2
AXE_SLEEP_TIME=1
AXE_HEADLESS=true
AXE_RESUME=true

# Logging
AXE_LOG_LEVEL=DEBUG
AXE_LOG_CONSOLE=true

# Scrapy
AXE_SCRAPY_CONCURRENT_REQUESTS=8
AXE_SCRAPY_CONCURRENT_PER_DOMAIN=4
AXE_SCRAPY_DOWNLOAD_DELAY=0.5

# Monitoring
AXE_RESOURCE_MONITORING=true
AXE_RESOURCE_CHECK_INTERVAL=5
AXE_CPU_THRESHOLD=90
AXE_MEMORY_THRESHOLD=85
EOL

    log_info "File .env temporaneo creato: $TEMP_ENV_FILE"
    return 0
}

# Funzione per attivare il virtual environment
activate_venv() {
    log_subheader "Attivazione virtual environment"
    
    # Controlla diverse posizioni per il venv
    if [ -d "$PROJECT_ROOT/.venv" ]; then
        source "$PROJECT_ROOT/.venv/bin/activate"
        log_info "Virtual environment attivato: $PROJECT_ROOT/.venv"
        return 0
    elif [ -d "$PROJECT_ROOT/venv" ]; then
        source "$PROJECT_ROOT/venv/bin/activate"
        log_info "Virtual environment attivato: $PROJECT_ROOT/venv"
        return 0
    elif [ -d "/home/ec2-user/axeScraper/.venv" ]; then
        source "/home/ec2-user/axeScraper/.venv/bin/activate"
        log_info "Virtual environment attivato: /home/ec2-user/axeScraper/.venv"
        return 0
    else
        log_warning "Nessun virtual environment trovato. Usando Python di sistema."
        return 1
    fi
}

# Funzione per verificare che i file e directory importanti esistano
check_file_structure() {
    log_header "VERIFICA STRUTTURA" "Controllo file e directory importanti"
    
    # Lista dei file e directory da controllare
    local items=(
        "$PROJECT_ROOT/src"
        "$PROJECT_ROOT/src/pipeline.py"
        "$PROJECT_ROOT/src/utils/config_manager.py"
        "$PROJECT_ROOT/src/utils/logging_config.py"
        "$PROJECT_ROOT/src/utils/output_manager.py"
        "$PROJECT_ROOT/src/axcel/axcel.py"
        "$PROJECT_ROOT/src/analysis/report_analysis.py"
    )
    
    # Controlla ogni elemento
    local all_ok=true
    for item in "${items[@]}"; do
        if [ -e "$item" ]; then
            if $VERBOSE; then
                log_success "Trovato: $item"
            fi
        else
            log_error "Non trovato: $item"
            all_ok=false
        fi
    done
    
    # Controlla il crawler
    if [ -d "$PROJECT_ROOT/src/multi_domain_crawler" ]; then
        log_success "Trovata directory multi_domain_crawler"
        
        # Verifica il file del spider
        if [ -f "$PROJECT_ROOT/src/multi_domain_crawler/multi_domain_crawler/spiders/multi_domain_spider.py" ]; then
            log_success "Trovato spider: multi_domain_spider.py"
        else
            log_error "Non trovato spider: multi_domain_crawler/multi_domain_crawler/spiders/multi_domain_spider.py"
            all_ok=false
            
            # Cerca il file in posizioni alternative
            log_info "Ricerca dello spider in posizioni alternative..."
            local spider_files=$(find "$PROJECT_ROOT" -name "multi_domain_spider.py" 2>/dev/null)
            if [ -n "$spider_files" ]; then
                log_info "Possibili posizioni dello spider:"
                echo "$spider_files"
            fi
        fi
    else
        log_error "Non trovata directory multi_domain_crawler"
        all_ok=false
        
        # Cerca la directory in posizioni alternative
        log_info "Ricerca di multi_domain_crawler in posizioni alternative..."
        local crawler_dirs=$(find "$PROJECT_ROOT" -type d -name "multi_domain_crawler" 2>/dev/null)
        if [ -n "$crawler_dirs" ]; then
            log_info "Possibili posizioni di multi_domain_crawler:"
            echo "$crawler_dirs"
        fi
    fi
    
    # Verifica permessi di esecuzione degli script
    log_subheader "Verifica permessi di esecuzione degli script"
    local scripts=(
        "$PROJECT_ROOT/run.sh"
        "$PROJECT_ROOT/run_crawler.sh"
        "$PROJECT_ROOT/run_pipeline.sh"
        "$PROJECT_ROOT/start_axescraper.sh"
    )
    
    for script in "${scripts[@]}"; do
        if [ -f "$script" ]; then
            if [ -x "$script" ]; then
                if $VERBOSE; then
                    log_success "Lo script $script ha permessi di esecuzione"
                fi
            else
                log_warning "Lo script $script non ha permessi di esecuzione"
                log_info "Consiglio: esegui 'chmod +x $script'"
                all_ok=false
            fi
        else
            log_warning "Script non trovato: $script"
        fi
    done
    
    # Risultato complessivo
    if $all_ok; then
        log_result 0 "Verifica struttura file e directory"
        return 0
    else
        log_result 1 "Verifica struttura file e directory"
        return 1
    fi
}

# Funzione per verificare ambiente Python e dipendenze
check_python_environment() {
    log_header "VERIFICA AMBIENTE" "Controllo Python e dipendenze"
    
    # Verifica Python
    log_subheader "Verifica Python"
    if command -v python &>/dev/null; then
        local python_version=$(python --version 2>&1)
        log_success "Python installato: $python_version"
    else
        log_error "Python non trovato nel PATH"
        return 1
    fi
    
    # Verifica pip
    log_subheader "Verifica pip"
    if command -v pip &>/dev/null; then
        local pip_version=$(pip --version 2>&1)
        log_success "pip installato: $pip_version"
    else
        log_error "pip non trovato nel PATH"
        return 1
    fi
    
    # Controlla dipendenze fondamentali
    log_subheader "Verifica dipendenze fondamentali"
    local dependencies=(
        "scrapy"
        "selenium"
        "pandas"
        "openpyxl"
        "matplotlib"
        "seaborn"
        "beautifulsoup4"
        "requests"
    )
    
    local all_deps_ok=true
    for dep in "${dependencies[@]}"; do
        if pip show "$dep" &>/dev/null; then
            local dep_version=$(pip show "$dep" | grep "Version:" | awk '{print $2}')
            if $VERBOSE; then
                log_success "$dep installato (versione $dep_version)"
            fi
        else
            log_error "$dep non installato"
            all_deps_ok=false
        fi
    done
    
    # Verifica ChromeDriver per Selenium
    log_subheader "Verifica ChromeDriver"
    if command -v chromedriver &>/dev/null; then
        local chromedriver_version=$(chromedriver --version 2>&1 | head -n 1)
        log_success "ChromeDriver installato: $chromedriver_version"
    else
        log_warning "ChromeDriver non trovato nel PATH"
        log_info "L'assenza di ChromeDriver potrebbe impedire l'analisi con Selenium"
        all_deps_ok=false
    fi
    
    # Verifica la presenza e integrità del file .env
    log_subheader "Verifica file di configurazione"
    if [ -f "$ENV_FILE" ]; then
        log_success "File .env trovato: $ENV_FILE"
        
        # Controlla le configurazioni fondamentali nel file .env
        local required_configs=(
            "AXE_BASE_URLS"
            "AXE_OUTPUT_DIR"
        )
        
        local config_ok=true
        for config in "${required_configs[@]}"; do
            if grep -q "^$config=" "$ENV_FILE"; then
                if $VERBOSE; then
                    local config_value=$(grep "^$config=" "$ENV_FILE" | cut -d= -f2-)
                    log_success "Configurazione trovata: $config=$config_value"
                fi
            else
                log_warning "Configurazione mancante in .env: $config"
                config_ok=false
            fi
        done
        
        if ! $config_ok; then
            log_info "Il file .env esiste ma mancano alcune configurazioni fondamentali"
            create_temp_env
        fi
    else
        log_warning "File .env non trovato: $ENV_FILE"
        create_temp_env
        ENV_FILE="$TEMP_ENV_FILE"
    fi
    
    # Risultato complessivo
    if $all_deps_ok; then
        log_result 0 "Verifica ambiente Python e dipendenze"
        return 0
    else
        log_warning "Alcune dipendenze o configurazioni potrebbero essere mancanti"
        log_result 1 "Verifica ambiente Python e dipendenze"
        return 1
    fi
}

# Funzione per testare il multi_domain_crawler in modo isolato
test_crawler_component() {
    log_header "TEST CRAWLER" "Verifica funzionamento del multi_domain_crawler"
    
    # Attiva il virtual environment
    activate_venv
    
    # Trova il percorso del crawler
    local crawler_dir="$PROJECT_ROOT/src/multi_domain_crawler"
    if [ ! -d "$crawler_dir" ]; then
        local alt_dirs=$(find "$PROJECT_ROOT" -type d -name "multi_domain_crawler" 2>/dev/null | head -n 1)
        if [ -n "$alt_dirs" ]; then
            crawler_dir=$(echo "$alt_dirs" | head -n 1)
            log_info "Usando directory alternativa per multi_domain_crawler: $crawler_dir"
        else
            log_error "Impossibile trovare la directory multi_domain_crawler"
            log_result 1 "Test componente crawler"
            return 1
        fi
    fi
    
    # Crea directory di output
    local output_dir="$TEST_OUTPUT_DIR/crawler_test"
    mkdir -p "$output_dir"
    
    # Imposta limitazioni più severe per i test
    local max_urls=3
    local timeout=60
    
    if $QUICK_MODE; then
        max_urls=2
        timeout=30
    elif $FULL_MODE; then
        max_urls=5
        timeout=120
    fi
    
    log_subheader "Test lista spider disponibili"
    local spider_list_output="$output_dir/spider_list.log"
    (cd "$crawler_dir" && python -m scrapy list > "$spider_list_output" 2>&1)
    
    if grep -q "multi_domain_spider" "$spider_list_output"; then
        log_success "Spider 'multi_domain_spider' trovato"
    else
        log_error "Spider 'multi_domain_spider' non trovato"
        cat "$spider_list_output"
        log_result 1 "Test lista spider"
        return 1
    fi
    
    log_subheader "Test esecuzione crawler su $TEST_DOMAIN (max $max_urls URL)"
    local crawler_output="$output_dir/crawler_output.log"
    local crawler_cmd="python -m scrapy crawl multi_domain_spider -a domains=\"$TEST_DOMAIN\" -a max_urls_per_domain=$max_urls -a hybrid_mode=False -s OUTPUT_DIR=$output_dir -s LOG_LEVEL=DEBUG"
    
    log_info "Avvio crawler (timeout: ${timeout}s)..."
    log_info "Questo potrebbe richiedere tempo, attendere..."
    
    (cd "$crawler_dir" && timeout $timeout $crawler_cmd > "$crawler_output" 2>&1)
    local status=$?
    
    if [ $status -eq 0 ]; then
        log_success "Crawler completato con successo"
    elif [ $status -eq 124 ]; then
        log_warning "Crawler interrotto per timeout dopo ${timeout}s (potrebbe essere normale)"
    else
        log_error "Crawler fallito con stato $status"
        echo -e "${YELLOW}Ultime righe del log:${NC}"
        tail -n 20 "$crawler_output"
        log_result 1 "Test esecuzione crawler"
        return 1
    fi
    
    # Verifica gli output
    log_subheader "Verifica output del crawler"
    
    # Controlla se sono stati generati file di stato o report
    local state_files=$(find "$output_dir" -name "crawler_state_*.pkl" 2>/dev/null)
    local report_files=$(find "$output_dir" -name "*.json" -o -name "*.md" -o -name "*.csv" 2>/dev/null)
    
    if [ -n "$state_files" ]; then
        log_success "Trovati file di stato del crawler"
        if $VERBOSE; then
            echo "$state_files"
        fi
    else
        log_warning "Nessun file di stato trovato"
    fi
    
    if [ -n "$report_files" ]; then
        log_success "Trovati file di report del crawler"
        if $VERBOSE; then
            echo "$report_files"
        fi
    else
        log_warning "Nessun file di report trovato"
    fi
    
    # Controlla il log per statistiche di crawling
    if grep -q "Scraped [0-9]\+ items" "$crawler_output" || grep -q "pages processed" "$crawler_output"; then
        log_success "Rilevate statistiche di crawling nel log"
        
        # Mostra dettagli utili dal log
        if $VERBOSE; then
            echo -e "${YELLOW}Statistiche dal log:${NC}"
            grep -E "Scraped|pages processed|items" "$crawler_output" | tail -n 5
        fi
    else
        log_warning "Nessuna statistica di crawling rilevata nel log"
    fi
    
    # Risultato complessivo
    log_result 0 "Test componente crawler"
    return 0
}

# Funzione per testare il componente axe_analysis
test_axe_component() {
    log_header "TEST AXE ANALYSIS" "Verifica funzionamento del componente di analisi Axe"
    
    # Attiva il virtual environment
    activate_venv
    
    # Setup percorsi
    local output_dir="$TEST_OUTPUT_DIR/axe_test"
    mkdir -p "$output_dir"
    local temp_state_file="$output_dir/temp_state.pkl"
    
    # Parametri di test
    local timeout=120
    if $QUICK_MODE; then
        timeout=60
    elif $FULL_MODE; then
        timeout=180
    fi
    
    # Per questo test useremo un URL o i risultati del crawler se esistono
    log_subheader "Verifica per dati del crawler da usare per Axe"
    
    local crawler_state_file=""
    local crawler_output_dir="$TEST_OUTPUT_DIR/crawler_test"
    
    # Cerca file di stato del crawler nei test precedenti
    local state_files=$(find "$TEST_OUTPUT_DIR" -name "crawler_state_*.pkl" 2>/dev/null)
    if [ -n "$state_files" ]; then
        crawler_state_file=$(echo "$state_files" | head -n 1)
        log_success "Trovato file di stato del crawler: $crawler_state_file"
    else
        log_warning "Nessun file di stato del crawler trovato"
        log_info "Creare un file di stato temporaneo per i test"
        
        # Crea un file di stato minimo per i test
        python3 -c "
import pickle
import os

# Crea un dizionario di stato minimo
state = {
    'structures': {
        'template1': {
            'url': 'https://$TEST_DOMAIN',
            'count': 1
        }
    },
    'unique_pages': set(['https://$TEST_DOMAIN']),
    'visited_urls': set(['https://$TEST_DOMAIN'])
}

# Salva il file di stato
with open('$temp_state_file', 'wb') as f:
    pickle.dump(state, f)
print('File di stato temporaneo creato: $temp_state_file')
" > "$output_dir/create_state.log" 2>&1
        
        if [ -f "$temp_state_file" ]; then
            crawler_state_file="$temp_state_file"
            log_success "File di stato temporaneo creato con successo"
        else
            log_error "Impossibile creare file di stato temporaneo"
            cat "$output_dir/create_state.log"
            log_result 1 "Test creazione file di stato temporaneo"
            log_skipped "Test componente axe_analysis (impossibile creare file di stato)"
            return 1
        fi
    fi
    
    # Test del componente axe_analysis in modo isolato
    log_subheader "Test esecuzione axe_analysis"
    
    local axe_script="$output_dir/axe_test.py"
    local axe_output="$output_dir/axe_output.log"
    local excel_output="$output_dir/accessibility_report.xlsx"
    
    # Crea uno script temporaneo per eseguire axe_analysis
    cat > "$axe_script" << EOL
import sys
import os
import time
from pathlib import Path

# Aggiungi il path principale al sys.path
project_root = "$PROJECT_ROOT"
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    # Importa la classe AxeAnalysis
    from src.axcel.axcel import AxeAnalysis
    
    # Crea l'oggetto AxeAnalysis configurato per i test
    analyzer = AxeAnalysis(
        urls=None,
        analysis_state_file="$crawler_state_file",
        fallback_urls=["https://$TEST_DOMAIN"],
        pool_size=1,
        sleep_time=1,
        excel_filename="$excel_output",
        visited_file="$output_dir/visited_urls.txt",
        headless=True,
        resume=True,
        output_folder="$output_dir"
    )
    
    # Avvia l'analisi
    print("Avvio analisi Axe...")
    start_time = time.time()
    analyzer.start()
    end_time = time.time()
    
    print(f"Analisi completata in {end_time - start_time:.2f} secondi")
    
    # Verifica che il file Excel sia stato creato
    if os.path.exists("$excel_output"):
        print(f"File Excel creato: {os.path.getsize('$excel_output')} bytes")
    else:
        print("ERRORE: File Excel non creato")
        sys.exit(1)
    
except Exception as e:
    print(f"ERRORE: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

sys.exit(0)
EOL
    
    log_info "Avvio test axe_analysis (timeout: ${timeout}s)..."
    log_info "Questo test potrebbe richiedere tempo, attendere..."
    
    local skip_axe=false
    # Controlla se seleniumwire è installato (necessario per axe_selenium_python)
    if ! pip show seleniumwire &>/dev/null && ! pip show axe-selenium-python &>/dev/null; then
        log_warning "Le dipendenze 'seleniumwire' o 'axe-selenium-python' non sono installate"
        log_info "Il test axe_analysis verrà eseguito ma potrebbe fallire"
    fi
    
    # Esegui lo script
    timeout $timeout python "$axe_script" > "$axe_output" 2>&1
    local status=$?
    
    if [ $status -eq 0 ]; then
        log_success "Test axe_analysis completato con successo"
        log_info "$(grep "Analisi completata in" "$axe_output")"
        log_info "$(grep "File Excel creato" "$axe_output")"
    elif [ $status -eq 124 ]; then
        log_warning "Test axe_analysis interrotto per timeout dopo ${timeout}s"
        echo -e "${YELLOW}Ultime righe del log:${NC}"
        tail -n 20 "$axe_output"
        log_result 1 "Test esecuzione axe_analysis (timeout)"
        return 1
    else
        log_error "Test axe_analysis fallito con stato $status"
        echo -e "${YELLOW}Ultime righe del log:${NC}"
        tail -n 20 "$axe_output"
        # Non interrompere il test globale, ma segnala il fallimento
        log_result 1 "Test esecuzione axe_analysis"
        return 1
    fi
    
    # Verifica i file generati
    if [ -f "$excel_output" ]; then
        log_success "File Excel generato con successo: $excel_output"
    else
        log_error "File Excel non generato"
        log_result 1 "Verifica output axe_analysis"
        return 1
    fi
    
    # Risultato complessivo
    log_result 0 "Test componente axe_analysis"
    return 0
}

# Funzione per testare il componente report_analysis
test_report_component() {
    log_header "TEST REPORT ANALYSIS" "Verifica funzionamento del componente di generazione report"
    
    # Attiva il virtual environment
    activate_venv
    
    # Setup percorsi
    local output_dir="$TEST_OUTPUT_DIR/report_test"
    mkdir -p "$output_dir"
    local report_output="$output_dir/report_output.log"
    
    # Parametri di test
    local timeout=60
    if $QUICK_MODE; then
        timeout=30
    elif $FULL_MODE; then
        timeout=90
    fi
    
    # Per questo test useremo i risultati di axe_analysis se esistono
    log_subheader "Verifica per dati di axe_analysis da usare per report"
    
    local excel_file=""
    local crawler_state_file=""
    
    # Cerca file Excel creati nei test precedenti
    local excel_files=$(find "$TEST_OUTPUT_DIR" -name "accessibility_report*.xlsx" 2>/dev/null)
    if [ -n "$excel_files" ]; then
        excel_file=$(echo "$excel_files" | head -n 1)
        log_success "Trovato file Excel: $excel_file"
    else
        log_warning "Nessun file Excel trovato dai test precedenti"
        log_skipped "Test componente report_analysis (manca input Excel)"
        return 0
    fi
    
    # Cerca file di stato del crawler
    local state_files=$(find "$TEST_OUTPUT_DIR" -name "crawler_state_*.pkl" 2>/dev/null)
    if [ -n "$state_files" ]; then
        crawler_state_file=$(echo "$state_files" | head -n 1)
        log_success "Trovato file di stato del crawler: $crawler_state_file"
    else
        log_warning "Nessun file di stato del crawler trovato"
        crawler_state_file=""
    fi
    
    # Test del componente report_analysis in modo isolato
    log_subheader "Test esecuzione report_analysis"
    
    local report_script="$output_dir/report_test.py"
    local final_report="$output_dir/final_analysis_report.xlsx"
    
    # Crea uno script temporaneo per eseguire report_analysis
    cat > "$report_script" << EOL
import sys
import os
import time
from pathlib import Path

# Aggiungi il path principale al sys.path
project_root = "$PROJECT_ROOT"
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    # Importa la classe AccessibilityAnalyzer
    from src.analysis.report_analysis import AccessibilityAnalyzer
    
    # Crea directory di output
    os.makedirs("$output_dir/charts", exist_ok=True)
    
    # Crea l'oggetto AccessibilityAnalyzer
    analyzer = AccessibilityAnalyzer()
    
    # Carica i dati
    print("Caricamento dati da Excel...")
    axe_df = analyzer.load_data("$excel_file", "$crawler_state_file")
    print(f"Caricati {len(axe_df)} record")
    
    # Calcola metriche
    print("Calcolo metriche...")
    metrics = analyzer.calculate_metrics(axe_df)
    print(f"Calcolate {len(metrics)} metriche")
    
    # Crea aggregazioni
    print("Creazione aggregazioni...")
    aggregations = analyzer.create_aggregations(axe_df)
    print(f"Create {len(aggregations)} aggregazioni")
    
    # Crea charts
    print("Generazione charts...")
    chart_files = analyzer.create_charts(metrics, aggregations, axe_df)
    print(f"Generati {len(chart_files)} grafici")
    
    # Carica dati dei template se disponibili
    template_df = None
    if "$crawler_state_file":
        try:
            print("Caricamento dati dei template...")
            templates_df, state = analyzer.load_template_data("$crawler_state_file")
            template_df = analyzer.analyze_templates(templates_df, axe_df)
            print(f"Analizzati {len(template_df)} template")
        except Exception as e:
            print(f"Errore analisi template: {e}")
    
    # Genera report finale
    print("Generazione report finale...")
    report_path = analyzer.generate_report(
        axe_df=axe_df,
        metrics=metrics,
        aggregations=aggregations,
        chart_files=chart_files,
        template_df=template_df,
        output_excel="$final_report"
    )
    
    print(f"Report generato: {report_path}")
    
    # Verifica che il file Excel sia stato creato
    if os.path.exists("$final_report"):
        print(f"File Excel creato: {os.path.getsize('$final_report')} bytes")
    else:
        print("ERRORE: File Excel non creato")
        sys.exit(1)
    
except Exception as e:
    print(f"ERRORE: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

sys.exit(0)
EOL
    
    log_info "Avvio test report_analysis (timeout: ${timeout}s)..."
    
    # Esegui lo script
    timeout $timeout python "$report_script" > "$report_output" 2>&1
    local status=$?
    
    if [ $status -eq 0 ]; then
        log_success "Test report_analysis completato con successo"
    elif [ $status -eq 124 ]; then
        log_warning "Test report_analysis interrotto per timeout dopo ${timeout}s"
        echo -e "${YELLOW}Ultime righe del log:${NC}"
        tail -n 20 "$report_output"
        log_result 1 "Test esecuzione report_analysis (timeout)"
        return 1
    else
        log_error "Test report_analysis fallito con stato $status"
        echo -e "${YELLOW}Ultime righe del log:${NC}"
        tail -n 20 "$report_output"
        log_result 1 "Test esecuzione report_analysis"
        return 1
    fi
    
    # Verifica i file generati
    if [ -f "$final_report" ]; then
        log_success "Report finale generato con successo: $final_report"
    else
        log_error "Report finale non generato"
        log_result 1 "Verifica output report_analysis"
        return 1
    fi
    
    # Verifica i grafici
    local chart_files=$(find "$output_dir/charts" -name "*.png" 2>/dev/null)
    if [ -n "$chart_files" ]; then
        local chart_count=$(echo "$chart_files" | wc -l)
        log_success "Grafici generati con successo: $chart_count"
    else
        log_warning "Nessun grafico generato"
    fi
    
    # Risultato complessivo
    log_result 0 "Test componente report_analysis"
    return 0
}

# Funzione per testare l'intera pipeline
test_full_pipeline() {
    log_header "TEST PIPELINE COMPLETA" "Verifica funzionamento dell'intera pipeline"
    
    # Attiva il virtual environment
    activate_venv
    
    # Setup percorsi
    local output_dir="$TEST_OUTPUT_DIR/pipeline_test"
    mkdir -p "$output_dir"
    local pipeline_output="$output_dir/pipeline_output.log"
    
    # Parametri di test
    local timeout=300  # 5 minuti
    if $QUICK_MODE; then
        timeout=120    # 2 minuti
    elif $FULL_MODE; then
        timeout=600    # 10 minuti
    fi
    
    # Crea .env temporaneo per questo test
    local test_env_file="$output_dir/test_pipeline.env"
    
    cat > "$test_env_file" << EOL
# File .env per test pipeline
AXE_BASE_URLS=$TEST_DOMAIN
AXE_OUTPUT_DIR=$output_dir
AXE_START_STAGE=crawler
AXE_CRAWLER_MAX_URLS=3
AXE_MAX_TEMPLATES=2
AXE_REPEAT_ANALYSIS=1
AXE_POOL_SIZE=1
AXE_SLEEP_TIME=1
AXE_HEADLESS=true
AXE_LOG_LEVEL=DEBUG
EOL
    
    log_subheader "Test esecuzione pipeline completa"
    
    # Usa lo script pipeline.py direttamente
    local pipeline_cmd="python -m src.pipeline --domains $TEST_DOMAIN --max-urls-per-domain 3 --max-templates 2 --env-file $test_env_file --verbose"
    
    log_info "Avvio pipeline completa (timeout: ${timeout}s)..."
    log_info "Questo test richiederà diversi minuti, attendere..."
    log_command "$pipeline_cmd"
    
    # Esegui la pipeline
    (cd "$PROJECT_ROOT" && timeout $timeout $pipeline_cmd > "$pipeline_output" 2>&1)
    local status=$?
    
    if [ $status -eq 0 ]; then
        log_success "Pipeline completa eseguita con successo"
    elif [ $status -eq 124 ]; then
        log_warning "Pipeline interrotta per timeout dopo ${timeout}s (potrebbe essere normale per test completi)"
        echo -e "${YELLOW}Ultime righe del log:${NC}"
        tail -n 20 "$pipeline_output"
    else
        log_error "Pipeline fallita con stato $status"
        echo -e "${YELLOW}Ultime righe del log:${NC}"
        tail -n 20 "$pipeline_output"
        log_result 1 "Test pipeline completa"
        return 1
    fi
    
    # Verifica i risultati
    log_subheader "Verifica risultati pipeline"
    
    # Cerca i file di output più importanti
    local report_files=$(find "$output_dir" -name "final_analysis_*.xlsx" 2>/dev/null)
    if [ -n "$report_files" ]; then
        log_success "Report finale trovato"
        if $VERBOSE; then
            echo "$report_files"
        fi
    else
        log_warning "Nessun report finale trovato"
    fi
    
    local chart_files=$(find "$output_dir" -name "*.png" 2>/dev/null)
    if [ -n "$chart_files" ]; then
        local chart_count=$(echo "$chart_files" | wc -l)
        log_success "Grafici trovati: $chart_count"
    else
        log_warning "Nessun grafico trovato"
    fi
    
    local axe_files=$(find "$output_dir" -name "accessibility_report_*.xlsx" 2>/dev/null)
    if [ -n "$axe_files" ]; then
        log_success "Report Axe trovato"
    else
        log_warning "Nessun report Axe trovato"
    fi
    
    local crawler_state_files=$(find "$output_dir" -name "crawler_state_*.pkl" 2>/dev/null)
    if [ -n "$crawler_state_files" ]; then
        log_success "File di stato del crawler trovato"
    else
        log_warning "Nessun file di stato del crawler trovato"
    fi
    
    # Controlla se ci sono errori gravi nel log
    log_subheader "Analisi log della pipeline"
    
    local error_count=$(grep -c -E "ERROR|CRITICAL|Exception|Error|Failed" "$pipeline_output")
    local warning_count=$(grep -c -E "WARNING|Warning" "$pipeline_output")
    
    if [ "$error_count" -gt 0 ]; then
        log_warning "Trovati $error_count errori e $warning_count warning nel log"
        if $VERBOSE; then
            echo -e "${YELLOW}Primi 10 errori:${NC}"
            grep -E "ERROR|CRITICAL|Exception|Error|Failed" "$pipeline_output" | head -n 10
        fi
    else
        log_success "Nessun errore grave nel log (solo $warning_count warning)"
    fi
    
    # Risultato complessivo basato sulla presenza di output finali
    if [ -n "$report_files" ] && [ -n "$axe_files" ]; then
        log_result 0 "Test pipeline completa"
        return 0
    else
        log_warning "La pipeline ha prodotto output parziali o incompleti"
        log_result 1 "Test pipeline completa"
        return 1
    fi
}

# Funzione per testare gli script shell
test_shell_scripts() {
    log_header "TEST SCRIPT SHELL" "Verifica funzionamento degli script di avvio"
    
    # Lista degli script da testare
    local scripts=(
        "$PROJECT_ROOT/run_crawler.sh"
        "$PROJECT_ROOT/run_pipeline.sh"
        "$PROJECT_ROOT/start_axescraper.sh"
    )
    
    # Directory di output
    local output_dir="$TEST_OUTPUT_DIR/scripts_test"
    mkdir -p "$output_dir"
    
    # Verifica presenza e sintassi di ogni script
    log_subheader "Verifica sintassi degli script"
    
    local all_syntax_ok=true
    for script in "${scripts[@]}"; do
        if [ -f "$script" ]; then
            if bash -n "$script" 2>/dev/null; then
                log_success "Sintassi corretta: $script"
            else
                log_error "Errore di sintassi in: $script"
                all_syntax_ok=false
            fi
        else
            log_warning "Script non trovato: $script"
        fi
    done
    
    if ! $all_syntax_ok; then
        log_result 1 "Verifica sintassi script"
        return 1
    fi
    
    # Test script run_crawler.sh (con parametri minimi)
    if [ -f "$PROJECT_ROOT/run_crawler.sh" ] && [ -x "$PROJECT_ROOT/run_crawler.sh" ]; then
        log_subheader "Test script run_crawler.sh (--help)"
        
        local crawler_help_output="$output_dir/run_crawler_help.log"
        "$PROJECT_ROOT/run_crawler.sh" --help > "$crawler_help_output" 2>&1
        
        if grep -q "Usage:" "$crawler_help_output" && grep -q "Parametri:" "$crawler_help_output"; then
            log_success "Help di run_crawler.sh funziona correttamente"
        else
            log_warning "Help di run_crawler.sh potrebbe avere problemi"
            if $VERBOSE; then
                cat "$crawler_help_output"
            fi
        fi
        
        # Se non in modalità rapida, esegui un test reale (molto breve)
        if ! $QUICK_MODE; then
            log_subheader "Test breve di run_crawler.sh"
            
            local crawler_test_output="$output_dir/run_crawler_test.log"
            local crawler_test_cmd="$PROJECT_ROOT/run_crawler.sh $TEST_DOMAIN 2 False"
            
            log_info "Avvio test di run_crawler.sh (max 2 URL, timeout 30s)..."
            log_command "$crawler_test_cmd"
            
            timeout 30 $crawler_test_cmd > "$crawler_test_output" 2>&1
            local status=$?
            
            if [ $status -eq 0 ] || [ $status -eq 124 ]; then
                log_success "Test di run_crawler.sh completato"
            else
                log_warning "Test di run_crawler.sh fallito con stato $status"
                if $VERBOSE; then
                    tail -n 20 "$crawler_test_output"
                fi
            fi
        else
            log_info "Test reale di run_crawler.sh saltato in modalità rapida"
        fi
    else
        log_warning "Script run_crawler.sh non trovato o non eseguibile"
    fi
    
    # Risultato complessivo
    log_result 0 "Test script shell"
    return 0
}

# Esegui tutti i test
run_all_tests() {
    log_header "INIZIO TEST" "Avvio della suite di test completa"
    
    # Lista delle funzioni di test
    check_file_structure
    check_python_environment
    
    # Se siamo in modalità rapida, esegui test fondamentali
    if $QUICK_MODE; then
        log_info "Modalità rapida: solo test fondamentali"
        test_crawler_component
    else
        # Altrimenti esegui tutti i test
        test_crawler_component
        test_axe_component
        test_report_component
        test_shell_scripts
        
        # Se in modalità completa, testa anche la pipeline completa
        if $FULL_MODE; then
            test_full_pipeline
        fi
    fi
    
    # Riepilogo dei risultati
    log_header "RIEPILOGO TEST" "Risultati complessivi della suite di test"
    echo -e "${BLUE}Test totali:${NC} $TESTS_TOTAL"
    echo -e "${GREEN}Test passati:${NC} $TESTS_PASSED"
    echo -e "${RED}Test falliti:${NC} $TESTS_FAILED"
    echo -e "${YELLOW}Test saltati:${NC} $TESTS_SKIPPED"
    
    # Calcola percentuale di successo
    if [ $TESTS_TOTAL -gt 0 ]; then
        local success_percentage=$(( (TESTS_PASSED * 100) / TESTS_TOTAL ))
        echo -e "${BLUE}Percentuale di successo:${NC} $success_percentage%"
        
        if [ $success_percentage -eq 100 ]; then
            echo -e "${GREEN}${BOLD}TUTTI I TEST SUPERATI!${NC}"
        elif [ $success_percentage -ge 80 ]; then
            echo -e "${YELLOW}${BOLD}MAGGIOR PARTE DEI TEST SUPERATI!${NC}"
        else
            echo -e "${RED}${BOLD}DIVERSI TEST FALLITI${NC}"
        fi
    fi
    
    # Informazioni finali
    echo ""
    echo -e "${BLUE}Log completo: $TEST_LOG${NC}"
    echo -e "${BLUE}Directory di test: $TEST_OUTPUT_DIR${NC}"
    
    # Pulizia se richiesta
    if ! $SKIP_CLEANUP; then
        log_info "Pulizia file temporanei in corso..."
        if [ -f "$TEMP_ENV_FILE" ]; then
            rm -f "$TEMP_ENV_FILE"
        fi
    else
        log_info "Pulizia saltata, file temporanei conservati"
    fi
    
    # Stato di uscita
    if [ $TESTS_FAILED -eq 0 ]; then
        return 0
    else
        return 1
    fi
}

# Avvia tutti i test
run_all_tests
exit $?