"""Run pytest and save output to a plain text file."""
import subprocess, sys

result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/", "--tb=long", "-v", "-p", "no:warnings"],
    capture_output=True,
    text=True,
    cwd=r"c:\Users\Dhurka\customer_support_bot",
)
combined = result.stdout + "\n" + result.stderr
with open(r"c:\Users\Dhurka\customer_support_bot\pytest_results.txt", "w", encoding="utf-8") as f:
    f.write(combined)
print("Exit code:", result.returncode)
print(combined[-8000:])
