#!/usr/bin/env python3
"""
ECMWF HRES to LISFLOOD Converter
-------------------------------------------------
Usage:
    process_input_HRES_files_LISVAP.py <YYYYMMDD>

Requirements:
    - Python packages: xarray, numpy, pandas, requests, netCDF4, scipy
    - System tools: cdo, nco (must be in PATH)
"""

import os
import sys
import json
import shutil
import subprocess
import threading
import traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import numpy as np
import pandas as pd
import xarray as xr

# --- NEW IMPORTS FOR RETRY LOGIC ---
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Region of Interest (West, East, South, North)
BBOX = (72, 98, 20, 32)

# ECMWF Settings
BASE_URL = "https://storage.googleapis.com/ecmwf-open-data"
FORECAST_TIME = "00z"
# Steps: 0 to 360 (Day 1-15) 6-hourly
STEPS = range(0, 361, 6)

# Directories
BASE_DIR = Path(__file__).resolve().parent / "input"
AREA_MAP_PATH = BASE_DIR / "../../basemaps/area.nc"

# Unified Variable Config
VAR_CONFIG = {
    "10v": {
        "param_id": "10v", 
        "out_var": "wv",
        "attrs": {"long_name": "Windspeed V component at 10m", "units": "m s**-1"}
    },
    "10u": {
        "param_id": "10u", 
        "out_var": "wu",
        "attrs": {"long_name": "Windspeed U component at 10m", "units": "m s**-1"}
    },
    "t2m": {
        "param_id": "2t",  
        "out_var": "ta",
        "attrs": {"long_name": "Average daily temperature", "units": "K"}
    },
    "d2m": {
        "param_id": "2d",  
        "out_var": "td",
        "attrs": {"long_name": "Dewpoint temperature", "units": "K"}
    },
    "ssrd": {
        "param_id": "ssrd", 
        "out_var": "rg",
        "is_accumulated": True,
        "attrs": {"long_name": "Downward surface solar radiation", "units": "J/m2/d"}
    },
    "str": {
        "param_id": "str",  
        "out_var": "rn",
        "is_accumulated": True,
        "attrs": {"long_name": "Net thermal radiation", "units": "J/m2/d"}
    }
}

MAX_WORKERS = os.cpu_count() or 4
PRINT_LOCK = threading.Lock()


# --- Utilities ---

def check_system_deps():
    """Checks if CDO and NCO are installed."""
    missing = []
    for tool in ["cdo", "ncatted"]:
        if shutil.which(tool) is None:
            missing.append(tool)
    if missing:
        print(f"Error: Missing system tools: {', '.join(missing)}")
        print("Please install CDO and NCO (e.g., 'sudo apt install cdo nco')")
        sys.exit(1)

