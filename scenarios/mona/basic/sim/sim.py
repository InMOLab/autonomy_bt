"""
MONA scenario Sim. All four modes (full_simulation / puppet / p2p /
offboard) use this same Sim — only ``mona.mode`` in the yaml differs.
MonaSim handles wall-clock display, MonaComm wiring, WhyCon UDP listener,
and the real-robot keyboard-event override automatically based on the
mode.
"""
from platforms.mona.mona_sim import MonaSim


class Sim(MonaSim):
    pass
