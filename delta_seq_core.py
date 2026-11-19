"""
Core logic for building Delta Elektronika (SM15K / SM3300 ...) sequencer files
from ControlDesk-style signal segments.  No GUI dependencies - can be used and
tested on its own.

Sequencer syntax used (see "Ethernet & Sequencer Programming" manual):
    SV=<v>  SC=<i>  SP=<p>      settings
    W=<s>                       wait 0.001 .. 65535 s
    #A=<n>  INC #A,1            variable / increment
    CJL <op>,<value>,<step>     conditional jump if less
    JP <label>                  unconditional jump
    END                         mandatory last step
Upload commands:
    PROG:SEL:NAM <name>, PROG:SEL:STE <n> <cmd>, PROG:SEL:LAB <label>,<step>,
    PROG:SEL:STA RUN, PROG:SEL:NON, PROG:SAV
"""
from __future__ import annotations

import json
import math
import re
import socket
import time
from dataclasses import dataclass, field, asdict

MAX_STEPS = 2000
MIN_WAIT = 0.001
MAX_WAIT = 65535.0

# --------------------------------------------------------------------------
# Segment definitions:  type -> list of (key, label, default, is_int)
# --------------------------------------------------------------------------
SEGMENT_TYPES: dict[str, list[tuple[str, str, float, bool]]] = {
    "Constant": [
        ("value", "Value", 0.0, False),
        ("duration", "Duration [s]", 1.0, False),
    ],
    "Ramp": [
        ("start", "Start value", 0.0, False),
        ("end", "End value", 10.0, False),
        ("duration", "Duration [s]", 5.0, False),
        ("dt", "Step time [s]", 0.1, False),
    ],
    "Sine": [
        ("offset", "Offset", 10.0, False),
        ("amplitude", "Amplitude", 5.0, False),
        ("freq", "Frequency [Hz]", 0.5, False),
        ("phase", "Phase [deg]", 0.0, False),
        ("duration", "Duration [s]", 4.0, False),
        ("dt", "Sample time [s]", 0.05, False),
    ],
    "Square": [
        ("low", "Low value", 0.0, False),
        ("high", "High value", 10.0, False),
        ("period", "Period [s]", 2.0, False),
        ("duty", "Duty cycle [%]", 50.0, False),
        ("cycles", "Cycles", 3, True),
    ],
    "Table": [],      # free list of [value, hold_time] points
    "Combine": [      # two child segments combined with an operation
        ("dt", "Sample time [s]", 0.05, False),
    ],
    "Triangle": [
        ("low", "Low value", 0.0, False),
        ("high", "High value", 10.0, False),
        ("period", "Period [s]", 4.0, False),
        ("cycles", "Cycles", 2, True),
        ("dt", "Step time [s]", 0.1, False),
    ],
}


def default_segment(kind: str) -> dict:
    seg = {"type": kind}
    if kind == "Table":
        seg["points"] = [[0.0, 1.0], [10.0, 1.0]]
    if kind == "Combine":
        seg["op"] = "Multiply"
        seg["a"] = default_segment("Sine")
        seg["b"] = default_segment("Ramp") | {"start": 0.0, "end": 1.0,
                                             "duration": 4.0}
    for key, _label, default, is_int in SEGMENT_TYPES[kind]:
        seg[key] = int(default) if is_int else float(default)
    return seg


def describe_segment(seg: dict) -> str:
    k = seg["type"]
    if k == "Constant":
        return f"Constant {seg['value']:g} for {seg['duration']:g} s"
    if k == "Ramp":
        return f"Ramp {seg['start']:g} → {seg['end']:g} in {seg['duration']:g} s"
    if k == "Sine":
        return (f"Sine {seg['offset']:g} ± {seg['amplitude']:g}, "
                f"{seg['freq']:g} Hz, {seg['duration']:g} s")
    if k == "Square":
        return (f"Square {seg['low']:g}/{seg['high']:g}, T={seg['period']:g} s, "
                f"{seg['cycles']}×")
    if k == "Table":
        pts = seg.get("points", [])
        return f"Table, {len(pts)} points, {sum(p[1] for p in pts):g} s"
    if k == "Combine":
        sym = COMBINE_OPS[seg["op"]][0]
        a, b = describe_segment(seg["a"]), describe_segment(seg["b"])
        if sym in ("min", "max"):
            return f"{sym}({a}, {b})"
        return f"({a}) {sym} ({b})"
    if k == "Triangle":
        return (f"Triangle {seg['low']:g}/{seg['high']:g}, T={seg['period']:g} s, "
                f"{seg['cycles']}×")
    return k


