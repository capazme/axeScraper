#!/bin/bash
# debug_pipeline.sh - Script per debug interattivo della pipeline axeScraper
# Questo script esegue passo-passo ogni componente della pipeline con feedback dopo ogni fase

# Colori per output migliore
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BLUE='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Directory di base
PROJECT_ROOT="/home/ec2-user/axeScraper"
DEBUG_DIR="$PROJECT_ROOT/debug_output"
ENV_FILE="$PROJECT_ROOT/.env"

# Crea directory debug
mkdir -p "$DEBUG_DIR"
mkdir -p "$DEBUG_DIR/crawler"
mkdir -p "$DEBUG_DIR/axe"
mkdir -p "$DEBUG_DIR/report"
mkdir -p "$DEBUG_DIR/logs"

# Dominio di test
TEST_DOMAIN=${1:-"example.com"}
MAX_URLS=${2:-5}

echo -e "${BLUE}${BOLD}===== Pipeline Debug Interattivo =====${NC}"
echo "Dominio di test: $TEST_DOMAIN"
echo "Max URLs: $MAX_URLS"
echo "Directory output: $DEBUG_DIR"
echo "Environment file: $ENV_FILE"
echo ""

# Attiva virtual environment
if [ -d "$PROJECT_ROOT/.venv" ]; then
    source "$PROJECT_ROOT/.venv/bin/activate"
    echo -e "${GREEN}Ambiente virtuale attivato: $PROJECT_ROOT/.venv${NC}"
else
    echo -e "${YELLOW}Virtual environment non trovato. Usando Python di sistema.${NC}"
fi

# Funzione per chiedere all'utente se continuare
ask_to_continue() {
    echo ""
    read -p "Continuare? (y/n): " choice
    case "$choice" in 
        y|Y ) return 0;;
        * ) return 1;;
    esac
}

# Crea file .env temporaneo se non esiste
if [ ! -f "$ENV_FILE" ] || ! grep -q "AXE_BASE_URLS" "$ENV_FILE"; then
    echo -e "${YELLOW}File .env non trovato o incompleto. Creazione file temporaneo...${NC}"
    
    cat > "$ENV_FILE" << EOL
# File .env generato dal debug_pipeline.sh
AXE_BASE_URLS=$TEST_DOMAIN
AXE_OUTPUT_DIR=$DEBUG_DIR
AXE_START_STAGE=crawler
AXE_CRAWLER_MAX_URLS=$MAX_URLS
AXE_MAX_TEMPLATES=3
AXE_REPEAT_ANALYSIS=1

# Crawler configuration
AXE_CRAWLER_MAX_WORKERS=4
AXE_CRAWLER_HYBRID_MODE=true
AXE_CRAWLER_REQUEST_DELAY=0.5
AXE_CRAWLER_TIMEOUT=30
AXE_CRAWLER_PARSER_WORKERS=2

# Axe configuration
AXE_POOL_SIZE=2
AXE_SLEEP_TIME=1
AXE_HEADLESS=true

# Logging
AXE_LOG_LEVEL=DEBUG
AXE_LOG_CONSOLE=true
EOL
    echo -e "${GREEN}File .env creato: $ENV_FILE${NC}"
fi

# FASE 1: Crawler
echo -e "${BLUE}${BOLD}1. FASE CRAWLER${NC}"
echo "Esecuzione crawler per $TEST_DOMAIN..."
echo "Questa operazione potrebbe richiedere un po' di tempo."

# Verifica percorso crawler
CRAWLER_DIR="$PROJECT_ROOT/src/multi_domain_crawler"
if [ ! -d "$CRAWLER_DIR" ]; then
    echo -e "${YELLOW}Directory crawler non trovata in $CRAWLER_DIR${NC}"
    ALT_CRAWLER=$(find "$PROJECT_ROOT" -type d -name "multi_domain_crawler" | head -n 1)
    if [ -n "$ALT_CRAWLER" ]; then
        CRAWLER_DIR="$ALT_CRAWLER"
        echo -e "${GREEN}Usando directory alternativa: $CRAWLER_DIR${NC}"
    else
        echo -e "${RED}Directory multi_domain_crawler non trovata!${NC}"
        exit 1
    fi
fi

# Esegui il crawler in maniera isolata
cd "$CRAWLER_DIR"
CRAWLER_LOG="$DEBUG_DIR/logs/crawler_debug.log"

