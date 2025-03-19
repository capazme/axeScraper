# src/pipeline.py
"""
Main pipeline orchestration with explicit stage dependencies and data flow.
"""

import asyncio
import signal
import psutil
import os
import time
import subprocess
from typing import Dict, Any, List, Optional
from pathlib import Path
from .axcel import AxeAnalysis
from .analysis import AccessibilityAnalyzer
from .utils.send_mail import send_email_report
# Import standardized logging and output management
from .utils.logging_config import get_logger
from .utils.output_manager import OutputManager
from .utils.config import (
    BASE_URLS,
    URL_CONFIGS,
    PIPELINE_CONFIG,
    EMAIL_CONFIG,
    LOGGING_CONFIG,
    OUTPUT_CONFIG,
)

# Set up logger with pipeline-specific configuration
logger = get_logger("pipeline", LOGGING_CONFIG.get("components", {}).get("pipeline", {}))

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
    resource_config = PIPELINE_CONFIG.get("resource_monitoring", {})
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
    
    # Get crawler parameters directly from crawler_config
    domains = crawler_config.get("domains", base_url)
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
    
async def run_crawler(base_url: str, config: Dict[str, Any], output_manager: OutputManager) -> bool:
    """Run crawler component with standardized path management."""
    global crawler_processes
    
    logger.info(f"Starting crawler for {base_url}")
    
    # Get standardized paths from output manager
    output_dir = str(output_manager.get_path("crawler"))
    state_file = str(output_manager.get_path(
        "crawler", f"crawler_state_{output_manager.domain_slug}.pkl"))
    log_file = str(output_manager.get_timestamped_path(
        "logs", f"crawler_{output_manager.domain_slug}", "log"))
    
    # Ensure directories exist
    output_manager.ensure_path_exists("crawler")
    output_manager.ensure_path_exists("logs")
    
    # Build command with consistent parameters
    cmd = [
        "python", "-m", "src.multi_domain_crawler.multi_domain_crawler.spiders.multi_domain_spider",
        "-a", f"domains={config.get('domains', base_url)}",
        "-a", f"max_urls_per_domain={config.get('max_urls', 500)}",
        "-a", f"hybrid_mode={'True' if config.get('hybrid_mode', True) else 'False'}",
        "-a", f"request_delay={config.get('request_delay', 0.25)}",
        "-s", f"OUTPUT_DIR={output_dir}",
        "-s", f"CONCURRENT_REQUESTS={config.get('max_workers', 16)}",
        "-s", f"DOWNLOAD_DELAY={config.get('request_delay', 0.25)}",
        "--logfile", f"{log_file}"
    ]
    
    # Log command for debugging
    logger.info(f"Crawler command: {' '.join(cmd)}")
    
    try:
        # Start the crawler as a subprocess
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            cwd=str(Path(__file__).parent.parent)  # Project root
        )
        
        crawler_processes[base_url] = process
        logger.info(f"Crawler started with PID {process.pid}")
        
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
        if stdout.strip():
            logger.info(f"Final crawler output: {stdout.strip()}")
        if stderr.strip():
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

