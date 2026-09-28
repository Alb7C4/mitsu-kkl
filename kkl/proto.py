"""Probe strategies for K-line ECUs: MUT-II (5-baud init, 15625), ISO 9141-2 /
KWP2000 slow init (0x33), KWP2000 fast init, DSM-style 1953 baud, passive listen.

Every strategy returns a dict with an `outcome` (see RANKS) and a one-line
`summary`; the raw byte timeline stays in the run's event log."""

from .link import now

RANKS = ["ERROR", "NO_ECHO", "SILENT", "NOISE", "SYNC", "HANDSHAKE", "DATA"]


def rank(outcome):
    return RANKS.index(outcome) if outcome in RANKS else 0


class SafetyError(RuntimeError):
    pass


# ------------------------------------------------------------------ safety ---
# MUT: 0x00-0xBF are RAM/sensor reads, 0xFD-0xFF ID reads. 0xC0-0xFC is never
# sent: on MUT-II ECUs 0xCA clears DTCs and 0xF1-0xFC fire actuators / cut injectors.
MUT_ALLOWED = frozenset(range(0x00, 0xC0)) | {0xFD, 0xFE, 0xFF}
# OBD / KWP: read-only services only (mode 04 / 0x14 clear-DTC is never sent).
OBD_ALLOWED = frozenset({0x01, 0x02, 0x03, 0x07, 0x09})
KWP_ALLOWED = OBD_ALLOWED | {0x81, 0x82, 0x3E, 0x1A}


def check_mut(cmd):
    if cmd not in MUT_ALLOWED:
        raise SafetyError(f"MUT request 0x{cmd:02X} blocked (0xC0-0xFC can clear DTCs or drive actuators)")


def check_service(sid):
    if sid not in KWP_ALLOWED:
        raise SafetyError(f"service 0x{sid:02X} blocked (read-only services only)")


ENGINE_ADDRS = (0x00, 0x01)
MUT_ENGINE_QUERIES = (0xFE, 0xFF, 0x14, 0x07, 0x21, 0x17, 0x15)
MUT_ID_QUERIES = (0xFE, 0xFF)
DSM_QUERIES = (0x14, 0x07, 0x21, 0x17, 0x15)

MUT_DECODE = {
    0x14: ("batt", lambda v: f"{v * 0.0733:.1f}V"),
    0x21: ("rpm", lambda v: f"{v * 31.25:.0f}"),
    0x07: ("clt", lambda v: f"raw{v}"),
    0x17: ("tps", lambda v: f"{v * 100 / 255:.0f}%"),
    0x15: ("baro", lambda v: f"{v * 0.49:.0f}kPa"),
    0xFE: ("id_hi", lambda v: f"{v:02X}"),
    0xFF: ("id_lo", lambda v: f"{v:02X}"),
}


def _hex(pairs):
    return " ".join(f"{b:02X}" for _, b in pairs) or "-"


def _ms(dt):
    return round(dt * 1000, 1)


def _clip(s, n=36):
    return s if len(s) <= n else s[:n - 3] + "..."


# ------------------------------------------------------------ 5-baud init ---
def _slow_init(kl, addr, baud, method, lline, bit_ms, idle_ms, sync_timeout, keep_open):
    """5-baud init + capture of the ECU's answer. With keep_open the capture stops
    right after KB2 so the caller can still answer ~KB2 inside W4."""
    kl.set_baud(baud)
    kl.discard()
    kl.reset_line_stats()
    i0 = len(kl.buf)
    init = kl.five_baud(addr, bit_ms / 1000, idle_ms / 1000, method, lline)
    i1 = len(kl.buf)
    kl.reset_line_stats()  # our own break sets BI; count only what arrives after the init

    def have_kb():
        bs = [b for _, b in kl.buf[i1:]]
        return 0x55 in bs and len(bs) - bs.index(0x55) >= 3

    kl.wait_for(have_kb, sync_timeout)
    if not (keep_open and have_kb()):
        kl.sleep(0.1)  # let trailing bytes arrive
    post = kl.buf[i1:]
    kl.pos = len(kl.buf)

    res = {"loopback": len(kl.buf[i0:i1]) if method != "bitbang" else "".join(map(str, init["readback"])),
           "edges_ms": init["edges_ms"], "post": _hex(post)}
    sync = None
    bs = [b for _, b in post]
    if 0x55 in bs:
        k = bs.index(0x55)
        sync = {"pre": _hex(post[:k]), "w1_ms": _ms(post[k][0] - init["t_stop_end"])}
        if len(bs) >= k + 3:
            sync.update(kb=f"{bs[k + 1]:02X} {bs[k + 2]:02X}", kb1=bs[k + 1], kb2=bs[k + 2],
                        t_kb2=post[k + 2][0])
    return res, post, sync