echo "Esecuzione crawler con il seguente comando:"
CMD="python -m scrapy crawl multi_domain_spider -a domains=\"$TEST_DOMAIN\" -a max_urls_per_domain=$MAX_URLS -a hybrid_mode=True -s OUTPUT_DIR=$DEBUG_DIR/crawler -s LOG_LEVEL=DEBUG --logfile=$CRAWLER_LOG"
echo $CMD

eval "$CMD"
CRAWLER_STATUS=$?

if [ $CRAWLER_STATUS -eq 0 ]; then
    echo -e "${GREEN}Crawler completato con successo.${NC}"
    # Verifica risultati crawler
    STATE_FILES=$(find "$DEBUG_DIR/crawler" -name "crawler_state_*.pkl" 2>/dev/null)
    REPORT_FILES=$(find "$DEBUG_DIR/crawler" -name "*.json" -o -name "*.md" 2>/dev/null)
    
    if [ -n "$STATE_FILES" ]; then
        STATE_FILE=$(echo "$STATE_FILES" | head -n 1)
        echo -e "${GREEN}File stato crawler: $STATE_FILE${NC}"
    else
        echo -e "${YELLOW}Nessun file stato crawler trovato!${NC}"
    fi
    
    if [ -n "$REPORT_FILES" ]; then
        echo -e "${GREEN}Report crawler generati:${NC}"
        echo "$REPORT_FILES"
    else
        echo -e "${YELLOW}Nessun report crawler trovato!${NC}"
    fi
else
    echo -e "${RED}Crawler fallito con stato $CRAWLER_STATUS${NC}"
    echo "Ultimi log:"
    tail -n 20 "$CRAWLER_LOG"
    exit 1
fi

if ! ask_to_continue; then
    echo "Debug interrotto dall'utente"
    exit 0
fi

# FASE 2: Axe Analysis
echo -e "${BLUE}${BOLD}2. FASE AXE ANALYSIS${NC}"

# Creare script Python per eseguire Axe in modo isolato
AXE_SCRIPT="$DEBUG_DIR/run_axe.py"
AXE_LOG="$DEBUG_DIR/logs/axe_debug.log"

# Trova il file di stato del crawler
STATE_FILE=$(find "$DEBUG_DIR/crawler" -name "crawler_state_*.pkl" 2>/dev/null | head -n 1)
if [ -z "$STATE_FILE" ]; then
    echo -e "${YELLOW}File stato crawler non trovato. Creazione file minimale...${NC}"
    # Crea script Python per generare file stato minimale
    cat > "$DEBUG_DIR/create_state.py" << EOL
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
state_file = '$DEBUG_DIR/crawler/crawler_state_temp.pkl'
with open(state_file, 'wb') as f:
    pickle.dump(state, f)
print(f'File di stato temporaneo creato: {state_file}')
EOL
    python "$DEBUG_DIR/create_state.py"
    STATE_FILE="$DEBUG_DIR/crawler/crawler_state_temp.pkl"
fi

# Crea script per eseguire Axe
cat > "$AXE_SCRIPT" << EOL
import sys
import os
import time
from pathlib import Path

# Aggiungi il path del progetto
sys.path.insert(0, '$PROJECT_ROOT')

try:
    # Importa AxeAnalysis
    from src.axcel.axcel import AxeAnalysis
    
    # Output file
    excel_file = '$DEBUG_DIR/axe/accessibility_report_debug.xlsx'
    visited_file = '$DEBUG_DIR/axe/visited_urls.txt'
    
    print(f"File stato crawler: $STATE_FILE")
    print(f"File Excel output: {excel_file}")
    
    # Crea istanza AxeAnalysis
    analyzer = AxeAnalysis(
        urls=None,
        analysis_state_file="$STATE_FILE",
        fallback_urls=["https://$TEST_DOMAIN"],
        pool_size=1,
        sleep_time=1,
        excel_filename=excel_file,
        visited_file=visited_file,
        headless=True,
        resume=True,
        output_folder="$DEBUG_DIR/axe"
    )
    
    # Esegui analisi
    print("Avvio analisi Axe...")
    start_time = time.time()
    analyzer.start()
    end_time = time.time()
    
    print(f"Analisi completata in {end_time - start_time:.2f} secondi")
    
    # Verifica output
    if os.path.exists(excel_file):
        print(f"File Excel creato: {excel_file} ({os.path.getsize(excel_file)} bytes)")
    else:
        print("ERRORE: File Excel non creato!")
        sys.exit(1)
    
