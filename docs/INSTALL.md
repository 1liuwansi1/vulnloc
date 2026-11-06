# Installation

Validated: Linux/WSL2, Python 3.12.3, NumPy 2.5.3. No model SDK required.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/vulnloc verify --root .
```

`setuptools==84.2.1` is pinned for the validated build; `numpy==2.5.3` is the
only numerical runtime dependency. Do not install the original research venv.

During this build standard venv creation initially FAILED because ensurepip was
absent. An independent venv was bootstrapped with an already-installed pip's
`--python .venv/bin/python` option, installing fresh NumPy/setuptools/pip from PyPI.
This is not a copied virtual environment. On a fresh host install the OS venv
package first, or use an existing trusted pip with `--python`.

Use this repository checkout as the working directory, or pass `--root` to its
location. Editable installation does not bundle the data/paper into a wheel.
Package downloads may need network; L1 runs offline after installation.
Reproduction/test commands never load model keys or start provider processes.
