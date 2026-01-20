#!/usr/bin/env python3
"""
LISVAP BD 
----------------------
Automates the full LISVAP pipeline:
1. Checks for local forcing data (meteorology).
2. If missing, runs 'process_input_HRES_files_LISVAP.py' to download/convert it.
3. Updates the LISVAP XML settings for the specific date.
4. Runs LISVAP.
5. Organizes the output.

Usage:
    python run_lisvap_workflow.py <YYYYMMDD>
"""

import sys
import shutil
import subprocess
import os
from pathlib import Path
from datetime import datetime, timedelta
from xml.dom import minidom

# --- Configuration ---

# Name of the merged script you created in the previous step
FETCHER_SCRIPT = "process_input_HRES_files_LISVAP.py"

# Directory names (Must match what is used in the fetcher script)
DATA_DIR_NAME = "input"
OUTPUT_DIR_NAME = "output"

# CRITICAL: Check for the FINAL LISFLOOD file names, not the raw ECMWF names.
# LISVAP will fail if these specific files are missing.
REQUIRED_NC_FILES = ["t2m.nc", "d2m.nc", "10u.nc", "10v.nc", "ssrd.nc", "str.nc"]

# --- Helper Functions ---

def run_task(cmd, description, working_dir):
    """Executes a subprocess with a clean status message."""
    print(f"\n[Task] {description}...")
    try:
        # Check if the executable exists (specifically for python scripts)
        if cmd[0].endswith('.py') and not Path(cmd[0]).exists() and not (working_dir / cmd[0]).exists():
             raise FileNotFoundError(f"Script not found: {cmd[0]}")

        subprocess.run(cmd, cwd=working_dir, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"   ❌ Error during {description}: {e}")
        print("   -> Simulation stopped.")
        sys.exit(1)

def update_xml_settings(xml_path, date_str, start_str, end_str, input_dir):
    """
    Updates the LISVAP XML template with:
    1. The specific simulation start/end dates.
    2. The correct input/output paths for this date.
    """
    doc = minidom.parse(str(xml_path))
    tags = doc.getElementsByTagName("textvar")
    
    for tag in tags:
        name = tag.getAttribute("name")
        current_val = tag.getAttribute("value")

        if name in ["CalendarDayStart", "StepStart"]:
            tag.setAttribute("value", start_str)
        
        elif name == "StepEnd":
            tag.setAttribute("value", end_str)
        
        elif name == "DtSec":
            tag.setAttribute("value", "21600") # 6-hourly
            
        elif name == "PathMeteoIn":
            # Update to point to absolute path of ./input/YYYYMMDD
            tag.setAttribute("value", str(input_dir.resolve()))

        elif name == "PathOut":
            # Update to point to ./output/YYYYMMDD (temporary local output)
            # This navigates from input/date -> input -> script_dir -> output -> date
            out_path = input_dir.parent.parent / OUTPUT_DIR_NAME / date_str
            out_path.mkdir(parents=True, exist_ok=True)
            tag.setAttribute("value", str(out_path.resolve()))

    return doc


# --- Main Execution ---

def main():
    if len(sys.argv) < 2:
        print("Usage: python run_lisvap_workflow.py <YYYYMMDD>")
        sys.exit(1)

    # 1. Setup Dates and Paths
    date_str = sys.argv[1]
    
    try:
        start_dt = datetime.strptime(date_str, "%Y%m%d")
    except ValueError:
        print("Error: Date format must be YYYYMMDD")
        sys.exit(1)

    end_dt = start_dt + timedelta(days=15)
    
    # LISVAP Date Format: DD/MM/YYYY HH:MM
    start_fmt = start_dt.strftime("%d/%m/%Y 00:00")
    end_fmt = end_dt.strftime("%d/%m/%Y 00:00")

    # The directory where THIS script resides
    script_dir = Path(__file__).resolve().parent
    
    # Define paths relative to this script
    daily_input_dir = script_dir / DATA_DIR_NAME / date_str
    daily_output_dir = script_dir / OUTPUT_DIR_NAME / date_str
    
    # 2. Check for Forcing Data
    print(f"--- Preparing LISVAP for {date_str} ---")

    daily_input_dir.mkdir(parents=True, exist_ok=True)
    existing_files = [f.name for f in daily_input_dir.glob("*.nc")]
    missing_files = [req for req in REQUIRED_NC_FILES if req not in existing_files]

    py_exe = sys.executable
   # Runs the downloader/converter script
    run_task([py_exe, FETCHER_SCRIPT, date_str], "Fetching/Converting Data", script_dir)


    # 3. Prepare XML Settings
    xml_template = script_dir / "tests_BD.xml"
    if not xml_template.exists():
        print(f"Error: XML Template not found at {xml_template}")
        sys.exit(1)

    xml_generated = script_dir / f"settings_{date_str}.xml"
    
    print(f"   -> Generating configuration: {xml_generated.name}")
    doc = update_xml_settings(xml_template, date_str, start_fmt, end_fmt, daily_input_dir)
    
    with open(xml_generated, "w", encoding="utf-8") as f:
        f.write(doc.toxml())


    # 4. Run LISVAP
    run_task(["lisvap", str(xml_generated)], "Running LISVAP Simulation", script_dir)

    print(f"   -> Results are saved to {daily_output_dir}")

    # Cleanup: If the output directory exists but is empty, remove it (warn user)
    if daily_output_dir.exists() and not any(daily_output_dir.iterdir()):
        print("   [WARNING] Output directory is empty. LISVAP might have failed.")
        daily_output_dir.rmdir()

    # Cleanup the generated XML settings file
    if xml_generated.exists():
        xml_generated.unlink()

    print(f"\n✅ Workflow Complete for {date_str}")

if __name__ == "__main__":
    main()