#!/usr/bin/env python3
"""
Main pipeline orchestration with explicit stage dependencies and data flow.
Uses enhanced configuration management system.
"""

import asyncio
import signal
import psutil
import os
import time
import subprocess
from typing import Dict, Any, List, Optional
from pathlib import Path

# Import core components
from .axcel.axcel import AxeAnalysis
from .analysis.report_analysis import AccessibilityAnalyzer
from .utils.send_mail import send_email_report

# Import configuration management
from .utils.config_manager import ConfigurationManager
from .utils.logging_config import get_logger
from .utils.output_manager import OutputManager

# Initialize configuration manager
config_manager = ConfigurationManager(project_name="axeScraper")

# Set up logger with pipeline-specific configuration
logger = get_logger("pipeline", config_manager.get_logging_config()["components"]["pipeline"])

# Global state
crawler_processes = {}
output_managers = {}
shutdown_flag = False
start_time = None

def handle_shutdown(signum, _):
    """Handle termination signals gracefully."""
    global shutdown_flag, crawler_processes
    shutdown_flag = True
    logger.warning(f"Received termination signal ({signum}). Starting controlled shutdown...")
    
    # Terminate running crawler processes
    for base_url, process in crawler_processes.items():
        if process and process.poll() is None:
            logger.info(f"Terminating crawler for {base_url}")
            try:
                process.terminate()
                # Wait up to 30 seconds for graceful termination
                for _ in range(30):
                    if process.poll() is not None:
                        break
                    time.sleep(1)
                # Force kill if still running
                if process.poll() is None:
                    process.kill()
            except Exception as e:
                logger.error(f"Error terminating crawler process: {e}")

# Register signal handlers
signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)

async def monitor_resources():
    """Monitor system resources and pause if thresholds are exceeded."""
    # Get resource monitoring config
    pipeline_config = config_manager.get_pipeline_config()
    resource_config = pipeline_config.get("resource_monitoring", {})
    
    threshold_cpu = resource_config.get("threshold_cpu", 90)
    threshold_memory = resource_config.get("threshold_memory", 85)
    check_interval = resource_config.get("check_interval", 3)
    cool_down_time = resource_config.get("cool_down_time", 7)
    
    if not resource_config.get("enabled", True):
        logger.info("Resource monitoring disabled by configuration")
        return
        
    try:
        while not shutdown_flag:
            try:
                cpu = psutil.cpu_percent(interval=0.5)
                mem = psutil.virtual_memory().percent
                
                # Log performance metrics periodically
                if start_time and (time.time() - start_time) % 60 < 3:
                    elapsed = time.time() - start_time
                    if elapsed > 0:
                        logger.info(f"Performance: CPU={cpu:.1f}%, Memory={mem:.1f}%, "
                                  f"Uptime={elapsed/60:.1f} minutes")
                
                # Pause if resources are constrained
                if cpu > threshold_cpu or mem > threshold_memory:
                    logger.warning(f"High resource usage: CPU={cpu:.1f}%, Memory={mem:.1f}%. "
                                 f"Pausing for {cool_down_time} seconds...")
                    
                    # Run garbage collection to free memory
                    if mem > threshold_memory:
                        logger.info("Running garbage collection...")
                        import gc
                        gc.collect()
                        
                    await asyncio.sleep(cool_down_time)
                else:
                    await asyncio.sleep(check_interval)
            except Exception as e:
                logger.error(f"Error in resource monitor: {e}")
                await asyncio.sleep(10)
    except asyncio.CancelledError:
        logger.info("Resource monitor terminated")
        raise

