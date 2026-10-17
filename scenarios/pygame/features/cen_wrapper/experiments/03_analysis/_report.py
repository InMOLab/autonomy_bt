"""Shared by the analysis scripts: where the data are read from, and a copy of everything a script prints, written to
04_results/<script name>.md.

Environment variables (optional): DATA_DIR (default ../02_data), RESULTS_DIR (default ../04_results).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get('DATA_DIR', os.path.join(HERE, '..', '02_data')) + os.sep
RESULTS = os.environ.get('RESULTS_DIR', os.path.join(HERE, '..', '04_results'))


class _Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            st.write(s)

    def flush(self):
        for st in self.streams:
            st.flush()


def start(script_file):
    """Print to the screen and to 04_results/<script>.md from here on."""
    os.makedirs(RESULTS, exist_ok=True)
    name = os.path.splitext(os.path.basename(script_file))[0] + '.md'
    sys.stdout = _Tee(sys.__stdout__, open(os.path.join(RESULTS, name), 'w', encoding='utf-8'))


def table(header, rows):
    """Markdown table."""
    print('| ' + ' | '.join(header) + ' |')
    print('|' + '---|' * len(header))
    for r in rows:
        print('| ' + ' | '.join(str(c) for c in r) + ' |')
