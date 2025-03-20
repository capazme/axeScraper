import asyncio
from src.pipeline import process_url
from src.utils.config_manager import ConfigurationManager
from src.utils.output_manager import OutputManager

async def main():
    # Carica configurazione
    config = ConfigurationManager()
    
    # Usa un singolo dominio per il test
    base_url = 'https://www.iccreabanca.it/it-IT/Pagine/default.aspx'
    domain_config = config.load_domain_config(base_url)
    
    # Crea output manager
    output_dir = config.get_path('OUTPUT_DIR', './output', create=True)
    output_manager = OutputManager(
        base_dir=output_dir,
        domain=base_url,
        create_dirs=True
    )
    
    print(f"Avvio pipeline per {base_url}")
    report_path = await process_url(base_url, domain_config, output_manager)
    
    if report_path:
        print(f"Pipeline completata con successo. Report: {report_path}")
    else:
        print(f"Pipeline completata con errori.")

if __name__ == "__main__":
    asyncio.run(main())