except Exception as e:
    print(f"ERRORE: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

sys.exit(0)
EOL

echo "Esecuzione analisi Axe..."
python "$AXE_SCRIPT" | tee "$AXE_LOG"
AXE_STATUS=$?

if [ $AXE_STATUS -eq 0 ]; then
    echo -e "${GREEN}Analisi Axe completata con successo.${NC}"
    
    # Verifica output Axe
    EXCEL_FILE="$DEBUG_DIR/axe/accessibility_report_debug.xlsx"
    if [ -f "$EXCEL_FILE" ]; then
        echo -e "${GREEN}File Excel generato: $EXCEL_FILE${NC}"
    else
        echo -e "${RED}File Excel non trovato!${NC}"
        exit 1
    fi
else
    echo -e "${RED}Analisi Axe fallita con stato $AXE_STATUS${NC}"
    exit 1
fi

if ! ask_to_continue; then
    echo "Debug interrotto dall'utente"
    exit 0
fi

# FASE 3: Report Analysis
echo -e "${BLUE}${BOLD}3. FASE REPORT ANALYSIS${NC}"

# Creare script Python per eseguire Report Analysis in modo isolato
REPORT_SCRIPT="$DEBUG_DIR/run_report.py"
REPORT_LOG="$DEBUG_DIR/logs/report_debug.log"

# Trova il file Excel generato da Axe
EXCEL_FILE=$(find "$DEBUG_DIR/axe" -name "accessibility_report_*.xlsx" 2>/dev/null | head -n 1)
if [ -z "$EXCEL_FILE" ]; then
    echo -e "${RED}File Excel non trovato. Impossibile eseguire analisi report.${NC}"
    exit 1
fi

# Crea script per eseguire Report Analysis
cat > "$REPORT_SCRIPT" << EOL
import sys
import os
import time
from pathlib import Path

# Aggiungi il path del progetto
sys.path.insert(0, '$PROJECT_ROOT')

try:
    # Importa AccessibilityAnalyzer
    from src.analysis.report_analysis import AccessibilityAnalyzer
    
    # Output file
    final_report = '$DEBUG_DIR/report/final_analysis_report.xlsx'
    
    # Crea directory per charts
    os.makedirs('$DEBUG_DIR/report/charts', exist_ok=True)
    
    print(f"File Excel input: $EXCEL_FILE")
    print(f"File stato crawler: $STATE_FILE")
    print(f"Report finale output: {final_report}")
    
    # Crea istanza AccessibilityAnalyzer
    analyzer = AccessibilityAnalyzer()
    
    # Carica dati
    print("Caricamento dati da Excel...")
    axe_df = analyzer.load_data("$EXCEL_FILE", "$STATE_FILE")
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
    if os.path.exists("$STATE_FILE"):
        try:
            print("Caricamento dati dei template...")
            templates_df, state = analyzer.load_template_data("$STATE_FILE")
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
        output_excel=final_report
    )
    
    print(f"Report generato: {report_path}")
    
    # Verifica output
    if os.path.exists(final_report):
        print(f"Report finale creato: {final_report} ({os.path.getsize(final_report)} bytes)")
        
        # Verifica grafici
        chart_count = len(list(Path('$DEBUG_DIR/report/charts').glob('*.png')))
        print(f"Grafici generati: {chart_count}")
    else:
        print("ERRORE: Report finale non creato!")
        sys.exit(1)
    