# --------------------------------------------------------------------------
# Continuous evaluation (used by Combine)
# --------------------------------------------------------------------------
COMBINE_OPS = {
    "Add": ("+", lambda a, b: a + b),
    "Subtract": ("−", lambda a, b: a - b),
    "Multiply": ("×", lambda a, b: a * b),
    "Min": ("min", min),
    "Max": ("max", max),
}


def segment_duration(seg: dict) -> float:
    k = seg["type"]
    if k in ("Constant", "Ramp", "Sine"):
        return float(seg["duration"])
    if k in ("Square", "Triangle"):
        return float(seg["period"]) * int(seg["cycles"])
    if k == "Table":
        return float(sum(p[1] for p in seg.get("points", [])))
    if k == "Combine":
        return max(segment_duration(seg["a"]), segment_duration(seg["b"]))
    raise ValueError(f"Unknown segment type {k}")


def value_at(seg: dict, t: float) -> float:
    """Value of a segment at time t (s, relative to segment start).
    Beyond its end a segment holds its final value."""
    k = seg["type"]
    dur = segment_duration(seg)
    t = min(max(t, 0.0), dur)
    if k == "Constant":
        return seg["value"]
    if k == "Ramp":
        return seg["start"] + (seg["end"] - seg["start"]) * (t / dur if dur else 1)
    if k == "Sine":
        return seg["offset"] + seg["amplitude"] * math.sin(
            2 * math.pi * seg["freq"] * t + math.radians(seg["phase"]))
    if k == "Square":
        p = seg["period"]
        if p <= 0:
            return seg["low"]
        tt = (t % p) if t < dur else p
        return seg["high"] if tt < p * seg["duty"] / 100.0 else seg["low"]
    if k == "Triangle":
        p = seg["period"]
        if p <= 0 or t >= dur:
            return seg["low"]
        x = (t % p) / p
        f = 2 * x if x < 0.5 else 2 - 2 * x
        return seg["low"] + (seg["high"] - seg["low"]) * f
    if k == "Table":
        acc = 0.0
        pts = seg.get("points", [])
        for v, h in pts:
            acc += h
            if t < acc:
                return v
        return pts[-1][0] if pts else 0.0
    if k == "Combine":
        return COMBINE_OPS[seg["op"]][1](value_at(seg["a"], t), value_at(seg["b"], t))
    raise ValueError(f"Unknown segment type {k}")


# --------------------------------------------------------------------------
# Sampling:  segment -> list of (value, hold_time)
# --------------------------------------------------------------------------
def _n(duration: float, dt: float) -> int:
    if dt <= 0:
        raise ValueError("Step/sample time must be > 0")
    return max(1, int(round(duration / dt)))


def sample_segment(seg: dict) -> list[tuple[float, float]]:
    k = seg["type"]
    if k == "Constant":
        return [(seg["value"], seg["duration"])]

    if k == "Ramp":
        n = _n(seg["duration"], seg["dt"])
        dt = seg["duration"] / n
        if n == 1:
            return [(seg["end"], seg["duration"])]
        return [(seg["start"] + (seg["end"] - seg["start"]) * i / (n - 1), dt)
                for i in range(n)]

    if k == "Sine":
        n = _n(seg["duration"], seg["dt"])
        dt = seg["duration"] / n
        ph = math.radians(seg["phase"])
        return [(seg["offset"] + seg["amplitude"]
                 * math.sin(2 * math.pi * seg["freq"] * i * dt + ph), dt)
                for i in range(n)]

    if k == "Table":
        out = []
        for v, t in seg.get("points", []):
            if t <= 0:
                raise ValueError("Table hold times must be > 0")
            out.append((float(v), float(t)))
        return out

    if k == "Combine":
        dur = segment_duration(seg)
        if dur <= 0:
            raise ValueError("Combined signal has zero duration")
        n = _n(dur, seg["dt"])
        dt = dur / n
        return [(value_at(seg, i * dt), dt) for i in range(n)]

    if k == "Square":
        t_high = seg["period"] * seg["duty"] / 100.0
        t_low = seg["period"] - t_high
        out = []
        for _ in range(int(seg["cycles"])):
            if t_high > 0:
                out.append((seg["high"], t_high))
            if t_low > 0:
                out.append((seg["low"], t_low))
        return out

    if k == "Triangle":
        half = seg["period"] / 2.0
        n = _n(half, seg["dt"])
        dt = half / n
        lo, hi = seg["low"], seg["high"]
        up = [lo + (hi - lo) * i / n for i in range(n)]
        down = [hi - (hi - lo) * i / n for i in range(n)]
        return [(v, dt) for _ in range(int(seg["cycles"])) for v in up + down]

    raise ValueError(f"Unknown segment type {k}")


