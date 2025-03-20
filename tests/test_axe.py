import asyncio
from ..src.axcel.axcel import AxeAnalysis
from ..src.utils.output_manager import OutputManager

async def test_axe():
    # Configura output manager
    output_manager = OutputManager(
        base_dir='./output',
        domain='example.com',
        create_dirs=True
    )
    
    # Crea un file di test per simulare l'output del crawler se necessario
    state_file = output_manager.get_path("crawler", f"crawler_state_{output_manager.domain_slug}.pkl")
    
    # Se non hai un file di stato, puoi usare solo URL fallback
    analyzer = AxeAnalysis(
        urls=None,
        analysis_state_file=None,
        fallback_urls=['https://example.com'],
        pool_size=1,
        excel_filename=str(output_manager.get_path("axe", "accessibility_report_example_com.xlsx")),
        output_folder=str(output_manager.get_path("axe")),
        output_manager=output_manager
    )
    
    # Esegui l'analisi
    analyzer.start()
    
    print("Analisi Axe completata. Verifica il file di output:", 
          output_manager.get_path("axe", "accessibility_report_example_com.xlsx"))

# Esegui il test
asyncio.run(test_axe())