def run_shell(command):
    """Executes a shell command safely."""
    try:
        subprocess.run(command, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(f"\nCommand failed: {' '.join([str(x) for x in command])}")
        print(e.stderr.decode())
        raise

def show_progress(current, total, message):
    """Thread-safe progress bar."""
    width = 30
    fraction = current / max(total, 1)
    filled = int(width * fraction)
    bar = "█" * filled + "-" * (width - filled)
    with PRINT_LOCK:
        sys.stdout.write(f"\r[{bar}] {int(100 * fraction)}% | {message: <25}")
        sys.stdout.flush()

# --- Part 1: Downloader

class ECMWFDownloader:
    def __init__(self, date_str, output_dir):
        self.date = date_str
        self.root_dir = output_dir
        self.work_dir = self.root_dir / "temp_grib"
        self.idx_dir = self.root_dir / "temp_indices"
        
        # --- Configure Session with Retries ---
        self.session = requests.Session()
        
        # Retry 5 times with backoff (1s, 2s, 4s...)
        retry_strategy = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        # ---------------------------------------

        # Prepare folders
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(exist_ok=True)
        self.idx_dir.mkdir(exist_ok=True)

    def _get_byte_offsets(self, index_path, target_params):
        """Parse .index file to find byte ranges for variables."""
        offsets = {}
        if not index_path.exists():
            return offsets
        with open(index_path, "r") as f:
            for line in f:
                try:
                    item = json.loads(line)
                    param = item.get("param")
                    if param in target_params:
                        offsets[param] = (int(item["_offset"]), int(item["_length"]))
                except (json.JSONDecodeError, KeyError):
                    continue
        return offsets

    def _download_index(self, step):
        """Fetch the index file for a specific time step."""
        name = f"{self.date}000000-{step}h-oper-fc.index"
        url = f"{BASE_URL}/{self.date}/{FORECAST_TIME}/ifs/0p25/oper/{name}"
        path = self.idx_dir / name
        
        if not path.exists():
            try:
                r = self.session.get(url, timeout=30)
                if r.status_code == 200:
                    path.write_bytes(r.content)
            except Exception:
                # Silently fail for indices (sometimes step 0 doesn't have one or network glitch)
                pass
        return step, path

    def _download_slice(self, step, var_key, offset_data):
        """Download partial GRIB file based on byte range."""
        start, length = offset_data
        url = f"{BASE_URL}/{self.date}/{FORECAST_TIME}/ifs/0p25/oper/{self.date}000000-{step}h-oper-fc.grib2"
        out_path = self.work_dir / f"{var_key}_{step}h.grib2"
        
        if not out_path.exists():
            headers = {"Range": f"bytes={start}-{start + length - 1}"}
            # Stream=True prevents loading everything into RAM and helps with timeouts
            with self.session.get(url, headers=headers, timeout=60, stream=True) as r:
                r.raise_for_status()
                with open(out_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
        return out_path

    def process_variable(self, var_key, param_id, index_map):
        """Download slices, merge time, crop region, save as intermediate NC."""
        final_nc = self.root_dir / f"{var_key}.nc"
        
        if final_nc.exists():
            return  # Already done

        grib_files = []
        for step in STEPS:
            if step in index_map and param_id in index_map[step]:
                try:
                    f = self._download_slice(step, var_key, index_map[step][param_id])
                    grib_files.append(f)
                except Exception as e:
                    print(f"\n[Warning] Failed to download slice for {var_key} step {step}: {e}")
                    # If a slice is missing, we proceed (CDO might complain, but better than crashing)
        
        if not grib_files:
            return

        # Sort by timestep
        grib_files.sort(key=lambda x: int(x.stem.split("_")[-1].replace("h", "")))
        
        tmp_nc = self.root_dir / f"temp_{var_key}.nc"
        w, e, s, n = BBOX

        # CDO Magic: Merge time -> Crop -> Convert to NetCDF4
        try:
            run_shell(["cdo", "-O", "-f", "nc4", "-mergetime"] + [str(p) for p in grib_files] + [str(tmp_nc)])
            run_shell(["cdo", "-O", f"sellonlatbox,{w},{e},{s},{n}", str(tmp_nc), str(final_nc)])
            
            # Clean metadata history
            try:
                run_shell(["ncatted", "-O", "-a", "history,global,d,,", str(final_nc)])
            except: pass 
            
        except Exception as e:
            print(f"\n[Error] CDO processing failed for {var_key}: {e}")
            if final_nc.exists(): final_nc.unlink()
        finally:
            # Cleanup temp files
            if tmp_nc.exists(): tmp_nc.unlink()
            for f in grib_files: 
                try: f.unlink()
                except: pass

    def run(self):
        print(f"--- 1. Downloading & Pre-processing ({self.date}) ---")
        
        # Check if all done
        if all((self.root_dir / f"{k}.nc").exists() for k in VAR_CONFIG.keys()):
            print("   -> All intermediate files exist. Skipping download.")
            return

        # 1. Download Indices
        index_map = {}
        wanted_params = {v["param_id"] for v in VAR_CONFIG.values()}
        
        print("   -> Fetching Indices...")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = [pool.submit(self._download_index, s) for s in STEPS]
            for i, f in enumerate(as_completed(futures)):
                s, path = f.result()
                if path.exists():
                    index_map[s] = self._get_byte_offsets(path, wanted_params)
                show_progress(i + 1, len(STEPS), "Fetching Indices")
        print()

        # 2. Process Variables
        for i, (key, cfg) in enumerate(VAR_CONFIG.items()):
            show_progress(i + 1, len(VAR_CONFIG), f"Processing {key}")
            self.process_variable(key, cfg["param_id"], index_map)
        
        print("\n   -> Download complete.")
        
        # Cleanup Indices/Work dir
        shutil.rmtree(self.idx_dir, ignore_errors=True)
        shutil.rmtree(self.work_dir, ignore_errors=True)


# --- Part 2: Converter ---

class LisfloodConverter:
    def __init__(self, date_str, input_dir):
        self.date = date_str
        self.input_dir = input_dir
        
        if not AREA_MAP_PATH.exists():
            raise FileNotFoundError(f"Base map not found: {AREA_MAP_PATH}")
        
        self.area_ds = xr.open_dataset(AREA_MAP_PATH)

    def _get_latlon_names(self, ds):
        """Smart detection of lat/lon names."""
        lat = next((x for x in ds.variables if x in ['lat', 'latitude']), None)
        lon = next((x for x in ds.variables if x in ['lon', 'longitude']), None)
        if not lat or not lon:
            raise KeyError(f"Lat/Lon not found in {list(ds.variables)}")
        return lat, lon

    def _format_time_units(self, time_arr):
        """Generates 'hours since YYYY-MM-DD 00:00:00'."""
        # Use the first timestamp as origin
        ts = pd.to_datetime(time_arr[0])
        origin_str = ts.strftime("%Y-%m-%d %H:%M:%S.000000")
        return f"hours since {origin_str}", ts

    def process_file(self, var_key, config):
        infile = self.input_dir / f"{var_key}.nc"
        outfile = self.input_dir / f"{config['out_var']}.nc" # e.g. ta.nc

        if not infile.exists():
            print(f"   [SKIP] Missing input: {infile.name}")
            return

        print(f"   -> Converting {infile.name} to {outfile.name}...")

        with xr.open_dataset(infile) as ds_in:
            # 1. Clean dimensions
            ds_in = ds_in.squeeze(drop=True)
            
            # 2. Identify variables
            in_lat, in_lon = self._get_latlon_names(ds_in)
            ar_lat, ar_lon = self._get_latlon_names(self.area_ds)
            
            data_var = [v for v in ds_in.data_vars if v not in ds_in.coords][0]

            # 3. De-accumulation (if needed for radiation/rain)
            if config.get("is_accumulated", False):
                # ECMWF accumulation resets at start, but here we usually have a continuous stream.
                # Simple diff gets the per-step value.
                first = ds_in[data_var].isel(time=0).expand_dims("time")
                rest = ds_in[data_var].diff("time")
                ds_in[data_var] = xr.concat([first, rest], dim="time")

            # 4. Interpolate to Area Map Grid (Nearest Neighbor)
            # Ensure input is sorted for interpolation
            ds_in = ds_in.sortby(in_lat).sortby(in_lon)
            
            target_y = self.area_ds[ar_lat].values
            target_x = self.area_ds[ar_lon].values
            
            interp_da = ds_in[data_var].interp(
                {in_lat: target_y, in_lon: target_x}, 
                method="nearest"
            )

            # 5. Handle Time (The Tricky Part)
            # Convert to 'hours since start' as integer
            raw_times = ds_in["time"].values
            # Ensure numpy array of datetime64
            if not np.issubdtype(raw_times.dtype, np.datetime64):
                raw_times = np.array([np.datetime64(t) for t in raw_times], dtype="datetime64[ns]")
            
            units_str, origin_ts = self._format_time_units(raw_times)
            origin_np = np.datetime64(origin_ts)
            
            hours_since = ((raw_times - origin_np) / np.timedelta64(1, 'h')).astype('int64')

            # 6. Create Output DataArray
            out_da = xr.DataArray(
                interp_da.data,
                dims=("time", ar_lat, ar_lon),
                coords={
                    "time": hours_since,
                    ar_lat: target_y,
                    ar_lon: target_x
                },
                name=config["out_var"]
            )

            # 7. Attributes
            out_da.attrs = config["attrs"]
            out_da.attrs["coordinates"] = f"{ar_lon} {ar_lat}"

            ds_out = xr.Dataset({config["out_var"]: out_da})
            
            # Copy spatial attributes from area map
            ds_out[ar_lat].attrs = self.area_ds[ar_lat].attrs
            ds_out[ar_lon].attrs = self.area_ds[ar_lon].attrs
            
            # Set specific Time attributes required by LISFLOOD
            ds_out["time"].attrs = {
                "standard_name": "time",
                "long_name": "time",
                "units": units_str,
                "calendar": "proleptic_gregorian",
                "axis": "T"
            }

            # 8. Save
            encoding = {
                config["out_var"]: {"zlib": True, "complevel": 4, "_FillValue": np.nan},
                "time": {"dtype": "int64"}
            }
            ds_out.to_netcdf(outfile, encoding=encoding)
            
            # Optional: Remove the raw intermediate file to save space?
            # os.remove(infile) 

    def run(self):
        print(f"--- 2. Formatting for LISFLOOD ---")
        for key, cfg in VAR_CONFIG.items():
            try:
                self.process_file(key, cfg)
            except Exception as e:
                print(f"   [ERROR] Failed converting {key}: {e}")
                traceback.print_exc()


# --- Main Entry Point ---

def main():
    if len(sys.argv) < 2:
        print("Usage: python process_input_HRES_files_LISVAP.py <YYYYMMDD>")
        sys.exit(1)

    date_str = sys.argv[1]
    output_dir = BASE_DIR / date_str

    check_system_deps()
    
    # Step 1: Download raw data
    downloader = ECMWFDownloader(date_str, output_dir)
    downloader.run()

    # Step 2: Convert to Lisflood format
    converter = LisfloodConverter(date_str, output_dir)
    converter.run()

    print(f"\nSUCCESS! Data available in: {output_dir.resolve()}")

if __name__ == "__main__":
    main()