# --------------------------------------------------------------------------
# Sequence settings + compilation
# --------------------------------------------------------------------------
@dataclass
class SequenceSettings:
    name: str = "SEQ1"
    channel: str = "SV"            # "SV" (voltage), "SC" (current), "SP" (power)
    limit_voltage: float = 50.0    # applied when channel != SV
    limit_current: float = 10.0    # applied when channel != SC
    vmax: float = 70.0             # model limits, used for validation only
    cmax: float = 450.0
    pmax: float = 15000.0
    repeat: int = 1                # 0 = infinite loop
    final_value_enabled: bool = True
    final_value: float = 0.0
    decimals: int = 3
    merge_equal: bool = True
    nonvolatile: bool = False
    clear_before_upload: bool = True
    run_after_upload: bool = False
    segments: list[dict] = field(default_factory=list)

    # ---- persistence -----------------------------------------------------
    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> "SequenceSettings":
        data = json.loads(text)
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class CompiledSequence:
    steps: list[str]
    labels: dict[str, int]
    points: list[tuple[float, float]]   # (value, hold) for one pass
    duration_one_pass: float
    warnings: list[str]
    errors: list[str]


def _fmt(x: float, decimals: int) -> str:
    s = f"{x:.{decimals}f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def compile_sequence(cfg: SequenceSettings) -> CompiledSequence:
    warnings: list[str] = []
    errors: list[str] = []

    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,15}", cfg.name or ""):
        errors.append("Name must start with a letter and be max 16 characters "
                      "(letters, digits, _).")
    if not cfg.segments:
        errors.append("Add at least one segment.")

    # 1. sample all segments
    pts: list[tuple[float, float]] = []
    for i, seg in enumerate(cfg.segments, 1):
        try:
            pts.extend(sample_segment(seg))
        except (ValueError, ZeroDivisionError, KeyError) as e:
            errors.append(f"Segment {i}: {e}")

    # 2. round, clamp wait times, merge equal neighbours
    clean: list[tuple[float, float]] = []
    short = 0
    for v, t in pts:
        v = round(v, cfg.decimals)
        t = round(t, 3)
        if t < MIN_WAIT:
            short += 1
            t = MIN_WAIT
        if cfg.merge_equal and clean and clean[-1][0] == v:
            clean[-1] = (v, clean[-1][1] + t)
        else:
            clean.append((v, t))
    if short:
        warnings.append(f"{short} point(s) shorter than 1 ms were raised to 1 ms.")

    points = clean

    # 3. range checks
    vmax = {"SV": cfg.vmax, "SC": cfg.cmax, "SP": cfg.pmax}[cfg.channel]
    lo = min((v for v, _ in points), default=0)
    hi = max((v for v, _ in points), default=0)
    if lo < 0:
        errors.append(f"Negative {cfg.channel} values ({lo:g}) are not allowed "
                      f"(use SCN/SPN for sink mode).")
    if hi > vmax:
        errors.append(f"{cfg.channel} value {hi:g} exceeds model max {vmax:g}.")

    # 4. build steps
    steps: list[str] = []
    labels: dict[str, int] = {}
    d = cfg.decimals
    if cfg.channel != "SV":
        steps.append(f"SV={_fmt(cfg.limit_voltage, d)}")
    if cfg.channel != "SC":
        steps.append(f"SC={_fmt(cfg.limit_current, d)}")
    if cfg.repeat > 1:
        steps.append("#A=0")

    loop_start = len(steps) + 1
    for v, t in points:
        steps.append(f"{cfg.channel}={_fmt(v, d)}")
        while t > MAX_WAIT:
            steps.append(f"W={_fmt(MAX_WAIT, 3)}")
            t -= MAX_WAIT
        steps.append(f"W={_fmt(t, 3)}")

    if cfg.repeat == 0:
        labels["LOOP"] = loop_start
        steps.append("JP LOOP")
    elif cfg.repeat > 1:
        if cfg.repeat > 65535:
            errors.append("Repeat count max is 65535.")
        steps.append("INC #A,1")
        steps.append(f"CJL #A,{cfg.repeat},{loop_start}")

    if cfg.final_value_enabled and cfg.repeat != 0:
        steps.append(f"{cfg.channel}={_fmt(cfg.final_value, d)}")
    steps.append("END")

    if len(steps) > MAX_STEPS:
        errors.append(f"{len(steps)} steps – the sequencer holds max {MAX_STEPS}. "
                      f"Increase step/sample times or shorten the signal.")
    elif len(steps) > 0.9 * MAX_STEPS:
        warnings.append(f"{len(steps)} of {MAX_STEPS} steps used.")

    return CompiledSequence(
        steps=steps, labels=labels, points=points,
        duration_one_pass=sum(t for _, t in points),
        warnings=warnings, errors=errors)