def run_multi_domain_crawler(base_url: str, crawler_config: Dict[str, Any], output_manager: OutputManager) -> subprocess.Popen:
    """Execute the multi-domain crawler for specified URL(s)"""
    # Get paths from output manager
    output_dir = str(output_manager.get_path("crawler"))
    log_file = str(output_manager.get_timestamped_path(
        "logs", f"crawler_{output_manager.domain_slug}", "log"))
    
    # Estrai il dominio base senza path
    clean_domain = output_manager.domain.replace("http://", "").replace("https://", "").replace("www.", "")
    clean_domain = clean_domain.split('/')[0]
    
    # Get crawler parameters from crawler_config
    domains = crawler_config.get("domains", clean_domain)  # Usa il dominio pulito
    max_urls_per_domain = crawler_config.get("max_urls", 1000)
    hybrid_mode = "True" if crawler_config.get("hybrid_mode", True) else "False"
    
    # Add more parameters from configuration
    request_delay = crawler_config.get("request_delay", 0.25)
    selenium_threshold = crawler_config.get("pending_threshold", 30)
    max_workers = crawler_config.get("max_workers", 16)
    
    # Prepare command
    cmd = [
        "python", "-m", "scrapy", "crawl", "multi_domain_spider",
        "-a", f"domains={domains}",
        "-a", f"max_urls_per_domain={max_urls_per_domain}",
        "-a", f"hybrid_mode={hybrid_mode}",
        "-a", f"request_delay={request_delay}",
        "-a", f"selenium_threshold={selenium_threshold}",
        "-s", f"OUTPUT_DIR={output_dir}",
        "-s", f"CONCURRENT_REQUESTS={max_workers}",
        "-s", f"CONCURRENT_REQUESTS_PER_DOMAIN={max(8, max_workers // 2)}",
        "-s", f"LOG_LEVEL=INFO",
        "-s", f"PIPELINE_REPORT_FORMAT=all",
        "--logfile", f"{log_file}"
    ]
    
    # Log the command (useful for debugging)
    logger.info(f"Crawler command: {' '.join(cmd)}")
    
    # Execute the command
    try:
        process = subprocess.Popen(
            cmd,
            cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "multi_domain_crawler")),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        
        logger.info(f"Crawler started for {base_url} with PID {process.pid}")
        return process
    except Exception as e:
        logger.error(f"Failed to start crawler for {base_url}: {e}")
        raise
    
async def run_crawler(base_url: str, domain_config: Dict[str, Any], output_manager: OutputManager) -> bool:
    """Run crawler component with standardized path management."""
    global crawler_processes
    
    logger.info(f"Starting crawler for {base_url}")
    
    # Get crawler configuration
    crawler_config = domain_config.get("crawler_config", {})
    
    # Get standardized paths from output manager
    output_dir = str(output_manager.get_path("crawler"))
    state_file = str(output_manager.get_path(
        "crawler", f"crawler_state_{output_manager.domain_slug}.pkl"))
    log_file = str(output_manager.get_timestamped_path(
        "logs", f"crawler_{output_manager.domain_slug}", "log"))
    
    # Ensure directories exist
    output_manager.ensure_path_exists("crawler")
    output_manager.ensure_path_exists("logs")
    
    try:
        # Start the multi-domain crawler as a subprocess
        process = run_multi_domain_crawler(base_url, crawler_config, output_manager)
        
        crawler_processes[base_url] = process
        
        # Monitor process execution
        while process.poll() is None:
            # Process stdout and stderr
            stdout_line = process.stdout.readline() if process.stdout else ""
            if stdout_line.strip():
                logger.info(f"Crawler ({base_url}): {stdout_line.strip()}")
            
            stderr_line = process.stderr.readline() if process.stderr else ""
            if stderr_line.strip():
                logger.warning(f"Crawler ({base_url}) stderr: {stderr_line.strip()}")
            
            # Check for shutdown signal
            if shutdown_flag:
                logger.warning(f"Shutdown requested, terminating crawler for {base_url}")
                process.terminate()
                return False
            
            await asyncio.sleep(0.1)
        
        # Process completed
        return_code = process.returncode
        
        # Read any remaining output
        stdout, stderr = process.communicate()
        if stdout and stdout.strip():
            logger.info(f"Final crawler output: {stdout.strip()}")
        if stderr and stderr.strip():
            logger.warning(f"Final crawler errors: {stderr.strip()}")
        
        if return_code == 0:
            logger.info(f"Crawler completed successfully for {base_url}")
            return True
        else:
            logger.error(f"Crawler failed with code {return_code} for {base_url}")
            return False
            
    except Exception as e:
        logger.exception(f"Error running crawler: {e}")
        return False
    finally:
        # Remove process from tracking
        crawler_processes.pop(base_url, None)