async def run_axe_analysis(base_url: str, config: Dict[str, Any], output_manager: OutputManager) -> bool:
    """Run Axe analysis with standardized path management."""
    logger.info(f"Starting Axe analysis for {base_url}")
    
    # Get standardized paths
    analysis_state_file = str(output_manager.get_path(
        "crawler", f"crawler_state_{output_manager.domain_slug}.pkl"))
    excel_filename = str(output_manager.get_path(
        "axe", f"accessibility_report_{output_manager.domain_slug}.xlsx"))
    visited_file = str(output_manager.get_path(
        "axe", f"visited_urls_{output_manager.domain_slug}.txt"))
    
    # Ensure directories exist
    output_manager.ensure_path_exists("axe")
    
    # Verify dependencies
    if not os.path.exists(analysis_state_file):
        logger.error(f"Required crawler state file not found: {analysis_state_file}")
        return False
    
    try:
        # Create analyzer with standardized paths
        analyzer = AxeAnalysis(
            urls=None,
            analysis_state_file=analysis_state_file,
            domains=config.get("domains"),
            max_templates_per_domain=config.get("max_templates_per_domain"),
            fallback_urls=[base_url],
            pool_size=config.get("pool_size", 5),
            sleep_time=config.get("sleep_time", 1),
            excel_filename=excel_filename,
            visited_file=visited_file,
            headless=config.get("headless", True),
            resume=config.get("resume", True),
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

async def run_final_report(base_url: str, config: Dict[str, Any], output_manager: OutputManager) -> Optional[str]:
    """Generate final accessibility report with standardized path management."""
    logger.info(f"Generating final report for {base_url}")
    
    # Get standardized paths
    input_excel = str(output_manager.get_path(
        "axe", f"accessibility_report_{output_manager.domain_slug}.xlsx"))
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
        # Create analyzer with output manager
        analyzer = AccessibilityAnalyzer(output_manager=output_manager)
        
        # Execute analysis pipeline with clear stage progression
        logger.info(f"Loading accessibility data for {base_url}")
        axe_df = analyzer.load_data(input_excel, crawler_state)
        
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

async def process_url(base_url: str, url_config: Dict[str, Any], output_manager: OutputManager) -> Optional[str]:
    """Process a URL through the complete pipeline with explicit stage progression."""
    logger.info(f"Processing {base_url} through the pipeline")
    
    # Get stage configuration
    start_stage = PIPELINE_CONFIG.get("start_stage", "crawler")
    repeat_axe = PIPELINE_CONFIG.get("repeat_axe", 1)
    
    # Run crawler if starting from that stage
    if start_stage == "crawler":
        logger.info(f"Starting with crawler stage for {base_url}")
        crawler_success = await run_crawler(base_url, url_config["crawler_config"], output_manager)
        
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
            axe_success = await run_axe_analysis(base_url, url_config["axe_analysis_config"], output_manager)
            
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
        report_path = await run_final_report(base_url, url_config["final_report_config"], output_manager)
        
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
    
    logger.info("Starting accessibility testing pipeline")
    logger.info(f"Configuration: Start stage: {PIPELINE_CONFIG.get('start_stage', 'crawler')}, "
               f"Repeat Axe: {PIPELINE_CONFIG.get('repeat_axe', 1)}")
    
    # System information for troubleshooting
    cpu_count = os.cpu_count()
    memory = psutil.virtual_memory()
    logger.info(f"System resources: {cpu_count} CPUs, "
               f"{memory.total / (1024**3):.1f}GB total RAM, "
               f"{memory.available / (1024**3):.1f}GB available RAM")
    
    # Initialize output managers for all URLs
    output_managers = {}
    for base_url, url_config in URL_CONFIGS.items():
        output_managers[base_url] = OutputManager(
            base_dir=os.path.expanduser("~/axeScraper/output"),
            domain=base_url,
            create_dirs=True
        )
    
    # Start resource monitoring
    resource_monitor = asyncio.create_task(monitor_resources())
    
    # Process each URL through the pipeline
    report_paths = []
    for base_url, url_config in URL_CONFIGS.items():
        if shutdown_flag:
            logger.warning("Shutdown requested, stopping pipeline")
            break
            
        logger.info(f"Processing URL: {base_url}")
        output_manager = output_managers[base_url]
        
        # Run the URL through all appropriate pipeline stages
        report_path = await process_url(base_url, url_config, output_manager)
        if report_path:
            report_paths.append(report_path)
    
    # Send email with reports if configured
    if not shutdown_flag and report_paths and EMAIL_CONFIG.get("recipient_email"):
        try:
            logger.info(f"Sending email with {len(report_paths)} reports")
            send_email_report(report_paths)
            logger.info("Email sent successfully")
        except Exception as e:
            logger.error(f"Error sending email: {e}")
    
    # Calculate total execution time
    end_time = time.time()
    elapsed_time = end_time - start_time
    hours, remainder = divmod(elapsed_time, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    # Log pipeline completion
    logger.info(f"Pipeline completed in {int(hours)}:{int(minutes):02}:{int(seconds):02}")
    logger.info(f"Processed {len(URL_CONFIGS)} URLs, generated {len(report_paths)} reports")
    
    # Stop resource monitoring
    resource_monitor.cancel()
    try:
        await resource_monitor
    except asyncio.CancelledError:
        pass

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user")
    except Exception as e:
        logger.exception(f"Unhandled error in pipeline: {e}")