# --------------------------------------------------------------------------
# Text output
# --------------------------------------------------------------------------
def to_scpi_lines(cfg: SequenceSettings, comp: CompiledSequence) -> list[str]:
    """Commands to send over TCP to upload (and optionally run) the sequence."""
    out = [f"PROG:SEL:NAM {cfg.name}"]
    if cfg.clear_before_upload:
        out += ["PROG:SEL:DEL", f"PROG:SEL:NAM {cfg.name}"]
    for i, s in enumerate(comp.steps, 1):
        out.append(f"PROG:SEL:STE {i} {s}")
    for lbl, step in comp.labels.items():
        out.append(f"PROG:SEL:LAB {lbl},{step}")
    if cfg.nonvolatile:
        out += ["PROG:SEL:NON", "PROG:SAV"]
    if cfg.run_after_upload:
        out.append("PROG:SEL:STA RUN")
    return out


def to_text(cfg: SequenceSettings, comp: CompiledSequence, fmt: str = "scpi") -> str:
    header = [
        f"# Delta Elektronika sequence '{cfg.name}'",
        f"# channel={cfg.channel} steps={len(comp.steps)} "
        f"one_pass={comp.duration_one_pass:.3f}s "
        f"repeat={'infinite' if cfg.repeat == 0 else cfg.repeat}",
    ]
    if fmt == "steps":
        body = [f"{i} {s}" for i, s in enumerate(comp.steps, 1)]
        body += [f"# label {k} = step {v}" for k, v in comp.labels.items()]
    else:
        body = to_scpi_lines(cfg, comp)
    return "\n".join(header + body) + "\n"


# --------------------------------------------------------------------------
# Upload over Ethernet
# --------------------------------------------------------------------------
def upload(host: str, port: int, lines: list[str], delay: float = 0.01,
           timeout: float = 3.0, log=print) -> None:
    with socket.create_connection((host, port), timeout=timeout) as s:
        for line in lines:
            if not line or line.startswith("#"):
                continue
            s.sendall((line + "\n").encode("ascii"))
            time.sleep(delay)
        s.sendall(b"PROG:SEL:STA?\n")
        try:
            log("Sequencer state: " + s.recv(256).decode(errors="replace").strip())
        except socket.timeout:
            log("No reply to PROG:SEL:STA? (upload sent anyway).")


# ==========================================================================
# Reading existing sequence files + simulation
# ==========================================================================
STEP_EXEC_TIME = 125e-6          # approx. execution time of one step

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_RE_STE = re.compile(r"^PROG(?:RAM)?:SEL(?:ECTED)?:STE(?:P)?\s+(\d+)\s+(.+)$", re.I)
_RE_NAM = re.compile(r"^PROG(?:RAM)?:SEL(?:ECTED)?:NAME?\s+(\S+)", re.I)
_RE_LAB = re.compile(r"^PROG(?:RAM)?:SEL(?:ECTED)?:LAB(?:EL)?\s+([^,\s]+)\s*,\s*(\S+)", re.I)
_RE_LAB_COMMENT = re.compile(r"^#\s*label\s+(\S+)\s*=\s*step\s+(\d+)", re.I)
_RE_NUMBERED = re.compile(r"^(\d+)\s*[:.)]?\s+(.+)$")
_RE_BARE = re.compile(
    r"^(SCN|SPN|SV|SC|SP|W|#[A-J]|O[A-H]\d|JP|JS|RET|CJNE|CJE|CJG|CJL|INC|DEC|NOP|TRG|END)\b",
    re.I)


