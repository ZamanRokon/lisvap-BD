# Customized LISVAP Forecast Pre-processor (ECMWF HRES)

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

---

## 🛠️ Prerequisites

To run this model, you need:
1.  **Miniconda** or **Anaconda** installed on your system.
2.  Access to ECMWF HRES data (or the sample data provided in this repository for testing).

---

## ⚙️ Installation & Setup

Follow these steps to set up the environment and download the model.

### 1. Clone the Repository
```bash
git clone [https://github.com/ZamanRokon/lisvap-BD.git](https://github.com/ZamanRokon/lisvap-BD.git)
cd lisvap-BD
