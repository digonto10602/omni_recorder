"""Streaming audio statistics and sanity checks for finished recordings.

Everything works chunk by chunk, so a multi-hour recording never has to fit in memory.

Terms:
- dBFS: decibels relative to full scale; 0 dBFS is the loudest value a file can hold.
- RMS: root-mean-square, the average power of a signal.
- clipping: samples stuck at full scale because the signal was too loud.
- bleed: the other side's voice, played by the speakers, picked up again by the microphone.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

WINDOW_S = 0.1                 # activity windows are 100 ms long
ACTIVE_DBFS = -45.0            # a window is "active" if its RMS is above this
SILENT_ACTIVE_FRACTION = 0.005 # a track active in < 0.5 % of windows is "silent"
CLIP_LEVEL = 0.999             # |sample| >= this counts as clipped
CLIP_WARN_SAMPLES = 100        # warn if at least this many samples clipped (about 2 ms at 48 kHz)
SHORT_SPAN_RATIO = 0.5         # warn if one track's active span < 50 % of the other's

# Bleed detection (speaker sound leaking into the microphone)
BLEED_RATE = 8000              # analysis sample rate after decimation
BLEED_BLOCK_S = 2.0            # length of each compared block of `them`
BLEED_MAX_LAG_S = 0.5          # mic may lag the Chrome stream by up to 500 ms
BLEED_MIN_LAG_S = -0.05        # and lead it by at most 50 ms (should not happen physically)
BLEED_THEM_ACTIVE_DBFS = -40.0 # only judge blocks where `them` is clearly audible
BLEED_CORR = 0.2               # normalized correlation above this counts as a "hit"
BLEED_HIT_FRACTION = 0.3       # bleed if >= 30 % of judged blocks are hits ...
BLEED_LAG_TOL_S = 0.003        # ... and >= 50 % of the hits agree on the lag within 3 ms
BLEED_MIN_BLOCKS = 5


def db(x: float) -> float:
    return 20.0 * math.log10(x) if x > 0 else float("-inf")


@dataclass
class TrackStats:
    """Accumulates statistics for one mono track, fed chunk by chunk."""
    rate: int
    sumsq: float = 0.0
    n: int = 0
    peak: float = 0.0
    clipped: int = 0
    window_rms: list[float] = field(default_factory=list)
    _carry: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))

    def add(self, x: np.ndarray, raw_channels: np.ndarray | None = None) -> None:
        x = np.asarray(x, dtype=np.float64)
        self.sumsq += float(np.dot(x, x))
        self.n += x.size
        if x.size:
            self.peak = max(self.peak, float(np.max(np.abs(x))))
        src = x if raw_channels is None else raw_channels
        self.clipped += int(np.count_nonzero(np.abs(src) >= CLIP_LEVEL))
        w = int(round(self.rate * WINDOW_S))
        buf = np.concatenate([self._carry, x])
        k = buf.size // w
        if k:
            blocks = buf[: k * w].reshape(k, w)
            self.window_rms.extend(np.sqrt(np.mean(blocks * blocks, axis=1)).tolist())
        self._carry = buf[k * w:]

    def result(self) -> dict:
        rms = math.sqrt(self.sumsq / self.n) if self.n else 0.0
        win = np.asarray(self.window_rms)
        thr = 10 ** (ACTIVE_DBFS / 20)
        active = np.nonzero(win > thr)[0] if win.size else np.zeros(0, dtype=int)
        first = float(active[0] * WINDOW_S) if active.size else None
        last = float((active[-1] + 1) * WINDOW_S) if active.size else None
        return {
            "duration_s": self.n / self.rate if self.rate else 0.0,
            "rms_dbfs": round(db(rms), 2) if rms > 0 else None,
            "peak_dbfs": round(db(self.peak), 2) if self.peak > 0 else None,
            "clipped_samples": self.clipped,
            "active_fraction": round(float(active.size / win.size), 4) if win.size else 0.0,
            "active_first_s": first,
            "active_last_s": last,
            "active_span_s": round(last - first, 2) if active.size else 0.0,
        }


def decimate(x: np.ndarray, factor: int) -> np.ndarray:
    """Crude anti-aliased decimation by block averaging (enough for correlation of speech)."""
    k = x.size // factor
    return x[: k * factor].reshape(k, factor).mean(axis=1)


class BleedDetector:
    """Looks for the `them` signal inside the `me` signal at a stable delay.

    Both signals are decimated to 8 kHz. For each 2 s block where `them` is audible,
    the normalized cross-correlation between that block and the `me` signal is
    computed for delays from -50 ms to +500 ms. A strong peak at a consistent delay
    means the microphone hears the speakers.
    """

    def __init__(self, rate: int):
        self.factor = max(1, rate // BLEED_RATE)
        self.r = rate / self.factor
        self.block = int(BLEED_BLOCK_S * self.r)
        self.lo = int(round(BLEED_MIN_LAG_S * self.r))
        self.hi = int(round(BLEED_MAX_LAG_S * self.r))
        self.me = np.zeros(0)
        self.them = np.zeros(0)
        self._me_tail = np.zeros(0)
        self._them_tail = np.zeros(0)
        self.offset = 0               # decimated-sample index of self.them[0]
        self.judged = 0
        self.hits: list[tuple[float, float]] = []   # (corr, lag_s)
        self.best: list[float] = []

    def add(self, me: np.ndarray, them: np.ndarray) -> None:
        me = np.concatenate([self._me_tail, np.asarray(me, dtype=np.float64)])
        them = np.concatenate([self._them_tail, np.asarray(them, dtype=np.float64)])
        k = (min(me.size, them.size) // self.factor) * self.factor
        self._me_tail, self._them_tail = me[k:], them[k:]
        self.me = np.concatenate([self.me, decimate(me[:k], self.factor)])
        self.them = np.concatenate([self.them, decimate(them[:k], self.factor)])
        self._process(final=False)

    def _process(self, final: bool) -> None:
        pre = -self.lo
        while True:
            # block of `them` starts at index `pre` of the buffers; me needs [start+lo, start+block+hi)
            need = pre + self.block + self.hi
            if self.them.size < need:
                break
            t = self.them[pre: pre + self.block]
            m = self.me[0: need]  # me index 0 corresponds to them index pre+lo
            self._judge(t, m)
            drop = self.block
            self.me = self.me[drop:]
            self.them = self.them[drop:]

    def _judge(self, t: np.ndarray, m: np.ndarray) -> None:
        t = t - t.mean()
        trms = math.sqrt(float(np.mean(t * t)))
        if trms <= 10 ** (BLEED_THEM_ACTIVE_DBFS / 20):
            return
        n = t.size
        nl = m.size - n + 1                     # number of lags
        size = 1 << int(math.ceil(math.log2(m.size + n)))
        num = np.fft.irfft(np.fft.rfft(m, size) * np.conj(np.fft.rfft(t, size)), size)[:nl]
        c2 = np.concatenate([[0.0], np.cumsum(m * m)])
        m_en = c2[n: n + nl] - c2[0:nl]
        m_mean_sq = (np.concatenate([[0.0], np.cumsum(m)])[n: n + nl] - np.concatenate([[0.0], np.cumsum(m)])[0:nl]) ** 2 / n
        den = np.sqrt(np.maximum(m_en - m_mean_sq, 1e-20) * float(np.dot(t, t)))
        corr = np.abs(num) / den
        i = int(np.argmax(corr))
        self.judged += 1
        self.best.append(float(corr[i]))
        if corr[i] >= BLEED_CORR:
            self.hits.append((float(corr[i]), (i + self.lo) / self.r))

    def result(self) -> dict:
        res = {"blocks_judged": self.judged, "hits": len(self.hits), "detected": False,
               "median_best_corr": round(float(np.median(self.best)), 3) if self.best else None,
               "lag_ms": None, "hit_fraction": 0.0}
        if self.judged < BLEED_MIN_BLOCKS:
            res["note"] = "too little audible speech from the other side to judge"
            return res
        frac = len(self.hits) / self.judged
        res["hit_fraction"] = round(frac, 3)
        if self.hits:
            lags = np.array([l for _, l in self.hits])
            med = float(np.median(lags))
            agree = float(np.mean(np.abs(lags - med) <= BLEED_LAG_TOL_S))
            res["lag_ms"] = round(med * 1000, 1)
            res["lag_agreement"] = round(agree, 3)
            res["detected"] = frac >= BLEED_HIT_FRACTION and agree >= 0.5
        return res


def sanity_warnings(me: dict, them: dict, total_s: float, them_label: str = "them.flac") -> list[str]:
    """Human-readable warnings for silent, clipped or much-shorter tracks."""
    w: list[str] = []
    for label, s in (("me.flac (your microphone)", me), (f"{them_label} (the other side)", them)):
        if s["active_fraction"] < SILENT_ACTIVE_FRACTION:
            w.append(f"SILENT: {label} has sound in only {100 * s['active_fraction']:.2f} % of the recording "
                     f"(RMS {s['rms_dbfs']} dBFS, peak {s['peak_dbfs']} dBFS).")
        if s["clipped_samples"] >= CLIP_WARN_SAMPLES:
            w.append(f"CLIPPED: {label} has {s['clipped_samples']} samples at full scale; it was too loud and is distorted there.")
    if total_s >= 30 and me["active_span_s"] > 0 and them["active_span_s"] > 0:
        a, b = me["active_span_s"], them["active_span_s"]
        if min(a, b) < SHORT_SPAN_RATIO * max(a, b):
            short = "me.flac" if a < b else them_label
            w.append(f"SHORT: sound in {short} spans only {min(a, b):.1f} s versus {max(a, b):.1f} s in the other track; "
                     "part of one side may be missing.")
    return w