except Exception as e:
    print(f"ERRORE: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

sys.exit(0)
EOL

echo "Esecuzione analisi report..."
python "$REPORT_SCRIPT" | tee "$REPORT_LOG"
REPORT_STATUS=$?

if [ $REPORT_STATUS -eq 0 ]; then
    echo -e "${GREEN}Analisi report completata con successo.${NC}"
    
    # Verifica output report
    FINAL_REPORT="$DEBUG_DIR/report/final_analysis_report.xlsx"
    if [ -f "$FINAL_REPORT" ]; then
        echo -e "${GREEN}Report finale generato: $FINAL_REPORT${NC}"
    else
        echo -e "${RED}Report finale non trovato!${NC}"
        exit 1
    fi
    
    # Verifica grafici
    CHARTS=$(find "$DEBUG_DIR/report/charts" -name "*.png" 2>/dev/null)
    CHART_COUNT=$(echo "$CHARTS" | wc -l)
    if [ "$CHART_COUNT" -gt 0 ]; then
        echo -e "${GREEN}Grafici generati: $CHART_COUNT${NC}"
    else
        echo -e "${YELLOW}Nessun grafico generato!${NC}"
    fi
else
    echo -e "${RED}Analisi report fallita con stato $REPORT_STATUS${NC}"
    exit 1
fi

if ! ask_to_continue; then
    echo "Debug interrotto dall'utente"
    exit 0
fi

# FASE 4: Pipeline completa
echo -e "${BLUE}${BOLD}4. PIPELINE COMPLETA${NC}"
echo "Esecuzione della pipeline completa usando src.pipeline direttamente..."

# Ritorna al project root
cd "$PROJECT_ROOT"

# Esegui la pipeline completa
PIPELINE_LOG="$DEBUG_DIR/logs/pipeline_complete.log"
PIPELINE_CMD="python -m src.pipeline --domains $TEST_DOMAIN --max-urls-per-domain $MAX_URLS --max-templates 3 --env-file $ENV_FILE --verbose"

echo "Comando: $PIPELINE_CMD"
echo "Esecuzione (questo potrebbe richiedere tempo)..."

eval "$PIPELINE_CMD" | tee "$PIPELINE_LOG"
PIPELINE_STATUS=$?

if [ $PIPELINE_STATUS -eq 0 ]; then
    echo -e "${GREEN}Pipeline completa eseguita con successo.${NC}"
    
    # Verifica output pipeline
    OUTPUT_DIR=$(grep "AXE_OUTPUT_DIR" "$ENV_FILE" | cut -d= -f2)
    if [ -z "$OUTPUT_DIR" ]; then
        OUTPUT_DIR="$DEBUG_DIR" # Default fallback
    fi
    
    echo -e "${YELLOW}Cercando output pipeline in $OUTPUT_DIR...${NC}"
    
    # Trova report finali
    FINAL_REPORTS=$(find "$OUTPUT_DIR" -name "final_analysis_*.xlsx" 2>/dev/null)
    if [ -n "$FINAL_REPORTS" ]; then
        echo -e "${GREEN}Report finali trovati:${NC}"
        echo "$FINAL_REPORTS"
    else
        echo -e "${RED}Nessun report finale trovato!${NC}"
    fi
    
    # Trova grafici
    CHARTS=$(find "$OUTPUT_DIR" -name "*.png" 2>/dev/null)
    CHART_COUNT=$(echo "$CHARTS" | wc -l)
    if [ "$CHART_COUNT" -gt 0 ]; then
        echo -e "${GREEN}Grafici trovati: $CHART_COUNT${NC}"
    else
        echo -e "${RED}Nessun grafico trovato!${NC}"
    fi
    
    # Trova report Axe
    AXE_REPORTS=$(find "$OUTPUT_DIR" -name "accessibility_report_*.xlsx" 2>/dev/null)
    if [ -n "$AXE_REPORTS" ]; then
        echo -e "${GREEN}Report Axe trovati:${NC}"
        echo "$AXE_REPORTS"
    else
        echo -e "${RED}Nessun report Axe trovato!${NC}"
    fi
    
    # Trova file di stato crawler
    STATE_FILES=$(find "$OUTPUT_DIR" -name "crawler_state_*.pkl" 2>/dev/null)
    if [ -n "$STATE_FILES" ]; then
        echo -e "${GREEN}File stato crawler trovati:${NC}"
        echo "$STATE_FILES"
    else
        echo -e "${RED}Nessun file stato crawler trovato!${NC}"
    fi
else
    echo -e "${RED}Pipeline completa fallita con stato $PIPELINE_STATUS${NC}"
    echo "Ultimi log:"
    tail -n 20 "$PIPELINE_LOG"
    exit 1
fi

# Conclusione
echo -e "${GREEN}${BOLD}Debug pipeline completato con successo!${NC}"
echo "Tutti i componenti hanno funzionato correttamente quando eseguiti separatamente."
echo ""
echo "Riepilogo:"
echo "- Crawler: $([ $CRAWLER_STATUS -eq 0 ] && echo -e "${GREEN}OK${NC}" || echo -e "${RED}FALLITO${NC}")"
echo "- Axe Analysis: $([ $AXE_STATUS -eq 0 ] && echo -e "${GREEN}OK${NC}" || echo -e "${RED}FALLITO${NC}")"
echo "- Report Analysis: $([ $REPORT_STATUS -eq 0 ] && echo -e "${GREEN}OK${NC}" || echo -e "${RED}FALLITO${NC}")"
echo "- Pipeline completa: $([ $PIPELINE_STATUS -eq 0 ] && echo -e "${GREEN}OK${NC}" || echo -e "${RED}FALLITO${NC}")"
echo ""
echo "Directory di debug: $DEBUG_DIR"
echo "Log completi in: $DEBUG_DIR/logs/"

exit 0