@dataclass
class ParsedSequence:
    name: str
    steps: dict[int, str]              # step number -> command (upper case)
    labels: dict[str, int]
    warnings: list[str]


def _strip_comment(line: str) -> str:
    for mark in ("//", ";"):
        if mark in line:
            line = line.split(mark, 1)[0]
    return line.strip()


def parse_sequence_text(text: str) -> ParsedSequence:
    """Accepts SCPI upload files (PROG:SEL:STE n cmd), numbered step lists
    ('n cmd') or bare command lists (one step per line)."""
    name, steps, labels, warnings = "IMPORTED", {}, {}, []
    bare: list[str] = []
    for ln, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        m = _RE_LAB_COMMENT.match(line)
        if m:
            labels[m.group(1).upper()] = int(m.group(2)); continue
        if line.startswith("#") and (len(line) == 1 or line[1] in " \t#"):
            continue                                  # comment, not '#A=0'
        line = _strip_comment(line)
        if not line:
            continue
        if m := _RE_STE.match(line):
            n, cmd = int(m.group(1)), m.group(2)
            if n in steps:
                warnings.append(f"Line {ln}: step {n} defined twice, last one wins.")
            steps[n] = cmd.strip().upper(); continue
        if m := _RE_NAM.match(line):
            name = m.group(1); continue
        if m := _RE_LAB.match(line):
            lbl, val = m.group(1).upper(), m.group(2)
            if val.upper() == "DELETE":
                labels.pop(lbl, None)
            elif val.isdigit():
                labels[lbl] = int(val)
            continue
        if line.upper().startswith(("PROG", "*", "SYST", "OUTP", "SOUR", "TRIG")):
            continue                                  # other remote commands
        if m := _RE_NUMBERED.match(line):
            if _RE_BARE.match(m.group(2).strip()):
                steps[int(m.group(1))] = m.group(2).strip().upper(); continue
        if _RE_BARE.match(line):
            bare.append(line.upper()); continue
        warnings.append(f"Line {ln}: not understood, ignored: {raw.strip()}")

    if bare and not steps:
        steps = {i: c for i, c in enumerate(bare, 1)}
    elif bare:
        warnings.append(f"{len(bare)} un-numbered command line(s) ignored "
                        f"(file also contains numbered steps).")
    if not steps:
        warnings.append("No sequencer steps found in file.")
    return ParsedSequence(name, dict(sorted(steps.items())), labels, warnings)


@dataclass
class SimResult:
    traces: dict[str, list[tuple[float, float]]]  # channel -> [(t, value)]
    end_time: float
    executed: int
    stop_reason: str
    warnings: list[str]
    errors: list[str]