def _ack(kl, t_kb2, kb2, w4=0.030):
    """Answer ~KB2 after W4 (25-50 ms) and read the ECU's ~address."""
    kl.wait_until(t_kb2 + w4)
    inv = (~kb2) & 0xFF
    echo_ok, _ = kl.send([inv])
    r = kl.read_n(1, 0.3)
    return {"sent": f"{inv:02X}", "echo": echo_ok, "reply": f"{r[0][1]:02X}" if r else None}


def _base_outcome(res, post, sync, kl):
    res["line"] = dict(kl.ls_counts)
    if sync:
        res["sync"] = {k: v for k, v in sync.items() if k not in ("kb1", "kb2", "t_kb2")}
        return "HANDSHAKE" if "kb" in sync else "SYNC"
    return "NOISE" if post or kl.ls_counts else "SILENT"


# ------------------------------------------------------------------ MUT-II ---
def mut_query(kl, cmd, timeout=0.3):
    check_mut(cmd)
    echo_ok, t_tx = kl.send([cmd])
    resp = kl.read_until_idle(0.03, timeout)
    q = {"cmd": f"{cmd:02X}", "echo": echo_ok, "resp": _hex(resp)}
    if resp:
        q["lat_ms"] = _ms(resp[0][0] - t_tx)
        if len(resp) == 1 and cmd in MUT_DECODE:
            q["val"] = MUT_DECODE[cmd][1](resp[0][1])
    return q


def _queries_ok(qs):
    good = [q for q in qs if q["echo"] and len(q["resp"].split()) == 1 and q["resp"] != "-"]
    return len(good) >= min(2, len(qs))


def _query_summary(qs):
    parts = []
    for q in qs:
        c = int(q["cmd"], 16)
        name = MUT_DECODE[c][0] if c in MUT_DECODE else q["cmd"]
        parts.append(f"{name}={q.get('val', q['resp'])}")
    return " ".join(parts)


def mut(kl, log, addr=0x00, baud=15625, ack=False, queries=None, method="break", lline=None,
        bit_ms=200, idle_ms=300, sync_timeout=1.2, always_query=False, repeat=0, interval=0.0):
    """MUT-II: 5-baud address, then 1-byte requests answered with echo + 1 byte."""
    if queries is None:
        queries = MUT_ENGINE_QUERIES if addr in ENGINE_ADDRS else MUT_ID_QUERIES
    for q in queries:
        check_mut(q)
    # A session left open by an earlier attempt would answer without any init
    # and make this attempt look successful - detect that first.
    kl.set_baud(baud)
    alive = mut_query(kl, 0xFE, timeout=0.15)
    res, post, sync = _slow_init(kl, addr, baud, method, lline, bit_ms, idle_ms, sync_timeout, ack)
    res["alive_before"] = alive["resp"]
    outcome = _base_outcome(res, post, sync, kl)
    summary = ["ALIVE-BEFORE"] if alive["resp"] != "-" else []
    summary.append(f"lb={res['loopback']} post={_clip(res['post'])}")
    if sync and "kb" in sync and ack:
        res["ack"] = _ack(kl, sync["t_kb2"], sync["kb2"])
        summary.append(f"ack->{res['ack']['reply']}")
    if queries and (sync or post or always_query):
        kl.sleep(0.02)
        res["queries"] = [mut_query(kl, q) for q in queries]
        if outcome == "SILENT" and not any(q["echo"] for q in res["queries"]):
            outcome = "NO_ECHO"
        # Answers without a 0x55 at this baud are usually a session running at
        # another speed decoded as garbage - don't call that DATA.
        if _queries_ok(res["queries"]) and not sync:
            summary.append("answers-without-sync: " + _clip(" ".join(q["resp"] for q in res["queries"]), 30))
        elif _queries_ok(res["queries"]):
            outcome = "DATA"
            summary.append(_query_summary(res["queries"]))
            if repeat:
                res["monitor_rows"] = _monitor(kl, log, queries, repeat, interval)
        else:
            summary.append("q:" + _clip(" ".join(q["resp"] for q in res["queries"]), 30))
    res.update(outcome=outcome, summary=" ".join(summary))
    return res


