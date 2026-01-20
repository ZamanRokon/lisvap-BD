# Customized LISVAP Forecast Pre-processor with ECMWF HRES data

**A spatially distributed hydrological pre-processor for LISFLOOD, customized for ECMWF HRES forecast data.**

## 🌊 Overview

**LISVAP** (LISFLOOD Potential Evapotranspiration) is a pre-processor based on the Penman-Monteith equation. It calculates potential evapotranspiration grids used as input for the **LISFLOOD** hydrological model.

This repository contains a **customized forecast version** of LISVAP developed to generate high-resolution forecast products. While currently configured for the **Bangladesh river basins**, the model logic is spatially adaptable to any region covered by ECMWF data.

### 🚀 Key Capabilities
* **Input:** Integrated with **ECMWF HRES** (High-Resolution) forecast data.
* **Outputs:**
    * **ET0:** Potential Reference Evapotranspiration.
    * **ES0:** Potential Evaporation from Bare Soil.
    * **EW0:** Potential Evaporation from Open Water.
* **Forecast Horizon:** Generates up to **15-day forecasts** at **6-hourly** timesteps.
* **Target Model:** Prepares forcing data specifically for LISFLOOD.

## ⚙️ Installation & Setup

Follow these steps to set up the environment and download the model.

### 1. Clone the Repository
```bash
conda env create -f lisflood_env.yml
conda activate lisflood
git clone https://github.com/ZamanRokon/lisvap-BD.git
cd lisvap-BD
```
### 🏃‍♂️ Usage
```bash
cd tests/
python run_lisvap_BD.py 20250606
```
