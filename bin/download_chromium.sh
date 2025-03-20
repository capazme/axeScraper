#!/bin/bash
# Script per installare ChromeDriver compatibile con Chrome/Chromium

echo "Installazione ChromeDriver..."

# Crea directory per i binary
mkdir -p /home/ec2-user/bin
PATH="$PATH:/home/ec2-user/bin"

# Determina la versione corretta di ChromeDriver basata su Chrome/Chromium
if command -v google-chrome &>/dev/null; then
    CHROME_VERSION=$(google-chrome --version | awk '{print $3}' | cut -d. -f1)
    echo "Rilevata versione Google Chrome: $CHROME_VERSION"
elif command -v chromium-browser &>/dev/null; then
    CHROME_VERSION=$(chromium-browser --version | awk '{print $2}' | cut -d. -f1)
    echo "Rilevata versione Chromium: $CHROME_VERSION"
else
    # Se Chrome non è installato, usa una versione predefinita
    CHROME_VERSION=110
    echo "Chrome/Chromium non trovato. Utilizzo versione predefinita: $CHROME_VERSION"
fi

# Scegli URL in base alla versione rilevata
case $CHROME_VERSION in
    113|114|115|116|117)
        CHROMEDRIVER_URL="https://chromedriver.storage.googleapis.com/114.0.5735.90/chromedriver_linux64.zip"
        ;;
    109|110|111|112)
        CHROMEDRIVER_URL="https://chromedriver.storage.googleapis.com/110.0.5481.77/chromedriver_linux64.zip"
        ;;
    *)
        CHROMEDRIVER_URL="https://chromedriver.storage.googleapis.com/114.0.5735.90/chromedriver_linux64.zip"
        ;;
esac

echo "Download ChromeDriver da $CHROMEDRIVER_URL"

# Download e installazione
cd /tmp
wget -q $CHROMEDRIVER_URL -O chromedriver.zip
unzip -o chromedriver.zip
chmod +x chromedriver
mv chromedriver /home/ec2-user/bin/
rm chromedriver.zip

# Verifica installazione
if [ -f /home/ec2-user/bin/chromedriver ]; then
    echo "ChromeDriver installato in /home/ec2-user/bin/chromedriver"
    CHROMEDRIVER_VERSION=$(/home/ec2-user/bin/chromedriver --version | head -n1)
    echo "Versione ChromeDriver: $CHROMEDRIVER_VERSION"
    
    # Aggiungi il path nel .bashrc se non è già presente
    if ! grep -q "PATH=\$PATH:/home/ec2-user/bin" ~/.bashrc; then
        echo 'export PATH=$PATH:/home/ec2-user/bin' >> ~/.bashrc
        echo "PATH aggiornato in .bashrc"
    fi
    
    # Aggiungi il path per questa sessione
    export PATH=$PATH:/home/ec2-user/bin
    echo "PATH aggiornato per questa sessione"
else
    echo "Errore nell'installazione di ChromeDriver"
    exit 1
fi

# Suggerimenti finali
echo ""
echo "Installazione completata! Nota:"
echo "- Esegui 'source ~/.bashrc' per aggiornare PATH in questa sessione"
echo "- Assicurati che Chrome o Chromium sia installato e aggiornato"
echo ""
echo "Per verificare l'installazione:"
echo "chromedriver --version"