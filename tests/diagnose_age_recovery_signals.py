import errno, os, signal, subprocess, sys, time

def probe(pg, signum=0):
    try:
        os.killpg(pg, signum)
    except OSError as error:
        return errno.errorcode[error.errno]
    return "ok"

# A: only member is our exited, unreaped leader (test 1 at :607)
p = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True)
time.sleep(0.2); probe(p.pid, signal.SIGTERM); time.sleep(0.2)
print("A unreaped", probe(p.pid)); p.wait(); print("A reaped", probe(p.pid))

# B: test 3 order; C: test 2 after the SIGKILL at :636
ORPHAN = "(trap '' TERM; exec /bin/sleep 60) & exec /bin/sleep 60"
tally = {}
for label in ("B", "C"):
    for _ in range(100):
        if label == "B":
            p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                 start_new_session=True)
            events = [("initial", probe(p.pid)), ("sigterm", probe(p.pid, signal.SIGTERM))]
        else:
            p = subprocess.Popen(["/bin/sh", "-c", ORPHAN], start_new_session=True)
            time.sleep(0.2); probe(p.pid, signal.SIGTERM); p.wait()
            events = [("sigkill", probe(p.pid, signal.SIGKILL))]
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            reaped = p.poll() is not None
            state = probe(p.pid)
            events.append((f"loop reaped={reaped}", state))
            if reaped and state == "ESRCH":
                break
            time.sleep(0.02)
        else:
            events.append(("stuck", "timeout"))
        for event in events:
            if event[1] not in ("ok", "ESRCH"):
                tally[(label, *event)] = tally.get((label, *event), 0) + 1
print("tally", tally)
