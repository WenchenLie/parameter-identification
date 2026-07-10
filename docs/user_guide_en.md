# Hysteresis Parameter Identification (HPI) User Guide

## 1. Purpose

Hysteresis Parameter Identification (HPI) identifies OpenSees uniaxial material parameters from an experimental hysteresis curve. It generates candidate parameters, computes the simulated hysteresis response with the OpenSees Python module, and minimizes RMSE between the simulated and experimental curves.

## 2. Start The Application

Run from source in the project root:

```powershell
python .\main.py
```

After packaging, you can start the program by running the executable file:

```powershell
HPI-v<version>.exe
```

The application uses the built-in OpenSees module by default:

```text
resources\opensees\opensees.pyd
```

The built-in `.pyd` supports **Python 3.14**. To use another `opensees.pyd`, make sure it matches the current Python version, then enable `Custom opensees.pyd` and select the file.

## 3. Parameter Definition Tab

### Experimental Data

Click `Browse` and select a data file with at least two columns:

- Column 1: displacement
- Column 2: force

Click `Load / Refresh Curve` to load and preview the curve.

### Skeleton Points

`Skeleton method` provides two options:

- `Max displacement`
- `Max force`

Enable `Mark skeleton points` to show skeleton points in red.

`Skeleton weight` controls the contribution of skeleton-point RMSE to the single objective. The step is 0.2. A value of 0 uses only the full hysteresis curve RMSE.

### Optimization Algorithm

Choose `PSO` or `GA`, then click `Algorithm Parameters...` to edit the selected algorithm settings.

- `PSO`: Particle Swarm Optimization
- `GA`: Genetic Algorithm

PSO parameters:

- Population size
- Generations
- Initial inertia
- Final inertia
- Cognitive factor
- Social factor
- Velocity ratio

GA parameters:

- Population size
- Generations
- Crossover rate
- Mutation rate
- Mutation scale
- Tournament size
- Elite count

Enable `Fixed random seed` for reproducible runs. Disable it for random initialization.

Use `Menu > Default Algorithm Parameters` to set persistent default parameters for PSO and GA. These defaults are saved in the system settings and loaded automatically the next time HPI starts.

### Material Definition

Only the middle code editor is editable. The application generates the fixed function wrapper and parameter extraction lines from the parameter table.

Editable example:

```python
    mats = [
        ["Steel01", 1, fy, E0, b],
    ]
    ctrl_tag = 1
```

You may define multiple OpenSees materials in the editable block. Use positive integers starting from 1 as material tags and set `ctrl_tag` to the controlling material tag.

### Material Parameters

Set each parameter in `Material Parameters`:

- `Name`: valid Python variable name
- `Lower`: lower bound
- `Upper`: upper bound

## 4. Run Identification

Click `Start` to run. `Stop` requests termination after the current generation finishes.

The log is cleared before each run and records:

- start time
- algorithm
- OpenSees module path
- parameter bounds
- per-generation best RMSE

After the run finishes, the application checks whether any final parameter is close to its lower or upper bound. If so, it warns you to adjust bounds and run again.

## 5. Results Tab

The results tab includes:

- parameter history plot
- RMSE history plot
- hysteresis comparison plot
- generation slider
- final parameter table
- run log

Move the generation slider to inspect different iterations.

## 6. Save Results

Click `Save Data...` after a run. The application exports:

- `parameter_definitions.json`
- `final_results.json`
- `run.log`
- `experimental_hysteresis.png`
- `hysteresis_comparison.png`
- `rmse_history.png`
- `parameter_*.png`
- `hysteresis_iterations.gif`

The export folder is named:

```text
identification_export_YYYYMMDD
```

If the folder already exists, `_2`, `_3`, and so on are appended.

## 7. Menu

The menu includes:

- `User Guide > Chinese`
- `User Guide > English`
- `Default Algorithm Parameters > PSO`
- `Default Algorithm Parameters > GA`
- `About`
- `Exit`
