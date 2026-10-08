# ocdu - developer and packaging helpers.
# Requires uv (https://docs.astral.sh/uv/). Packaging needs the dev extras
# (PyInstaller); run `make sync` first. Recipes use '>' as the recipe prefix
# (.RECIPEPREFIX) so the file does not depend on literal tab characters.

.RECIPEPREFIX := >

PY    := uv run python
NAME  := ocdu
SRC   := src
ENTRY := packaging/ocdu_launcher.py

# Build output directory, read from the ocdu config (DIST_DIR) by the program
# itself. Falls back to "dist" when the value is unavailable.
DIST := $(shell uv run --no-sync ocdu build-dir)
ifeq ($(strip $(DIST)),)
DIST := dist
endif

.DEFAULT_GOAL := help
.PHONY: help sync run tui test test-cov lint push-private push-public package package-dir venv-install venv-install-dev tool-install tool-uninstall clean

help:
> @$(info Usage: make [target])
> @$(info )
> @$(info Targets:)
> @$(info   sync             Install or refresh the virtual environment)
> @$(info   run              Launch the interactive TUI)
> @$(info   tui              Alias for run)
> @$(info   test             Run the test suite with pytest)
> @$(info   test-cov         Run tests with coverage)
> @$(info   lint             Lint with ruff)
> @$(info   push-private     Push master to the private remote (origin))
> @$(info   push-public      Build the filtered publish branch and push it to github)
> @$(info   venv-install     Install ocdu into the project virtualenv (.venv))
> @$(info   venv-install-dev Install ocdu editable into the project virtualenv (.venv))
> @$(info   tool-install     Install ocdu as a global uv tool (on PATH; --force refreshes it))
> @$(info   tool-uninstall   Remove the global uv tool)
> @$(info   package          Build a single-file executable at dist/ocdu.exe)
> @$(info   package-dir      Build an onedir executable at dist/ocdu/ocdu.exe)
> @$(info   clean            Remove the build and dist directories)
> @$(info )
> @$(info Build output directory (DIST_DIR): $(DIST))

sync:
> uv sync

run:
> uv run ocdu

tui: run

test:
> uv run pytest

test-cov:
> uv run pytest --cov=ocdu --cov-report=term --cov-report=html

lint:
> uv run ruff check .

push-private:
> $(PY) scripts/publish.py --target private

push-public:
> $(PY) scripts/publish.py --target public

package:
> uv run pyinstaller --noconfirm --onefile --name $(NAME) --paths $(SRC) --collect-all textual --distpath "$(DIST)" --workpath build --specpath build $(ENTRY)

package-dir:
> uv run pyinstaller --noconfirm --onedir --name $(NAME) --paths $(SRC) --collect-all textual --distpath "$(DIST)" --workpath build --specpath build $(ENTRY)

venv-install:
> uv pip install .

venv-install-dev:
> uv pip install -e .

tool-install:
> uv tool install --force .

tool-uninstall:
> uv tool uninstall $(NAME)

clean:
> $(PY) -c "import shutil; [shutil.rmtree(p, ignore_errors=True) for p in ('build', 'dist')]; print('cleaned build/ and dist/')"