def mutdump(kl, log, addr=0x00, baud=15625, start=0x00, end=0xBF, method="break"):
    """Connect like `mut`, then read every whitelisted request in [start, end] once."""
    cmds = [c for c in range(start, end + 1) if c in MUT_ALLOWED]
    for c in cmds:
        check_mut(c)
    res = mut(kl, log, addr=addr, baud=baud, method=method, queries=MUT_ID_QUERIES)
    if res["outcome"] != "DATA":
        return res
    table = {}
    for c in cmds:
        q = mut_query(kl, c)
        table[q["cmd"]] = q["resp"] if q["echo"] else "echo?"
    res["table"] = table
    answered = [k for k, v in table.items() if len(v.split()) == 1 and v not in ("-", "echo?")]
    res["summary"] += f" | dump {len(answered)}/{len(cmds)} answered"
    for row in range(start & 0xF0, end + 1, 0x10):
        cells = [table.get(f"{c:02X}", "  ") for c in range(row, row + 0x10)]
        print(f"      {row:02X}: " + " ".join(c if len(c) == 2 else "??" for c in cells), flush=True)
    return res


# Engine DTC bytes found on this ECU (E4 3A) by unplugging TPS + coolant sensor:
# 0x40 = active, 0x45 = stored; 0x41 / 0x46 assumed to be the next 8 codes.
DTC_ACTIVE, DTC_STORED = (0x40, 0x41), (0x45, 0x46)
# Bit order guess (standard Mitsubishi code order); bits 3 = 14 TPS and 5 = 21 ECT are confirmed.
DTC_CODES = (11, 12, 13, 14, 15, 21, 22, 23, 24, 25, 31, 32, 36, 39, 41, 42)


def _dtc(kl):
    vals = {}
    for c in DTC_ACTIVE + DTC_STORED:
        q = mut_query(kl, c)
        vals[c] = int(q["resp"], 16) if q["echo"] and len(q["resp"].split()) == 1 and q["resp"] != "-" else None
    return vals


def dtc_text(vals, cmds):
    if any(vals[c] is None for c in cmds):
        return "?"
    word = vals[cmds[0]] | (vals[cmds[1]] << 8)
    bits = [i for i in range(16) if word >> i & 1]
    return f"{vals[cmds[0]]:02X} {vals[cmds[1]]:02X} bits={bits or '-'} codes~{[DTC_CODES[i] for i in bits] or '-'}"


def dtc(kl, log, addr=0x00, baud=15625):
    """Read the engine DTC bytes (read-only)."""
    res = mut(kl, log, addr=addr, baud=baud, queries=MUT_ID_QUERIES)
    if res["outcome"] != "DATA":
        return res
    vals = _dtc(kl)
    res["dtc"] = {f"{k:02X}": v for k, v in vals.items()}
    res["summary"] = (f"id={res['queries'][0]['resp']}{res['queries'][1]['resp']} "
                      f"active: {dtc_text(vals, DTC_ACTIVE)} | stored: {dtc_text(vals, DTC_STORED)}")
    return res


