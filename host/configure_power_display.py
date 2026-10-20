"""2026-10-20: load display-only calibration over existing UART registers."""
import argparse
import json
import math
from pathlib import Path
from llctl import LightLock


def words(fit, channel):
    a,b=fit["slope_code_per_mw"],fit["intercept_code"]
    if not math.isfinite(a) or abs(a)<1e-12 or not math.isfinite(b):
        raise ValueError("Invalid slope/intercept")
    zero=round(b*65536)
    gain=round(10000/a*2**20)
    if not -(2**31)<=zero<2**31 or not -(2**31)<=gain<2**31:
        raise ValueError("Calibration exceeds fixed-point range")
    low=math.floor(fit["code_min"]);high=math.ceil(fit["code_max"])
    if not 0<=low<high<=16383:
        raise ValueError("Invalid calibration ADC range")
    return [1 | (channel<<1),zero&65535,(zero>>16)&65535,
            gain&65535,(gain>>16)&65535,low,high]


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port",required=True)
    ap.add_argument("--fit",type=Path,default=Path(__file__).resolve().parents[1]/"calibration/calibration_20261020.json")
    ap.add_argument("--channel",type=int,choices=[0,1],default=0)
    args=ap.parse_args()
    values=words(json.loads(args.fit.read_text(encoding="utf-8")),args.channel)
    with LightLock(args.port) as dev:
        for address,value in enumerate(values,0x30):
            dev.write_reg(address,value)
            actual,_=dev.read_reg(address)
            if actual!=value:
                raise RuntimeError(f"Readback failed at {address:#x}; calibration not applied")
        dev.write_reg(0x37,0xA501)
    print("Display calibration applied. Volatile until reset; PID settings were not written.")
