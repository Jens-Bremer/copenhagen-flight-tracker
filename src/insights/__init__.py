"""Pure data functions powering the `airlines.html` price-insight panels.

Each submodule exposes a `build_*` function that takes already-loaded rows
(list of dicts with the slim-CSV schema) and returns a JSON-serializable
dict. Rendering lives in `frontend/js/render-*.js`.
"""
