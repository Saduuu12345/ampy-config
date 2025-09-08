from ampy_config import ConfigRuntime
import time

# Start an in-process runtime
rt = ConfigRuntime(profile="dev")
rt.load()  # initial load

def on_change(cfg):
    print("[service] new config received! oms.risk.max_order_notional_usd =", cfg["oms"]["risk"]["max_order_notional_usd"])

rt.on_change(on_change)
rt.start_background()

print("[service] initial max_order_notional_usd =", rt.get("oms.risk.max_order_notional_usd"))

# Keep the process alive; apply overlays via the CLI in another terminal.
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    rt.stop()
