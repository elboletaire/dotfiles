# Taller

`taller.py` collects every project the user works on -- the git repositories
under `[taller].roots` plus `extra`, each with its uncommitted and unpushed
work, the aoe and herdr agents running in it and the last conversation held
there -- and has the actions to focus, resume or open one in herdr. It used to
be the right-hand column of the Arxiu board (`ai/arxiu/`); it is parked here,
unchanged and with its own `config.toml`, for a future workspace of its own.
`python3 taller.py [--json]` shows what it collects; tests:
`python3 -m unittest discover -s ai/taller/tests`.