CLEAR_CMD = 0xCA  # MUT "erase DTCs" - only ever sent by mut_clear()


def mut_clear(kl, log, addr=0x00, baud=15625):
    """Erase engine DTCs with MUT 0xCA. Engine ECU only, engine must be stopped."""
    if addr != 0x00:
        raise SafetyError("DTC clear is only allowed for the engine ECU (address 00)")
    res = mut(kl, log, addr=addr, baud=baud, queries=(0xFE, 0xFF, 0x21))
    if res["outcome"] != "DATA":
        res["summary"] = "no session, nothing sent | " + res["summary"]
        return res
    rpm = res["queries"][2]["resp"]
    if rpm != "00":
        res.update(outcome="ERROR", summary=f"RPM byte = {rpm}, engine must be stopped - nothing sent")
        return res
    before = _dtc(kl)
    kl.sleep(0.05)
    log.ev("dtc_clear_send", cmd=f"{CLEAR_CMD:02X}")
    echo_ok, _ = kl.send([CLEAR_CMD])
    reply = kl.read_until_idle(0.05, 1.0)
    kl.sleep(1.0)
    after = _dtc(kl)
    res.update(dtc_before={f"{k:02X}": v for k, v in before.items()},
               dtc_after={f"{k:02X}": v for k, v in after.items()},
               clear_reply=_hex(reply), clear_echo=echo_ok)
    res["summary"] = (f"CA echo={int(echo_ok)} reply={_hex(reply)} | before: active {dtc_text(before, DTC_ACTIVE)}, "
                      f"stored {dtc_text(before, DTC_STORED)} | after: active {dtc_text(after, DTC_ACTIVE)}, "
                      f"stored {dtc_text(after, DTC_STORED)}")
    return res


def _monitor(kl, log, queries, repeat, interval):
    data_q = [q for q in queries if q < 0xFD] or list(queries)
    for _ in range(repeat):
        vals = [mut_query(kl, q) for q in data_q]
        line = _query_summary(vals)
        log.ev("monitor", values=line)
        print("      " + line, flush=True)
        if interval:
            kl.sleep(interval)
    return repeat


# ----------------------------------------------------- ISO 9141-2 / KWP2000 ---
def frame(fr, payload, target=0x33, physical=False):
    check_service(payload[0])
    if fr == "iso9141":
        msg = [0x68, 0x6A, 0xF1] + list(payload)
    else:
        msg = [(0x80 if physical else 0xC0) | len(payload), target, 0xF1] + list(payload)
    return msg + [sum(msg) & 0xFF]


def split_frames(resp, fr):
    """Pull checksum-valid frames out of a response byte stream."""
    bs = [b for _, b in resp]
    out, i = [], 0
    while i < len(bs):
        if fr == "kwp" and bs[i] & 0x80:
            n = bs[i] & 0x3F
            hdr = 3 if n else 4
            if n == 0 and i + 3 < len(bs):
                n = bs[i + 3]
            end = i + hdr + n + 1
            if n and end <= len(bs) and sum(bs[i:end - 1]) & 0xFF == bs[end - 1]:
                out.append(bs[i:end])
                i = end
                continue
        elif fr == "iso9141" and bs[i] == 0x48:
            end = next((e for e in range(i + 5, min(len(bs), i + 11) + 1)
                        if sum(bs[i:e - 1]) & 0xFF == bs[e - 1]), None)
            if end:
                out.append(bs[i:end])
                i = end
                continue
        i += 1
    return out


def _payload(f, fr):
    if fr == "iso9141":
        return f[3:-1]
    return f[3:-1] if f[0] & 0x3F else f[4:-1]