def simulate(seq: ParsedSequence, max_time: float = 600.0,
             max_exec: int = 500_000, inputs: dict[str, int] | None = None,
             step_time: float = STEP_EXEC_TIME) -> SimResult:
    inputs = {k.upper(): v for k, v in (inputs or {}).items()}
    order = list(seq.steps)
    index = {n: i for i, n in enumerate(order)}
    state = {"SV": 0.0, "SC": 0.0, "SP": 0.0, "SCN": 0.0, "SPN": 0.0}
    var = {c: 0 for c in "ABCDEFGH"}
    timers = {"I": (0, 0.0), "J": (0, 0.0)}           # value, set-time
    tick = {"I": 0.001, "J": 0.1}
    outputs: dict[str, int] = {}
    traces: dict[str, list[tuple[float, float]]] = {}
    used: set[str] = set()
    warnings: list[str] = []
    errors: list[str] = []
    warned: set[str] = set()
    stack: list[int] = []
    t, executed, pc = 0.0, 0, 0

    def warn_once(key, msg):
        if key not in warned:
            warned.add(key); warnings.append(msg)

    def record(ch, v):
        traces.setdefault(ch, [])
        if traces[ch] and traces[ch][-1][0] == t:
            traces[ch][-1] = (t, v)
        else:
            traces[ch].append((t, v))

    for ch in state:                                   # start at 0
        traces[ch] = [(0.0, 0.0)]

    def timer_val(c):
        v, t0 = timers[c]
        return max(0, v - int((t - t0) / tick[c] + 1e-9))

    def get(op: str) -> float:
        op = op.strip().upper()
        if op in state:
            return state[op]
        if op in ("MV", "MC", "MP", "MCN", "MPN"):
            warn_once("meas", "Measured values (MV/MC/MP) are assumed equal "
                              "to the set values in the simulation.")
            return state[{"MV": "SV", "MC": "SC", "MP": "SP",
                          "MCN": "SCN", "MPN": "SPN"}[op]]
        if re.fullmatch(r"#[A-H]", op):
            return var[op[1]]
        if op in ("#I", "#J"):
            return timer_val(op[1])
        if re.fullmatch(r"I[A-H]\d", op):
            if op not in inputs:
                warn_once("in" + op, f"Digital input {op} assumed 0 "
                                     f"(set it in the simulation options).")
            return inputs.get(op, 0)
        if re.fullmatch(r"O[A-H]\d", op):
            return outputs.get(op, 0)
        try:
            return float(op)
        except ValueError:
            raise ValueError(f"unknown operand '{op}'")

    def target(tok: str, here: int) -> int:
        tok = tok.strip().upper()
        n = int(tok) if tok.isdigit() else seq.labels.get(tok)
        if n is None:
            raise ValueError(f"step {here}: unknown label '{tok}'")
        if n not in index:
            raise ValueError(f"step {here}: jump to non-existing step {n}")
        return index[n]

    def set_value(op: str, v: float):
        op = op.upper()
        if op in state:
            state[op] = v; record(op, v); used.add(op)
        elif re.fullmatch(r"#[A-H]", op):
            var[op[1]] = int(v) & 0xFFFF
        elif op in ("#I", "#J"):
            timers[op[1]] = (max(0, int(v)), t)
        elif re.fullmatch(r"O[A-H]\d", op):
            outputs[op] = 1 if v else 0
            record(op, outputs[op]); used.add(op)
        else:
            raise ValueError(f"cannot assign to '{op}'")

    stop = "Sequence is empty." if not order else ""
    while order and not stop:
        if pc >= len(order):
            stop = "Ran past the last step (no END)."; break
        if executed >= max_exec:
            stop = (f"Stopped after {executed} executed steps without reaching "
                    f"END – probably waiting on an input or timer at step "
                    f"{order[pc]}."); break
        if t >= max_time:
            stop = (f"Stopped at the simulation limit of {max_time:g} s "
                    f"(sequence loops / still running)."); break
        n = order[pc]
        cmd = seq.steps[n]
        executed += 1
        t += step_time
        nxt = pc + 1
        try:
            if m := re.fullmatch(r"(SCN|SPN|SV|SC|SP|#[A-J]|O[A-H]\d)\s*=\s*(\S+)", cmd):
                op, val = m.groups()
                if val in ("ON", "TRUE"): val = "1"
                if val in ("OFF", "FALSE"): val = "0"
                set_value(op, float(val))
            elif m := re.fullmatch(rf"W\s*=\s*({_NUM})", cmd):
                w = float(m.group(1))
                if not MIN_WAIT <= w <= MAX_WAIT:
                    warn_once(f"w{n}", f"Step {n}: wait {w:g} s outside "
                                       f"0.001..65535 s.")
                t += w
            elif m := re.fullmatch(r"(JP|JS)\s+(\S+)", cmd):
                if m.group(1) == "JS":
                    if len(stack) >= 6:
                        raise ValueError(f"step {n}: more than 6 nested JS")
                    stack.append(nxt)
                nxt = target(m.group(2), n)
            elif cmd == "RET":
                if not stack:
                    raise ValueError(f"step {n}: RET without JS")
                nxt = stack.pop()
            elif m := re.fullmatch(r"(CJE|CJNE|CJG|CJL)\s+([^,]+),([^,]+),(.+)", cmd):
                kind, a, b, tgt = m.groups()
                va, vb = get(a), get(b)
                ok = {"CJE": va == vb, "CJNE": va != vb,
                      "CJG": va > vb, "CJL": va < vb}[kind]
                if ok:
                    nxt = target(tgt, n)
            elif m := re.fullmatch(r"(INC|DEC)\s+([^,]+),\s*(\S+)", cmd):
                kind, op, d = m.groups()
                d = float(d) * (1 if kind == "INC" else -1)
                cur = get(op)
                new = cur + d
                if op.strip() in ("SV", "SC", "SP"):
                    new = max(0.0, new)
                set_value(op.strip(), new)
            elif cmd == "NOP":
                pass
            elif cmd == "TRG":
                warn_once("trg", f"Step {n}: TRG (wait for trigger) treated as "
                                 f"triggered immediately.")
            elif cmd == "END":
                stop = f"END reached at step {n}."
            else:
                warn_once(f"u{n}", f"Step {n}: '{cmd}' not understood, "
                                   f"treated as NOP.")
        except ValueError as e:
            errors.append(str(e)); stop = f"Simulation error: {e}"; break
        pc = nxt

    # keep only channels that were actually used (but always SV/SC)
    traces = {k: v for k, v in traces.items() if k in used or k in ("SV", "SC")}
    if "END" not in seq.steps.values():
        warnings.append("Sequence has no END step.")
    return SimResult(traces, t, executed, stop, seq.warnings + warnings, errors)


