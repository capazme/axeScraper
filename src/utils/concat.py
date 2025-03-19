import pandas as pd
import os

def concat_excel_sheets(file_path, output_path=None, sheet_names=None):
    """
    Concatena tutti i fogli di un file Excel in un unico DataFrame.
    Se sheet_names è None, legge tutti i fogli; altrimenti, lista esplicitamente i fogli da leggere.
    
    Args:
        file_path (str): percorso del file Excel.
        output_path (str, optional): percorso dove salvare il file Excel. Default è None.
        sheet_names (list, optional): lista di nomi di fogli da leggere. Default è None.
        
    Returns:
        str: percorso del file Excel salvato (se output_path è specificato) o il DataFrame concatenato.
    """
    # Controlla se il file esiste
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Il file {file_path} non esiste")
    
    # Legge tutti i fogli se sheet_names è None
    if sheet_names is None:
        sheets = pd.read_excel(file_path, sheet_name=None)
    else:
        sheets = {sheet: pd.read_excel(file_path, sheet_name=sheet) for sheet in sheet_names}

    # Concatena i DataFrame provenienti dai vari fogli
    df_concat = pd.concat(sheets.values(), ignore_index=True)
    
    # Se output_path è specificato, salva il DataFrame in un file Excel
    if output_path:
        # Assicurati che la directory esista
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
            
        # Salva il file Excel usando openpyxl come engine
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            df_concat.to_excel(writer, index=False)
        return output_path
    
    # Altrimenti, restituisce il DataFrame
    return df_concat

if __name__ == "__main__":
    # Esempio di utilizzo
    file_path = '/home/ec2-user/axeScraper/output/iper_it/axe_output/accessibility_report_iper.xlsx'
    output_path = '/home/ec2-user/axeScraper/output/iper_it/axe_output/accessibility_report_iper_concatenated.xlsx'
    
    # Test con salvataggio
    result = concat_excel_sheets(file_path, output_path)
    print(f"File salvato in: {result}")
    
    # Test senza salvataggio
    df_finale = concat_excel_sheets(file_path)
    print(df_finale.head())