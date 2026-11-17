#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Temperature-based software PWM for the Switch Lite dock fan."""
import logging
from pathlib import Path
import signal
import time

import lgpio

GPIO = 18
PWM_HZ = 25
SAMPLE_SECONDS = 2
STARTUP_KICK_SECONDS = 2
THERMAL_INPUT = Path("/sys/class/thermal/thermal_zone0/temp")

# Duties were observed on this two-wire fan: 20% is the selected quiet level;
# 10% stalled/twitched. Higher levels also ran steadily during short checks.
STATES = (("off", 0), ("low", 20), ("medium", 45), ("high", 80), ("full", 100))
UP_MILLIC = (45_000, 55_000, 65_000, 70_000)
DOWN_MILLIC = (0, 43_000, 53_000, 63_000, 68_000)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("switch-dock-fan")
running = True


def request_stop(_signum, _frame):
    global running
    running = False


def read_temperature():
    value = int(THERMAL_INPUT.read_text().strip())
    if not 0 <= value <= 120_000:
        raise ValueError(f"CPU temperature outside expected range: {value} m°C")
    return value


def state_for_temperature(temp):
    state = 0
    while state < len(UP_MILLIC) and temp >= UP_MILLIC[state]:
        state += 1
    return state


def hysteresis_state(state, temp):
    while state < len(UP_MILLIC) and temp >= UP_MILLIC[state]:
        state += 1
    while state > 0 and temp < DOWN_MILLIC[state]:
        state -= 1
    return state


def main():
    global running
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    chip = lgpio.gpiochip_open(0)
    if chip < 0:
        raise RuntimeError(f"Cannot open GPIO chip 0: {chip}")
    claimed = False

    def drive(duty):
        # Keep the PWM frequency nonzero even at the endpoints. lgpio's API
        # rejects frequency=0 on this platform, while 0% and 100% are valid.
        result = lgpio.tx_pwm(chip, GPIO, PWM_HZ, duty)
        if result < 0:
            raise RuntimeError(f"Cannot set GPIO18 duty to {duty}%: {result}")

    try:
        result = lgpio.gpio_claim_output(chip, GPIO, 1)
        if result < 0:
            raise RuntimeError(f"Cannot claim GPIO18: {result}")
        claimed = True
        drive(100)
        log.info("Startup kick: 100%% for %d seconds", STARTUP_KICK_SECONDS)
        time.sleep(STARTUP_KICK_SECONDS)

        state = None
        sensor_failed = False
        while running:
            try:
                temp = read_temperature()
            except (OSError, ValueError) as exc:
                drive(100)
                if not sensor_failed:
                    log.error("Temperature read failed; fan forced to 100%%: %s", exc)
                sensor_failed = True
                state = None
                time.sleep(SAMPLE_SECONDS)
                continue

            if sensor_failed:
                log.info("Temperature sensor recovered")
                sensor_failed = False
            new_state = state_for_temperature(temp) if state is None else hysteresis_state(state, temp)
            if new_state != state:
                if state == 0 and new_state > 0:
                    drive(100)
                    log.info("Fan start kick before low-speed mode")
                    time.sleep(STARTUP_KICK_SECONDS)
                name, duty = STATES[new_state]
                drive(duty)
                log.info("CPU %.1f C; fan %s (%d%%)", temp / 1000, name, duty)
                state = new_state
            time.sleep(SAMPLE_SECONDS)
    finally:
        if claimed:
            try:
                drive(100)
            except Exception:
                log.exception("Could not force fan to 100%% during exit")
        lgpio.gpiochip_close(chip)


if __name__ == "__main__":
    main()