def obd_request(kl, fr, payload, target=0x33, physical=False, p4=0.005):
    msg = frame(fr, payload, target, physical)
    echo_ok, t_tx = kl.send(msg, gap=p4)
    resp = kl.read_until_idle(0.06, 1.5, first_timeout=0.5)
    frames = split_frames(resp, fr)
    r = {"fr": fr, "req": " ".join(f"{b:02X}" for b in msg), "echo": echo_ok, "resp": _hex(resp),
         "frames": [" ".join(f"{b:02X}" for b in f) for f in frames]}
    r["positive"] = any(_payload(f, fr)[:1] == [payload[0] | 0x40] for f in frames)
    if resp:
        r["lat_ms"] = _ms(resp[0][0] - t_tx)
    return r


def iso(kl, log, addr=0x33, baud=10400, method="break", lline=None, bit_ms=200, idle_ms=300,
        sync_timeout=1.2, obd=True):
    """ISO 9141-2 / KWP2000 slow init: 5-baud address, 0x55 KB1 KB2, ~KB2, ~addr."""
    res, post, sync = _slow_init(kl, addr, baud, method, lline, bit_ms, idle_ms, sync_timeout, True)
    outcome = _base_outcome(res, post, sync, kl)
    summary = [f"lb={res['loopback']} post={_clip(res['post'])}"]
    if sync and "kb" in sync:
        kb1, kb2 = sync["kb1"], sync["kb2"]
        res["ack"] = _ack(kl, sync["t_kb2"], kb2)
        proto = "kwp" if kb2 == 0x8F else ("iso9141" if kb1 == kb2 and kb1 in (0x08, 0x94) else "unknown")
        res["proto"] = proto
        summary.append(f"kb={sync['kb']} ({proto}) ack->{res['ack']['reply']}")
        if obd and res["ack"]["reply"] == f"{(~addr) & 0xFF:02X}":
            res["obd"] = []
            for fr in ([proto] if proto != "unknown" else ["iso9141", "kwp"]):
                kl.sleep(0.06)
                r = obd_request(kl, fr, [0x01, 0x00])
                res["obd"].append(r)
                if r["positive"]:
                    outcome = "DATA"
                    for payload in ([0x03], [0x01, 0x05], [0x01, 0x0C], [0x09, 0x00]):
                        kl.sleep(0.06)
                        res["obd"].append(obd_request(kl, fr, payload))
                    summary.append("obd: " + " | ".join(_clip(x["resp"], 30) for x in res["obd"]))
                    break
            else:
                summary.append("0100: " + _clip(res["obd"][-1]["resp"], 24))
    res.update(outcome=outcome, summary=" ".join(summary))
    return res


def kwpfast(kl, log, target=0x33, physical=False, method="byte", baud=10400, idle_ms=300, obd=True):
    """ISO 14230 fast init: 25/25 ms wake-up, then StartCommunication (0x81)."""
    kl.discard()
    kl.reset_line_stats()
    t_go = kl.fast_init(method, idle=idle_ms / 1000, baud=baud)
    kl.wait_until(t_go)
    kl.reset_line_stats()
    msg = frame("kwp", [0x81], target, physical)
    echo_ok, t_tx = kl.send(msg)
    resp = kl.read_until_idle(0.06, 1.0, first_timeout=0.3)
    frames = split_frames(resp, "kwp")
    res = {"req": " ".join(f"{b:02X}" for b in msg), "echo": echo_ok, "resp": _hex(resp),
           "frames": [" ".join(f"{b:02X}" for b in f) for f in frames], "line": dict(kl.ls_counts)}
    positive = [f for f in frames if _payload(f, "kwp")[:1] == [0xC1]]
    if not echo_ok and not resp:
        outcome = "NO_ECHO"
    elif positive:
        outcome = "HANDSHAKE"
    else:
        outcome = "NOISE" if resp or kl.ls_counts else "SILENT"
    summary = [f"resp={_clip(res['resp'])}"]
    if positive:
        p = _payload(positive[0], "kwp")
        res["kb"] = " ".join(f"{b:02X}" for b in p[1:3])
        summary.append(f"kb={res['kb']}")
        if obd:
            kl.sleep(0.06)
            r = obd_request(kl, "kwp", [0x01, 0x00], target, physical)
            res["obd"] = [r]
            if r["positive"]:
                outcome = "DATA"
            summary.append("0100: " + _clip(r["resp"], 24))
        kl.sleep(0.06)
        stop = frame("kwp", [0x82], target, physical)
        kl.send(stop)
        res["stop_resp"] = _hex(kl.read_until_idle(0.06, 0.5, first_timeout=0.2))
    res.update(outcome=outcome, summary=" ".join(summary))
    return res


