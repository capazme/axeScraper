import re
from pathlib import Path
import pandas as pd
import openpyxl


def generate_excel_report(self) -> None:
        """
        Genera un file Excel in cui ogni sheet corrisponde a un URL analizzato,
        contenente il report delle issues rilevate in quella pagina.
        """
        self.logger.debug("Inizio generazione del report Excel.")
        if not self.results:
            self.logger.warning("Nessun risultato da esportare. Esco dalla generazione del report.")
            return

        excel_path = Path(self.excel_filename)
        if not excel_path.parent.exists():
            self.logger.debug(f"Cartella '{excel_path.parent}' non trovata, la creo adesso.")
            try:
                excel_path.parent.mkdir(parents=True, exist_ok=True)
                self.logger.info(f"Cartella creata: '{excel_path.parent}'.")
            except Exception as e:
                self.logger.exception(f"Errore nella creazione della cartella '{excel_path.parent}': {e}")
                return

        try:
            self.logger.debug(f"Apertura di ExcelWriter per il file: '{self.excel_filename}'.")
            with pd.ExcelWriter(self.excel_filename, engine="openpyxl") as writer:
                for url, issues in self.results.items():
                    last_segment = url.rstrip("/").split("/")[-1]
                    sheet_name = re.sub(r'[\\/*?:\[\]]', '_', last_segment)[:31] or "Sheet"
                    self.logger.debug(f"Creazione dello sheet per URL: '{url}' con nome: '{sheet_name}'.")
                    if issues:
                        df = pd.DataFrame(issues)
                        self.logger.debug(f"Trovate {len(issues)} issues per URL: '{url}'.")
                    else:
                        self.logger.debug(f"Nessuna issue trovata per URL: '{url}'. Creazione DataFrame vuoto.")
                        df = pd.DataFrame(columns=[
                            "page_url", "violation_id", "impact", "description",
                            "help", "XPath", "html attuale", "failure_summary/action"
                        ])
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
                    self.logger.debug(f"Sheet '{sheet_name}' scritto con successo.")
            self.logger.info(f"Report Excel generato con successo: '{self.excel_filename}'.")
        except Exception as e:
            self.logger.exception(f"Errore nella generazione del report Excel: {e}")

def rename_headers(input_file: str, output_file: str) -> None:
    """
    Carica un file Excel, rinomina alcuni header secondo una mappatura predefinita e salva il file modificato.

    Args:
        input_file: Percorso del file Excel di origine.
        output_file: Percorso dove salvare il file modificato.
    """
    # Mappatura degli header da modificare
    header_mapping = {
        "target": "XPath",
        "html": "html attuale",
        "failure_summary": "failure_summary/action"
    }

    wb = openpyxl.load_workbook(input_file)

    # Itera su ogni foglio del workbook, sostituendo gli header nella prima riga
    for ws in wb.worksheets:
        for cell in ws[1]:
            if cell.value in header_mapping:
                print(f"Nel foglio '{ws.title}', cambio '{cell.value}' in '{header_mapping[cell.value]}'")
                cell.value = header_mapping[cell.value]
    
    wb.save(output_file)
