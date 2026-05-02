# Development Setup

Use Python 3.12 for the backend. The checked-in `.venv` may point at a missing
interpreter on some machines, so recreate it instead of relying on it blindly.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Baseline verification:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q app run.py config.py
python -c "import app.main; print('app.main import ok')"
```
