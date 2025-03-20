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