async def run_axe_analysis(base_url: str, domain_config: Dict[str, Any], output_manager: OutputManager) -> bool:
    """Run Axe analysis with standardized path management."""
    logger.info(f"Starting Axe analysis for {base_url}")
    
    # Get axe configuration
    axe_config = domain_config.get("axe_config", {})
    
    # Use the output manager to get the best path
    analysis_state_file = str(output_manager.get_crawler_state_path())
    
    if not os.path.exists(analysis_state_file):
        logger.warning(f"Crawler state file not found at primary path: {analysis_state_file}")
        logger.info("Searching for alternate state files...")
        
        # Prova a cercare in posizioni alternative (gestite internamente da get_crawler_state_path)
        analysis_state_file = str(output_manager.get_crawler_state_path())
    
    # Altre definizioni di percorso
    excel_filename = str(output_manager.get_path(
        "axe", f"accessibility_report_{output_manager.domain_slug}.xlsx"))
    visited_file = str(output_manager.get_path(
        "axe", f"visited_urls_{output_manager.domain_slug}.txt"))
    
    # Ensure directories exist
    output_manager.ensure_path_exists("axe")
    
    # Verify dependencies
    if not os.path.exists(analysis_state_file):
        logger.error(f"Required crawler state file not found: {analysis_state_file}")
        # Ancora una chance se il crawler è stato avviato senza registrare lo stato
        fallback_urls = [base_url]
        logger.warning(f"Using fallback URL: {base_url}")
    else:
        fallback_urls = [base_url]
        logger.info(f"Using state file: {analysis_state_file}")
    
    try:
        # Create analyzer with standardized paths
        analyzer = AxeAnalysis(
            urls=None,
            analysis_state_file=analysis_state_file,
            domains=axe_config.get("domains"),
            max_templates_per_domain=axe_config.get("max_templates_per_domain"),
            fallback_urls=fallback_urls,
            pool_size=axe_config.get("pool_size", 5),
            sleep_time=axe_config.get("sleep_time", 1),
            excel_filename=excel_filename,
            visited_file=visited_file,
            headless=axe_config.get("headless", True),
            resume=axe_config.get("resume", True),
            output_folder=str(output_manager.get_path("axe")),
            output_manager=output_manager
        )
        
        # Run analysis in a thread to avoid blocking asyncio
        await asyncio.to_thread(analyzer.start)
        
        # Verify output was created
        if os.path.exists(excel_filename):
            logger.info(f"Axe analysis completed successfully for {base_url}")
            return True
        else:
            logger.error(f"Axe analysis failed to produce output for {base_url}")
            return False
            
    except Exception as e:
        logger.exception(f"Error in Axe analysis: {e}")
        return False
    
