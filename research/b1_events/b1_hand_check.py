"""Hand check of 20 random buyback-start events (seed in b1_events.HAND_CHECK_SEED): message id -> (does the notice
start a new buyback programme?, note). Judged on 8 October 2026 by reading each title and the start of its body."""

VERDICTS: dict[int, tuple[bool, str]] = {
    443717: (True, "DFDS: new DKK 400m buyback"),
    455560: (True, "Europris: up to 2m shares, for an acquisition or cancellation"),
    476846: (True, "Telenor: up to 43m shares, 2019-20"),
    501579: (True, "NRC: NOK 2m, for the employee share programme"),
    532314: (True, "Itera: reverse book-building offer, for employee options"),
    561580: (True, "Elop: intention to buy back up to 10 %"),
    561925: (True, "Kitron: NOK 1m, for board remuneration"),
    564152: (True, "Napatech: NOK 12m, to offset incentive dilution"),
    569368: (True, "ECIT: NOK 8m, for the incentive plan"),
    569833: (True, "Elop: another programme, NOK 5m"),
    591591: (True, "B2Holding: NOK 162.6m, to reduce capital"),
    592940: (True, "BW LPG: USD 25-50m tender offer"),
    596681: (True, "Elkem: 2m shares, for the incentive scheme"),
    603622: (True, "Sparebanken Vest: NOK 5m, for employee bonus and savings schemes"),
    638018: (True, "Boliden: SEK 40m, for the share savings programme"),
    652987: (True, "Xplora: NOK 10m, for the employee share purchase programme"),
    655329: (True, "Elopak: NOK 18m, for the long-term incentive plan"),
    665919: (False, "a programme's termination; the title says 'announced', and 'terminat' is not on the stop list"),
    667322: (True, "ABL Group: NOK 5m"),
    674869: (True, "Sparebanken Norge: NOK 50m, for employee bonus and savings schemes"),
}

# Of the 19 real starts, these only supply shares to employee, board or incentive schemes (stated in the notice).
INCENTIVE_ONLY = {501579, 532314, 561925, 564152, 569368, 596681, 603622, 638018, 652987, 655329, 674869}
