# Well Intervention Scheduling

A Python notebook with a Gradio interface for optimizing rig schedules and viewing Gantt timelines, fleet routes, and Monte Carlo risk analysis.

## First-time setup

Install Python 3.9 or newer, then run these commands from the project directory:

```bash
cd /path/to/bayu-well-intervention-scheduling

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

These activation commands apply to macOS and Linux. On Windows PowerShell, activate the environment with `.venv\Scripts\Activate.ps1` instead.

`requirements.txt` pins Gradio and Pydantic and constrains Hugging Face Hub to compatible versions. It also includes notebook widgets for progress bars.

## Launch the app

With the virtual environment active, start JupyterLab:

```bash
python -m jupyter lab
```

1. Open `Trial.ipynb` in JupyterLab and select the Python kernel from your virtual environment.
2. Select **Run → Run All Cells**.
3. Use the Gradio interface displayed in the notebook, or open the local URL printed by Gradio.
4. Under **Ingest Dataset → Rig Fleet Dataset**, upload `example_rig.csv`. The fleet starts empty, so upload rigs or add them manually before optimizing.
5. Optionally upload `example-well.csv` under **Well Dataset**. The app starts with 20 generated wells; uploads merge into the existing dataset and deduplicate by `Well_ID`.
6. Click **Run Optimization** to generate the schedule and charts.

Excel (`.xlsx`) uploads are also supported; `openpyxl` provides the Excel reader.

## Subsequent launches

From the project directory:

```bash
source .venv/bin/activate
python -m jupyter lab
```

Open the notebook and run all cells again to start the app. To stop it, shut down the notebook kernel and press **Ctrl+C** in the terminal running JupyterLab.

## Repair an existing environment

If Gradio fails to import with `cannot import name 'HfFolder'`, you see `IProgress not found`, or launch fails with `TypeError: argument of type 'bool' is not iterable`, update the active environment:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Restart JupyterLab and select **Kernel → Restart Kernel and Run All Cells** so the notebook loads the repaired dependencies.

The boolean schema error comes from incompatible Pydantic versions and can also cause Gradio to report that localhost is inaccessible. Install the constrained dependencies above before changing network settings. Public sharing is not needed for local use.