async def run_final_report(base_url: str, domain_config: Dict[str, Any], output_manager: OutputManager) -> Optional[str]:
    """Generate final accessibility report with standardized path management."""
    logger.info(f"Generating final report for {base_url}")
    
    # Get report configuration
    report_config = domain_config.get("report_config", {})
    
    # Get standardized paths
    input_excel = str(output_manager.get_path(
        "axe", f"accessibility_report_{output_manager.domain_slug}.xlsx"))
    # Path per il file Excel concatenato
    concat_excel = str(output_manager.get_path(
        "analysis", f"accessibility_report_{output_manager.domain_slug}_concat.xlsx"))
    output_excel = str(output_manager.get_path(
        "analysis", f"final_analysis_{output_manager.domain_slug}.xlsx"))
    crawler_state = str(output_manager.get_path(
        "crawler", f"crawler_state_{output_manager.domain_slug}.pkl"))
    charts_dir = str(output_manager.get_path("charts"))
    
    # Ensure directories exist
    output_manager.ensure_path_exists("analysis")
    output_manager.ensure_path_exists("charts")
    
    # Verify dependencies
    if not os.path.exists(input_excel):
        logger.error(f"Required Axe report not found: {input_excel}")
        return None
    
    try:
        # NUOVO PASSAGGIO: Concatenare i fogli Excel dall'output di Axe
        from src.utils.concat import concat_excel_sheets
        logger.info(f"Concatenating Excel sheets from {input_excel}")
        concat_excel_path = concat_excel_sheets(file_path=input_excel, output_path=concat_excel)
        logger.info(f"Excel sheets concatenated and saved to {concat_excel_path}")
        
        # Create analyzer with output manager
        analyzer = AccessibilityAnalyzer(output_manager=output_manager)
        
        # Execute analysis pipeline with clear stage progression
        logger.info(f"Loading accessibility data for {base_url}")
        # Usa il file Excel concatenato invece dell'originale
        axe_df = analyzer.load_data(concat_excel_path, crawler_state)
        
        logger.info(f"Calculating metrics for {base_url}")
        metrics = analyzer.calculate_metrics(axe_df)
        
        logger.info(f"Creating data aggregations for {base_url}")
        aggregations = analyzer.create_aggregations(axe_df)
        
        logger.info(f"Generating visualization charts for {base_url}")
        chart_files = analyzer.create_charts(metrics, aggregations, axe_df)
        
        # Load template data if available
        template_df = None
        if os.path.exists(crawler_state):
            try:
                logger.info(f"Loading template structure data for {base_url}")
                templates_df, state = analyzer.load_template_data(crawler_state)
                template_df = analyzer.analyze_templates(templates_df, axe_df)
            except Exception as e:
                logger.warning(f"Template analysis failed (non-critical): {e}")
        
        # Generate final Excel report
        logger.info(f"Creating final Excel report for {base_url}")
        report_path = analyzer.generate_report(
            axe_df=axe_df,
            metrics=metrics,
            aggregations=aggregations,
            chart_files=chart_files,
            template_df=template_df,
            output_excel=output_excel
        )
        
        logger.info(f"Final report generated: {report_path}")
        return report_path
        
    except Exception as e:
        logger.exception(f"Error generating final report: {e}")
        return None

async def process_url(base_url: str, domain_config: Dict[str, Any], output_manager: OutputManager) -> Optional[str]:
    """Process a URL through the complete pipeline with explicit stage progression."""
    logger.info(f"Processing {base_url} through the pipeline")
    
    # Controlla se ci sono già dati in strutture diverse
    domain_slug = output_manager.domain_slug
    output_root = Path(output_manager.base_dir)
    # Get pipeline configuration
    pipeline_config = config_manager.get_pipeline_config()
    start_stage = pipeline_config.get("start_stage", "crawler")
    repeat_axe = pipeline_config.get("repeat_axe", 1)
    
    # Verifica se ci sono directory esistenti con dati
    alternate_path = None
    for item in output_root.iterdir():
        if item.is_dir() and domain_slug in item.name and item != output_manager.get_path("root"):
            crawler_output = item / "crawler_output"
            if crawler_output.exists():
                for domain_dir in crawler_output.iterdir():
                    if domain_dir.is_dir() and domain_slug in domain_dir.name:
                        state_file = domain_dir / f"crawler_state_{domain_dir.name}.pkl"
                        if state_file.exists():
                            alternate_path = state_file
                            logger.info(f"Trovato state file alternativo: {alternate_path}")
                            break
            if alternate_path:
                break
    
    # Run crawler if starting from that stage
    if start_stage == "crawler":
        logger.info(f"Starting with crawler stage for {base_url}")
        crawler_success = await run_crawler(base_url, domain_config, output_manager)
        
        if not crawler_success:
            logger.warning(f"Crawler stage failed for {base_url}, but continuing with pipeline")
            
        if shutdown_flag:
            logger.warning(f"Shutdown requested after crawler stage for {base_url}")
            return None
    else:
        logger.info(f"Skipping crawler stage for {base_url} (starting from {start_stage})")
    
    # Run Axe analysis if starting from crawler or axe stage
    if start_stage in ["crawler", "axe"]:
        logger.info(f"Running Axe analysis for {base_url} ({repeat_axe} iterations)")
        
        for i in range(repeat_axe):
            logger.info(f"Axe analysis iteration {i+1}/{repeat_axe} for {base_url}")
            axe_success = await run_axe_analysis(base_url, domain_config, output_manager)
            
            if not axe_success:
                logger.warning(f"Axe analysis iteration {i+1} failed for {base_url}")
                
            if shutdown_flag:
                logger.warning(f"Shutdown requested during Axe analysis for {base_url}")
                return None
                
            # Pause between iterations
            if i < repeat_axe - 1:
                await asyncio.sleep(1)
    else:
        logger.info(f"Skipping Axe analysis stage for {base_url} (starting from {start_stage})")
    
    # Generate final report
    if not shutdown_flag:
        logger.info(f"Generating final report for {base_url}")
        report_path = await run_final_report(base_url, domain_config, output_manager)
        
        if report_path:
            logger.info(f"Final report generated for {base_url}: {report_path}")
            return report_path
        else:
            logger.error(f"Failed to generate final report for {base_url}")
            return None
    else:
        logger.warning(f"Shutdown requested before final report stage for {base_url}")
        return None

