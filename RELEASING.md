poetry run dephell deps convert
poetry install
poetry build

poetry config repositories.testpypi https://test.pypi.org/legacy/
poetry publish -r testpypi

mkdir /tmp/testrelease; cd /tmp/testrelease
python3 -mvenv .venv ; source .venv/bin/activate
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple emojifs

emojifs -v
