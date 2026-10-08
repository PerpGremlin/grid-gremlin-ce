"""E11: the write pacer. A fleet's start places every bot's ladder in one
minute — thirty orders on the carry sub met Bybit's rate limit (10006,
2026-10-08) and the backoff rode it, but a fleet should not have to. Two
rules, pure: a floor between writes (the venue's budget is per second,
so writes are spread rather than burst), and the venue's own word — a
response that says the budget is spent names the moment it refills, and
the next write waits for it. Reads are not paced (E10 keeps them cheap).
"""
import time

from ..fmt import float_or


class Pacer:
    def __init__(self, min_gap=0.12, clock=None, sleep=None):
        self.min_gap = float(min_gap)
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._last = None
        self._hold_until = None          # the venue's refill moment, on its clock
        self.waited = 0.0                # how long the pacer has held writes, in all

    def wait(self, venue_now_ms=None):
        """Called before a write: holds until the gap has passed and any
        refill moment the venue named has come."""
        now = self._clock()
        due = now
        if self._last is not None:
            due = max(due, self._last + self.min_gap)
        if self._hold_until is not None and venue_now_ms is not None:
            left = (self._hold_until - venue_now_ms) / 1000.0
            if left > 0:
                due = max(due, now + min(left, 5.0))
            self._hold_until = None
        if due > now:
            self._sleep(due - now)
            self.waited += due - now
        self._last = self._clock()

    def learn(self, headers):
        """The venue's budget headers after a write: a spent budget names
        the refill moment (ms on the venue's clock); the next write waits."""
        left = float_or(headers.get('X-Bapi-Limit-Status'))
        reset = float_or(headers.get('X-Bapi-Limit-Reset-Timestamp'))
        if left is None or reset is None:
            return None
        if left <= 0:
            self._hold_until = int(reset)
        return int(left)
