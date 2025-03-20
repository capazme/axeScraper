#!/bin/bash
# Script per correggere i potenziali problemi di percorso nella pipeline

# Assicurati che i percorsi degli output siano creati correttamente
PIPELINE_PATH="/home/ec2-user/axeScraper/src/pipeline.py"

# Verifica ed eventualmente aggiorna il file pipeline.py
if [ -f "$PIPELINE_PATH" ]; then
    echo "Controllo pipeline.py per potenziali problemi di percorso..."
    
    # Backup
    cp "$PIPELINE_PATH" "${PIPELINE_PATH}.bak"
    echo "Backup creato: ${PIPELINE_PATH}.bak"
    
    # Aggiungi debug logging per tracciare i percorsi
    sed -i '/^import asyncio/a import os.path' "$PIPELINE_PATH"
    sed -i '/start_time = time.time()/a \    # Debug percorsi\n    logger.info(f"PROJECT_ROOT: {os.path.abspath(os.path.dirname(__file__))}")\n    logger.info(f"CRAWLER_DIR: {os.path.abspath(os.path.join(os.path.dirname(__file__), \"multi_domain_crawler\"))}")' "$PIPELINE_PATH"
    
    # Correggi il percorso del crawler nel metodo run_crawler
    sed -i 's|cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "multi_domain_crawler"))|cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/multi_domain_crawler"))|' "$PIPELINE_PATH"
    
    echo "Pipeline.py aggiornato con debug logging e percorsi corretti."
else
    echo "File pipeline.py non trovato in $PIPELINE_PATH"
fi

# Crea un wrapper che usa percorsi assoluti
WRAPPER_PATH="/home/ec2-user/axeScraper/run_pipeline_fixed.sh"
cat > "$WRAPPER_PATH" << 'EOL'
#!/bin/bash
# Script wrapper per la pipeline con percorsi corretti

# Directory corrente
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$SCRIPT_DIR"

# Attiva l'ambiente virtuale
if [ -d "$PROJECT_ROOT/.venv" ]; then
    source "$PROJECT_ROOT/.venv/bin/activate"
    echo "Ambiente virtuale attivato"
fi

# Stampa informazioni di debug
echo "Directory di lavoro: $(pwd)"
echo "PROJECT_ROOT: $PROJECT_ROOT"
echo "Path Python: $(which python)"

# Crea una .env temporanea per il test se non esiste
ENV_FILE="$PROJECT_ROOT/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "File .env non trovato, creando uno temporaneo..."
    cat > "$ENV_FILE" << ENVEOF
# File .env creato automaticamente
AXE_BASE_URLS=iccreabanca.it
AXE_OUTPUT_DIR=$PROJECT_ROOT/output
AXE_START_STAGE=crawler
AXE_CRAWLER_MAX_URLS=20
AXE_MAX_TEMPLATES=10
AXE_REPEAT_ANALYSIS=1
AXE_LOG_LEVEL=DEBUG
AXE_CRAWLER_HYBRID_MODE=true
ENVEOF
    echo "File .env creato: $ENV_FILE"
fi

# Assicurati che la directory di output esista
mkdir -p "$PROJECT_ROOT/output"
mkdir -p "$PROJECT_ROOT/output/logs"

# Parametri opzionali dalla linea di comando
DOMAINS=${1:-""}
MAX_URLS=${2:-20}
MAX_TEMPLATES=${3:-10}
START_STAGE=${4:-"crawler"}

# Costruisci il comando
CMD="python -m src.pipeline"

if [ -n "$DOMAINS" ]; then
    CMD="$CMD --domains \"$DOMAINS\""
fi

CMD="$CMD --max-urls-per-domain $MAX_URLS --max-templates $MAX_TEMPLATES --start-stage $START_STAGE --env-file \"$ENV_FILE\" --verbose"

echo "Esecuzione comando: $CMD"

# Esegui in directory progetto con percorsi assoluti
cd "$PROJECT_ROOT"
eval "$CMD"

STATUS=$?
if [ $STATUS -eq 0 ]; then
    echo "Pipeline completata con successo!"
else
    echo "Pipeline terminata con errori (codice: $STATUS)"
fi

exit $STATUS
EOL

chmod +x "$WRAPPER_PATH"
echo "Wrapper creato: $WRAPPER_PATH"