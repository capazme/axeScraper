from ..src.analysis.report_analysis import AccessibilityAnalyzer
from ..src.utils.output_manager import OutputManager
import pandas as pd
import os

# Configura output manager
output_manager = OutputManager(
    base_dir='./output',
    domain='example.com',
    create_dirs=True
)

# Crea dati di test se non hai un report Axe
test_data_path = output_manager.get_path("axe", "test_data.xlsx")
if not os.path.exists(test_data_path):
    # Crea dati di test
    data = {
        'page_url': ['https://example.com', 'https://example.com/page1', 'https://example.com/page2'],
        'violation_id': ['color-contrast', 'aria-roles', 'image-alt'],
        'impact': ['serious', 'critical', 'moderate']
    }
    df = pd.DataFrame(data)
    df.to_excel(test_data_path, index=False)
    print(f"Creato file di test: {test_data_path}")

# Crea l'analizzatore
analyzer = AccessibilityAnalyzer(output_manager=output_manager)

# Esegui l'analisi
df = analyzer.load_data(str(test_data_path))
metrics = analyzer.calculate_metrics(df)
aggregations = analyzer.create_aggregations(df)
chart_files = analyzer.create_charts(metrics, aggregations, df)

# Genera il report
report_path = analyzer.generate_report(
    axe_df=df,
    metrics=metrics,
    aggregations=aggregations,
    chart_files=chart_files,
    output_excel=str(output_manager.get_path("analysis", "test_report.xlsx"))
)

print(f"Report generato: {report_path}")
print("Metriche calcolate:", metrics)