def trace_to_points(trace: list[tuple[float, float]], end_time: float,
                    decimals: int = 3) -> list[list[float]]:
    """Convert a simulated trace into [value, hold] pairs (for a Table segment)."""
    pts: list[list[float]] = []
    for i, (t0, v) in enumerate(trace):
        t1 = trace[i + 1][0] if i + 1 < len(trace) else end_time
        hold = round(t1 - t0, 3)
        if hold < MIN_WAIT:
            continue
        v = round(v, decimals)
        if pts and pts[-1][0] == v:
            pts[-1][1] = round(pts[-1][1] + hold, 3)
        else:
            pts.append([v, hold])
    return pts


# ==========================================================================
# Importing measured samples (timestamp / value) from CSV, TXT or Excel
# ==========================================================================
TIME_UNITS = {"µs": 1e-6, "ms": 1e-3, "s": 1.0, "min": 60.0, "h": 3600.0,
              "hh:mm:ss / date-time": None}


def read_table_file(path: str) -> list[list[str]]:
    """Return the raw cells of a CSV/TXT/TSV or Excel file as strings."""
    low = path.lower()
    if low.endswith((".xlsx", ".xlsm")):
        try:
            import openpyxl
        except ImportError:
            raise ValueError("Reading Excel needs 'openpyxl' (pip install openpyxl).")
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = [["" if c is None else str(c) for c in r]
                for r in ws.iter_rows(values_only=True)]
        wb.close()
        return [r for r in rows if any(x.strip() for x in r)]

    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        lines = [ln.rstrip("\r\n") for ln in fh if ln.strip()]
    lines = [ln for ln in lines if not ln.lstrip().startswith(("#", "//"))]
    sample = lines[:50]
    # choose delimiter: the one that gives a consistent column count > 1
    best, best_score = None, 0
    for d in ("\t", ";", ",", "|"):
        counts = [len(ln.split(d)) for ln in sample]
        if counts and min(counts) > 1:
            score = sum(1 for c in counts if c == counts[-1])
            if score > best_score:
                best, best_score = d, score
    if best is None:
        return [ln.split() for ln in lines]          # whitespace separated
    rows = [[c.strip().strip('"') for c in ln.split(best)] for ln in lines]
    if best == ";":                                  # European decimal comma
        rows = [[c.replace(",", ".") if re.fullmatch(r"[-+]?\d+,\d+", c) else c
                 for c in r] for r in rows]
    return rows


def _to_float(s: str) -> float | None:
    try:
        return float(str(s).strip().replace(",", ".") if re.fullmatch(
            r"\s*[-+]?\d+,\d+\s*", str(s)) else s)
    except (TypeError, ValueError):
        return None


def _parse_clock(s: str) -> float | None:
    """'12:03:04.5', '03:04', '2026-11-19 12:03:04.500' -> seconds."""
    from datetime import datetime
    s = str(s).strip()
    try:
        return datetime.fromisoformat(s.replace("/", "-")).timestamp()
    except ValueError:
        pass
    m = re.fullmatch(r"(?:(\d+):)?(\d+):(\d+(?:[.,]\d+)?)", s)
    if m:
        h, mi, sec = m.groups()
        return int(h or 0) * 3600 + int(mi) * 60 + float(sec.replace(",", "."))
    return None


def detect_header(rows: list[list[str]]) -> bool:
    if not rows:
        return False
    first = rows[0]
    return not any(_to_float(c) is not None or _parse_clock(c) is not None
                   for c in first if c.strip())


def extract_samples(rows: list[list[str]], tcol: int, vcol: int, unit: str,
                    has_header: bool) -> tuple[list[tuple[float, float]], int]:
    """Return ([(t_seconds, value)], skipped_row_count)."""
    out, skipped = [], 0
    factor = TIME_UNITS[unit]
    for r in rows[1 if has_header else 0:]:
        if max(tcol, vcol) >= len(r):
            skipped += 1; continue
        v = _to_float(r[vcol])
        t = _parse_clock(r[tcol]) if factor is None else _to_float(r[tcol])
        if t is None or v is None:
            skipped += 1; continue
        out.append((t if factor is None else t * factor, v))
    return out, skipped


