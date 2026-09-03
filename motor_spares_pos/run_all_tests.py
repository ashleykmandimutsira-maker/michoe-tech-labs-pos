import subprocess
import sys
import os

os.chdir(r"c:\Users\HomePC\Documents\Online Motor Spare Pos System\motor_spares_pos_updated claude\motor_spares_pos")

tests = sys.argv[1:] or ["test_phase1.py", "test_phase2.py", "test_initialization.py", "test_cart.py", "test_security.py"]
results = []
for t in tests:
    r = subprocess.run([sys.executable, t], capture_output=True, text=True)
    tail = (r.stdout or "").strip().splitlines()[-6:]
    err_tail = (r.stderr or "").strip().splitlines()[-3:]
    results.append((t, r.returncode))
    print("=" * 70)
    print(f"TEST {t}  EXIT={r.returncode} {'PASS' if r.returncode==0 else 'FAIL'}")
    print("-" * 70)
    for line in tail:
        print("OUT:", line)
    for line in err_tail:
        print("ERR:", line)

print("=" * 70)
for t, code in results:
    print(f"{'PASS' if code==0 else 'FAIL'}: {t}")
sys.exit(0 if all(c == 0 for _, c in results) else 1)