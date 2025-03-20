#!/bin/bash
# run.sh - Wrapper per avviare axeScraper con ambiente pulito

# Lista delle variabili da resettare
VARS_TO_RESET=(
  "AXE_CRAWLER_MAX_URLS"
  "AXE_START_STAGE"
  # Aggiungi altre variabili problematiche qui
)

# Resetta tutte le variabili della lista
for var in "${VARS_TO_RESET[@]}"; do
  unset "$var"
done

# Avvia l'applicazione
./start_axescraper.sh "$@"