@dataclass
class SampleImportOptions:
    time_is_duration: bool = False   # False: timestamps, True: hold time per sample
    zero_start: bool = True          # shift first timestamp to t = 0
    continuous: bool = False         # False: step/hold, True: linear interpolation
    resample_dt: float = 0.1         # s, used when continuous
    last_hold: float = 1.0           # s, hold time of the last sample
    min_hold: float = 0.001          # s, shorter steps are merged (step mode)
    scale: float = 1.0
    offset: float = 0.0
    decimals: int = 3


def samples_to_points(samples: list[tuple[float, float]],
                      o: SampleImportOptions) -> tuple[list[list[float]], list[str]]:
    """Turn (time, value) samples into [value, hold] points for a Table segment."""
    warn: list[str] = []
    if not samples:
        return [], ["No numeric samples found."]

    # durations -> timestamps
    if o.time_is_duration:
        ts, acc = [], 0.0
        for d, v in samples:
            ts.append((acc, v)); acc += d
        samples, end_t = ts, acc
    else:
        if any(b[0] < a[0] for a, b in zip(samples, samples[1:])):
            warn.append("Timestamps were not in order – samples sorted by time.")
            samples = sorted(samples, key=lambda x: x[0])
        dup = sum(1 for a, b in zip(samples, samples[1:]) if a[0] == b[0])
        if dup:
            warn.append(f"{dup} duplicate timestamp(s) – the later value is used.")
            dedup = {}
            for t, v in samples:
                dedup[t] = v
            samples = sorted(dedup.items())
        end_t = samples[-1][0] + o.last_hold

    samples = [(t, v * o.scale + o.offset) for t, v in samples]
    t0 = samples[0][0]
    lead = []
    if o.zero_start:
        samples = [(t - t0, v) for t, v in samples]
        end_t -= t0
    elif t0 > 0:
        lead = [[0.0, t0]]                     # output 0 until the first sample
        warn.append(f"Output is 0 for the first {t0:g} s (before the first sample).")
    elif t0 < 0:
        warn.append("Negative timestamps – enable 'start at 0'.")
        samples = [(t - t0, v) for t, v in samples]; end_t -= t0

    pts: list[list[float]] = []
    if o.continuous and len(samples) > 1:
        if o.resample_dt < MIN_WAIT:
            raise ValueError("Resample step must be at least 1 ms.")
        last_t = samples[-1][0]
        n = max(1, int(math.ceil((last_t - samples[0][0]) / o.resample_dt - 1e-9)))
        j = 0
        for k in range(n):
            t = samples[0][0] + k * o.resample_dt
            while j < len(samples) - 2 and samples[j + 1][0] <= t:
                j += 1
            (ta, va), (tb, vb) = samples[j], samples[j + 1]
            v = va if tb == ta else va + (vb - va) * (t - ta) / (tb - ta)
            hold = min(o.resample_dt, last_t - t)
            pts.append([v, hold])
        tail = end_t - last_t
        pts.append([samples[-1][1], tail if tail > 0 else MIN_WAIT])
    else:
        for i, (t, v) in enumerate(samples):
            t_next = samples[i + 1][0] if i + 1 < len(samples) else end_t
            pts.append([v, t_next - t])
        if pts[-1][1] <= 0:
            pts[-1][1] = MIN_WAIT

    # round, merge short steps and equal neighbours
    merged: list[list[float]] = []
    short = 0
    pending_extra = 0.0
    for v, h in lead + pts:
        v = round(v, o.decimals)
        if h < o.min_hold and not o.continuous:
            short += 1
            if merged:
                merged[-1][1] += h        # absorb into previous step
            else:
                pending_extra += h
            continue
        h += pending_extra; pending_extra = 0.0
        if merged and merged[-1][0] == v:
            merged[-1][1] += h
        else:
            merged.append([v, h])
    if pending_extra and merged:
        merged[0][1] += pending_extra
    for p in merged:
        p[1] = max(MIN_WAIT, round(p[1], 3))
    if short:
        warn.append(f"{short} sample(s) shorter than the minimum hold "
                    f"({o.min_hold * 1000:g} ms) were merged into the previous step.")
    return merged, warn