async def main():
    """Main pipeline entry point with clear execution flow."""
    global start_time, output_managers
    start_time = time.time()
    
    # Get all domains to process
    base_urls = config_manager.get_all_domains()
    
    logger.info("Starting accessibility testing pipeline")
    pipeline_config = config_manager.get_pipeline_config()
    logger.info(f"Configuration: Start stage: {pipeline_config.get('start_stage', 'crawler')}, "
               f"Repeat Axe: {pipeline_config.get('repeat_axe', 1)}")
    
    # System information for troubleshooting
    cpu_count = os.cpu_count()
    memory = psutil.virtual_memory()
    logger.info(f"System resources: {cpu_count} CPUs, "
               f"{memory.total / (1024**3):.1f}GB total RAM, "
               f"{memory.available / (1024**3):.1f}GB available RAM")
    
    # Initialize output managers for all URLs
    output_managers = {}
    for base_url in base_urls:
        # Get domain configuration
        domain_config = config_manager.load_domain_config(base_url)
        
        # Estrai dominio base per consistenza
        clean_domain = base_url.replace("http://", "").replace("https://", "").replace("www.", "")
        clean_domain = clean_domain.split('/')[0]
        
        # Create output manager for this domain
        output_root = config_manager.get_path("OUTPUT_DIR", "~/axeScraper/output", create=True)
        output_manager = OutputManager(
            base_dir=output_root,
            domain=clean_domain,  # Usa solo il dominio base!
            create_dirs=True
        )
        
        # Cerca eventuali directory già esistenti
        domain_slug = output_manager.domain_slug
        existing_dirs = []
        
        # Cerca directory che potrebbero contenere dati per questo dominio
        for item in output_root.iterdir():
            if item.is_dir():
                # Verifica se il nome contiene il dominio di base
                if domain_slug in item.name:
                    # Verifica se contiene directory di output del crawler o axe
                    if (item / "crawler_output").exists() or (item / "axe_output").exists():
                        existing_dirs.append(item)
        
        # Se ci sono directory esistenti, usa la prima
        if existing_dirs:
            logger.info(f"Trovate directory esistenti per {clean_domain}: {[d.name for d in existing_dirs]}")
            # Usa la directory con più file o, in caso di parità, la prima
            existing_dir = max(existing_dirs, key=lambda d: sum(1 for _ in d.glob("**/*")))
            logger.info(f"Usando directory esistente: {existing_dir.name}")
            
            # Ricrea l'output manager con la directory esistente
            output_manager = OutputManager(
                base_dir=output_root,
                domain=clean_domain,
                create_dirs=True,
                config={"root": existing_dir}
            )
        
        output_managers[base_url] = output_manager

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user")
    except Exception as e:
        logger.exception(f"Unhandled error in pipeline: {e}")