# ------------------------------------------------------- DSM / passive -------
def dsm(kl, log, baud=1953, queries=DSM_QUERIES, listen=0.3):
    """Early-DSM style: no init, 1-byte requests at 1953 baud (needs diag pin grounded)."""
    for q in queries:
        check_mut(q)
    kl.set_baud(baud)
    kl.discard()
    kl.reset_line_stats()
    kl.sleep(listen)
    pre = kl.take()
    qs = [mut_query(kl, q, timeout=0.4) for q in queries]
    res = {"pre": _hex(pre), "queries": qs, "line": dict(kl.ls_counts)}
    if _queries_ok(qs):
        outcome, summary = "DATA", _query_summary(qs)
    else:
        any_resp = any(q["resp"] != "-" for q in qs)
        echo = any(q["echo"] for q in qs)
        outcome = "NOISE" if any_resp or pre or kl.ls_counts else ("SILENT" if echo else "NO_ECHO")
        summary = "q:" + _clip(" ".join(q["resp"] for q in qs), 30) + f" echo={int(echo)}"
    res.update(outcome=outcome, summary=summary)
    return res


def listen(kl, log, baud=10400, secs=2.0):
    kl.set_baud(baud)
    kl.discard()
    kl.reset_line_stats()
    kl.sleep(secs)
    got = kl.take()
    res = {"rx": _hex(got), "n": len(got), "line": dict(kl.ls_counts)}
    res["outcome"] = "NOISE" if got or kl.ls_counts else "SILENT"
    res["summary"] = f"{len(got)} bytes {_clip(res['rx'], 30)} line={res['line'] or '-'}"
    return res


def quick_echo(kl):
    """One 0x55 at 10400 baud; True if it came back (cable powered from pin 16)."""
    kl.set_baud(10400)
    kl.discard()
    kl.write(b"\x55")
    got = kl.read_until_idle(0.02, 0.2)
    return [b for _, b in got] == [0x55]


def selftest(kl, log):
    """Idle-line check, echo test and break loopback - tells whether the cable
    is powered from the OBD socket (pin 16) and sees its own K-line."""
    res = {}
    kl.set_baud(10400)
    kl.discard()
    kl.reset_line_stats()
    kl.sleep(0.5)
    idle = kl.take()
    res["idle"] = {"rx": _hex(idle), "line": dict(kl.ls_counts)}
    echoes = {}
    for baud in (10400, 15625):
        kl.set_baud(baud)
        kl.discard()
        pattern = bytes([0x55, 0xAA])
        t = kl.write(pattern)
        got = kl.read_until_idle(0.02, 0.3)
        echoes[baud] = {"sent": pattern.hex(" ").upper(), "got": _hex(got),
                        "lat_ms": _ms(got[0][0] - t) if got else None}
    res["echo"] = echoes
    kl.set_baud(10400)
    kl.discard()
    kl.reset_line_stats()
    kl.dev.break_on()
    kl.sleep(0.03)
    kl.dev.break_off()
    kl.sleep(0.05)
    res["break_loopback"] = {"rx": _hex(kl.take()), "line": dict(kl.ls_counts)}
    good = all(e["got"] == e["sent"] for e in echoes.values())
    none = all(e["got"] == "-" for e in echoes.values())
    res["outcome"] = "OK" if good else ("NO_ECHO" if none else "ECHO_BAD")
    res["summary"] = (f"echo10400={echoes[10400]['got']} echo15625={echoes[15625]['got']} "
                      f"idle={_clip(res['idle']['rx'], 16)} brk={res['break_loopback']['rx']}")
    return res
