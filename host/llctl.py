#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llctl.py —— 光强锁定主工程上位机（对应 21 项里的 05 / 11 / 16 / 18）

依赖：pyserial（pip install pyserial）。不依赖任何厂商 SDK。

串口参数：115200 8N1（与 RTL 的 BAUD_DIV=434 = 50MHz/115200 对应）

帧格式（写寄存器，**8 字节**）：
    C5 01 <addr> <dataL> <dataH> 5C C5 C5
读寄存器同样是 8 字节：C5 02 <addr> 00 00 5C C5 C5（应答帧也定长 8 字节）。
其中 addr 是 6 位寄存器地址（见 README_REGISTERS.md）。
RTL 侧 uart_proto.v 是**定长 8 字节**状态机（byte_idx 3 位，数到 7 才回 0）：
第 5 字节 0x5C 触发写；应答请求条件是 byte_idx == 7。
★ 只发 6 字节会错位——写命令隔一帧才生效，读命令永远读回空。

★ 三个"电平语义"的坑（这些位在 RTL 里是电平不是脉冲，仿真里踩过）：
  - CTRL[1] 是 **ADC 直通**开关（旧注释误写成 "SIG update"）：写 1 就一直直通。
    要切到信号发生器请写模式位 `CTRL[3:2] = 1`（即 `MODE_SIG << CTRL_MODE_SHIFT`），
    信号发生器没有独立的 update 位。
  - CTRL[4] (set_valid)：装订工作点。写 1 期间积分恒被清零、输出被压回 bias_code，
    用完必须写回 0。
  - CTRL[9] (clr_flags)：写 1 期间 monitor 每拍清 loss_run，light_lost 永远不置位。
  以上都用 pulse_ctrl_bit() 做一次性脉冲（默认定时写回）。

典型用法：
    python llctl.py --port COM5 --info
    python llctl.py --port COM5 --read 0x11
    python llctl.py --port COM5 --write 0x18 0x2000
    python llctl.py --port COM5 --sine --amp 1024 --period 64
    python llctl.py --port COM5 --step --setpoint 0x2000      # 17 阶跃扰动
    python llctl.py --port COM5 --dist-sine --amp 64 --period 4096
    python llctl.py --port COM5 --sweep --start 0x0000 --end 0x3FFF --step 1
    python llctl.py --port COM5 --log --every 64 --count 2000 --out run.csv
"""

import argparse
import csv
import sys
import time

try:
    import serial  # pyserial
except ImportError:  # pragma: no cover
    serial = None

SYNC0 = 0xC5
SYNC1 = 0x5C
CMD_WRITE = 0x01

# ---- 寄存器地址表（与 rtl/reg_file.v 的 default_value / case 一一对应）----
REG = {
    0x00: "CTRL",
    0x01: "STATUS",
    0x02: "DAC_CODE",
    0x03: "ADC_CODE",
    0x04: "ERROR",
    0x05: "OUT_CODE",
    0x06: "MEAN",
    0x07: "VAR_Q4",
    0x08: "MIN_CODE",
    0x09: "MAX_CODE",
    0x0A: "SWEEP_START",
    0x0B: "SWEEP_END",
    0x0C: "SWEEP_STEP_LO",
    0x0D: "SWEEP_STEP_HI",
    0x0E: "SWEEP_HOLD",
    0x0F: "SWEEP_CTL",
    0x10: "CTRL_HALF",
    0x11: "ADC_HALF",
    0x12: "SIG_EN",
    0x13: "SIG_MODE",
    0x14: "SIG_FIXED",
    0x15: "SIG_AMP",
    0x16: "SIG_OFF",
    0x17: "SIG_PERIOD",
    0x18: "SETPOINT",
    0x19: "BIAS_CODE",
    0x1A: "KP_SHIFT",
    0x1B: "KI_SHIFT",
    0x1C: "I_CLAMP_LO",
    0x1D: "I_CLAMP_HI",
    0x1E: "OUT_MIN",
    0x1F: "OUT_MAX",
    0x20: "DIR_POL",
    0x21: "LIGHT_TH",
    0x22: "STATS_LOG2",
    0x23: "DIST_EN",
    0x24: "DIST_MODE",
    0x25: "DIST_AMP",
    0x26: "DIST_PERIOD",
    0x27: "LOG_EVERY",
    0x28: "STREAM_EN",
    0x29: "BAUD_DIV",
    0x2A: "I_VALUE",
    0x2B: "I_VALUE_HI",
    0x2C: "SP_SLEW",
    0x2D: "FEEDBACK_CH",
    0x2E: "LOOP_ARM",
}
REG_BY_NAME = {v: k for k, v in REG.items()}

# CTRL 位定义（对应 rtl/light_lock_top.v 里对 ctrl 的切片）
CTRL_ENABLE = 0      # [0] PI 闭环使能
CTRL_PASSTHROUGH = 1  # [1] ADC 直通到 DAC
CTRL_SET_VALID = 4    # [4] 装订：积分清零 + 输出回到 bias_code（电平！用完要清）
CTRL_CLR_INTEG = 8    # [8] 清积分
CTRL_CLR_FLAGS = 9    # [9] 清标志（电平！用完要清）
CTRL_CLR_STATS = 10   # [10] 清统计
# [3:2] 输出选择 mode：0 = PI 闭环，1 = 信号发生器，2 = 固定码，3 = 扫描
#   ★ 2026-10-14 自查：改前 set_valid 被误接到 [2]，而 [2] 是 mode 的低位 ⇒
#     写一次 set_valid 就静默切到 mode=1 并把 PI 关掉（那段装订逻辑是死代码）。
#     现在 set_valid 独占 [4]，[3:2] 才是模式。
CTRL_MODE_SHIFT = 2
MODE_PI, MODE_SIG, MODE_FIXED, MODE_SWEEP = 0, 1, 2, 3
# [12:11] 调试 LED 输出字节选择（RTL 已实现：led_sel = ctrl[12:11] 选 live_status 的字节）
CTRL_LED_SHIFT = 11
LED_STATUS_10, LED_STATUS_32, LED_STATUS_54, LED_STATUS_76 = 0, 1, 2, 3
LED_SRC_NAME = {LED_STATUS_10: "STATUS[1:0]", LED_STATUS_32: "STATUS[3:2]",
                LED_STATUS_54: "STATUS[5:4]", LED_STATUS_76: "STATUS[7:6]"}

# SIG_MODE
SIG_FIXED, SIG_SQUARE, SIG_STEP, SIG_RAMP, SIG_TRI, SIG_SINE = 0, 1, 2, 3, 4, 5
SIG_MODE_NAME = {
    SIG_FIXED: "固定码",
    SIG_SQUARE: "方波",
    SIG_STEP: "阶跃",
    SIG_RAMP: "锯齿",
    SIG_TRI: "三角",
    SIG_SINE: "正弦",
}

# DIST_MODE（17/19 扰动发生器；取自 rtl/step_gen.v 的 case(mode)）
#   0 = 关（delta 恒 0）   1 = 阶跃(4 拍后跳)   2 = 方波   3 = 正弦   4 = 三角
# 注意 reg_file.v 里 DIST_MODE(0x24) 的上电默认值是 3 ⇒ 正弦
DIST_OFF, DIST_STEP, DIST_SQUARE, DIST_SINE, DIST_TRI = 0, 1, 2, 3, 4
DIST_MODE_NAME = {
    DIST_OFF: "关",
    DIST_STEP: "阶跃",
    DIST_SQUARE: "方波",
    DIST_SINE: "正弦",
    DIST_TRI: "三角",
}

# bit2 / bit3 是**实时电平**（DAC 码此刻是否贴到 out_min/out_max、积分是否贴到
# i_clamp），不是粘滞标志。粘滞的"曾经饱和过"是 monitor 里的 out_sat_seen，
# 目前没有上送到 STATUS。
STATUS_BITS = [
    (0, "光丢失"),
    (1, "OTR"),
    (2, "输出到限"),
    (3, "积分到限"),
    (4, "冻结"),
    (5, "ADC 时钟停摆"),
    (6, "扫描完成"),
]


def parse_int(text):
    """允许 0x 前缀的十六进制，也允许十进制。"""
    return int(str(text), 0)


class LightLock:
    """光强锁定主工程的串口客户端。"""

    def __init__(self, port, baud=115200, timeout=1.0):
        if serial is None:
            raise RuntimeError("需要 pyserial：python -m pip install -r host/requirements.txt")
        self.ser = serial.Serial(port=port, baudrate=baud, timeout=timeout)
        # 打开串口会让板子复位（DTR 拉低），等它启动完
        time.sleep(0.15)

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- 底层 ---------------------------------------------------------------
    def write_reg(self, addr, value, settle=0.004):
        """
        写一个 16 位寄存器。settle 是让 RTL 处理完这一帧的等待时间。

        ★ 帧长必须是 **8** 字节：RTL 的 uart_proto.v 是定长 8 字节状态机
          （帧头注释见 uart_proto.v 第 6-14 行）：
            [0] 0xC5 同步头  [1] cmd  [2] addr  [3] dataL  [4] dataH
            [5] 0x5C 尾      [6] 0xC5 尾        [7] 0xC5 尾
          `byte_idx` 数到 7 才回 0。若只发 6 字节（写命令确实会在 byte_idx==5
          那一拍落寄存器、看似生效），RTL 会停在 byte_idx==6，把**下一帧的头两个
          字节**当成 frame[6]/frame[7] 吃掉，于是从第二帧起每一帧都被错位吞掉，
          表现为"发两条写命令只有一条生效"。读命令更彻底：应答要求
          `byte_idx == 7`，6 字节帧永远到不了（uart_proto.v:126-128）。
          testbench 发的就是 8 字节，所以仿真 22 项全过而真实上位机不能用。
        """
        addr &= 0x3F
        value &= 0xFFFF
        frame = bytes([SYNC0, CMD_WRITE, addr,
                       value & 0xFF, (value >> 8) & 0xFF, SYNC1, SYNC0, SYNC0])
        self.ser.reset_input_buffer()
        self.ser.write(frame)
        self.ser.flush()
        # 一帧 8 字节 @115200 ≈ 0.69 ms；留足余量再发下一帧
        time.sleep(settle)
        return frame

    def write_named(self, name_or_addr, value):
        addr = name_or_addr if isinstance(name_or_addr, int) else REG_BY_NAME[
            str(name_or_addr).upper()]
        return self.write_reg(addr, value)

    def read_reg(self, addr, settle=0.05):
        """
        读寄存器：RTL 的 uart_proto 收到读帧后回一帧。
        注意：回帧格式以 RTL 实现为准，若本机回帧与预期不符，
        先确认 RTL 的读命令码（这里假定 CMD=0x02）。

        ★ 读帧同样是 8 字节（尾部两个 0xC5）。RTL 的应答请求条件是
          `byte_idx == 3'd7`（uart_proto.v:126-128），只发 6 字节永远到不了 7，
          所以读寄存器会一直返回 None。
        """
        addr &= 0x3F
        frame = bytes([SYNC0, 0x02, addr, 0x00, 0x00, SYNC1, SYNC0, SYNC0])
        self.ser.reset_input_buffer()
        self.ser.write(frame)
        self.ser.flush()
        time.sleep(settle)
        raw = self.ser.read(16)
        if len(raw) < 8:
            return None, raw
        # 应答帧（高位先发，见 rtl/uart_proto.v 的 resp_data 与 rtl/log_arbiter.v）：
        #   [i] 0xC5  [i+1] cmd=0x02  [i+2] addr 回显  [i+3] dataL  [i+4] dataH
        #   [i+5] 0x5C  [i+6] 0xC5  [i+7] 0xC5
        # ★ 2026-10-14 第四轮自查：原来只找 0xC5 就取 i+3/i+4，若线上混进数据流帧
        #   （帧头同为 0xC5）会拼出错误的数。现在逐位置核对 cmd、地址回显与三个尾字节。
        for i in range(len(raw) - 7):
            if (raw[i] == SYNC0 and raw[i + 1] == 0x02 and raw[i + 2] == addr
                    and raw[i + 5] == SYNC1 and raw[i + 6] == SYNC0 and raw[i + 7] == SYNC0):
                return (raw[i + 3] | (raw[i + 4] << 8)), raw
        return None, raw

    def read_named(self, name_or_addr):
        addr = name_or_addr if isinstance(name_or_addr, int) else REG_BY_NAME[
            str(name_or_addr).upper()]
        return self.read_reg(addr)

    def pulse_ctrl_bit(self, bit, base_ctrl=None, settle=0.004):
        """
        给 CTRL 的某一位打一个"脉冲"。
        RTL 里 CTRL 的若干位是**电平**语义（clr_flags / update），
        写 1 之后必须再写一份不带该位的值，否则那一位会一直有效。
        """
        base = 0 if base_ctrl is None else base_ctrl
        self.write_reg(0x00, base | (1 << bit), settle)
        time.sleep(0.01)
        self.write_reg(0x00, base & ~(1 << bit), settle)

    # ---- 状态 ---------------------------------------------------------------
    def status(self, raw=None):
        if raw is None:
            raw, _ = self.read_reg(0x01)
        if raw is None:
            return None
        flags = [name for bit, name in STATUS_BITS if raw & (1 << bit)]
        return raw, flags

    def info(self):
        """读一小组只读量，打印当前状态。"""
        out = {}
        for addr in (0x01, 0x03, 0x04, 0x05, 0x06, 0x11):
            val, _ = self.read_reg(addr)
            out[REG[addr]] = val
        return out

    # ---- 常用动作（21 项里的对应功能）---------------------------------------
    def set_sine(self, amp=1024, offset=0x2000, period=64):
        """【04】信号发生器：正弦。注意 update 是电平，写完要清。"""
        self.write_reg(0x16, offset)          # SIG_OFF
        self.write_reg(0x15, amp)             # SIG_AMP
        self.write_reg(0x17, period)          # SIG_PERIOD
        self.write_reg(0x13, SIG_SINE)        # SIG_MODE
        self.pulse_ctrl_bit(CTRL_ENABLE, base_ctrl=0)  # 先确保不使能
        self.write_reg(0x00, MODE_SIG << CTRL_MODE_SHIFT)   # mode=1 ⇒ 信号发生器
        self.write_reg(0x12, 0x0003)          # SIG_EN：enable + update（复位相位）
        time.sleep(0.02)
        self.write_reg(0x12, 0x0001)          # 只留 enable ⇒ 相位开始推进
        return True

    def set_signal(self, mode, amp=1024, offset=0x2000, period=64, fixed=0x2000):
        """【04】任意波形：mode 见 SIG_MODE_NAME。"""
        self.write_reg(0x16, offset)
        self.write_reg(0x15, amp)
        self.write_reg(0x17, period)
        self.write_reg(0x14, fixed)
        self.write_reg(0x13, mode)
        self.write_reg(0x00, MODE_SIG << CTRL_MODE_SHIFT)
        self.write_reg(0x12, 0x0003)
        time.sleep(0.02)
        self.write_reg(0x12, 0x0001)
        return True

    def stop_signal(self):
        self.write_reg(0x12, 0x0000)

    def set_setpoint(self, code):
        """Normalized ADC code, updated online through the FPGA slew limiter."""
        if not 0 <= int(code) <= 16383:
            raise ValueError("setpoint must be 0..16383 normalized ADC codes")
        return self.write_reg(0x18, int(code))

    def set_pi(self, kp_shift, ki_shift, out_min=0, out_max=16383,
               dir_pol=1, i_clamp=0x00200000):
        """Configure while disarmed. Kp=2^-shift; Ki=2^-shift PER SAMPLE.
        KP >=15 disables P; KI >=23 disables I. Integral is signed Q9.
        Changing parameters requires an explicit arm afterwards.
        """
        if not (0 <= kp_shift <= 31 and 0 <= ki_shift <= 63):
            raise ValueError("KP_SHIFT must be 0..31, KI_SHIFT 0..63")
        if not 0 <= out_min <= out_max <= 16383:
            raise ValueError("require 0 <= out_min <= out_max <= 16383")
        if not 0 <= i_clamp <= 0x7fffffff or dir_pol not in (0, 1):
            raise ValueError("invalid integral limit or feedback direction")
        self.write_reg(0x2E, 0)
        for a, v in [(0x1A,kp_shift),(0x1B,ki_shift),
                     (0x1C,i_clamp & 65535),(0x1D,i_clamp >> 16),
                     (0x1E,out_min),(0x1F,out_max),(0x20,dir_pol)]:
            self.write_reg(a,v)
        return True

    def select_feedback(self, channel):
        if channel not in (1, 2):
            raise ValueError("feedback channel must be 1 or 2")
        self.write_reg(0x2D, channel - 1)  # RTL also disarms the loop.

    def arm_pi(self):
        """Call only after measuring the actuator direction and usable range."""
        self.write_reg(0x2E, 0xA501)
        value, _ = self.read_reg(0x2E)
        if value != 1:
            raise RuntimeError("LOOP_ARM readback failed")

    def set_led_src(self, src):
        """把调试 LED 切到 live_status 的某个字节（0..3 ⇒ [1:0]/[3:2]/[5:4]/[7:6]）。"""
        if src not in LED_SRC_NAME:
            raise ValueError(f"src 必须是 0..3，收到 {src}")
        base = 1 << CTRL_ENABLE
        self.write_reg(0x00, base | (int(src) << CTRL_LED_SHIFT))
        print(f"  LED 现在显示 {LED_SRC_NAME[int(src)]}")
        return True

    def enable_pi(self, setpoint=None, bias=None):
        """Enter PI only after explicit arming; preserve configured bias by default."""
        armed, _ = self.read_reg(0x2E)
        if armed != 1:
            raise RuntimeError("PI is disarmed: calibrate direction/range, then use --arm")
        if setpoint is not None:
            self.set_setpoint(setpoint)
        if bias is not None:
            if not 0 <= bias <= 16383:
                raise ValueError("bias must be 0..16383")
            self.write_reg(0x19, bias)
        self.write_reg(0x00, 1 << CTRL_ENABLE)
        return True

    def bind_pi(self, bias=None, settle=0.004):
        """
        【12–16】把 PI 装订到工作点：给 CTRL[4] 打一个脉冲。
        RTL 收到 set_valid 后当拍做三件事：integ 清零、out_code 直接置成 bias_code、
        两个到限标志清掉（见 rtl/pi_ctrl.v 的 set_valid 分支）。
        用途：切 setpoint 或重新使能闭环之前，先把积分归零、输出钉在偏置码上，
        免得带着旧积分量猛冲一下。bias 给了就先写 BIAS_CODE(0x19)。
        """
        if bias is not None:
            self.write_reg(0x19, bias)
        self.pulse_ctrl_bit(CTRL_SET_VALID,
                            base_ctrl=(MODE_PI << CTRL_MODE_SHIFT) | (1 << CTRL_ENABLE),
                            settle=settle)
        return True

    def disable(self):
        self.write_reg(0x00, 0x0000)
        self.write_reg(0x2E, 0)

    def clear_flags(self):
        """【15】清标志。clr_flags 是电平 ⇒ 必须用脉冲。"""
        self.pulse_ctrl_bit(CTRL_CLR_FLAGS, base_ctrl=1 << CTRL_ENABLE)

    def clear_stats(self):
        self.pulse_ctrl_bit(CTRL_CLR_STATS, base_ctrl=1 << CTRL_ENABLE)

    def config_dist(self, mode, amp=64, period=4096, enable=True):
        """
        【17/19】扰动发生器：阶跃/方波/正弦/三角，mode 见 DIST_MODE_NAME。
        period 单位 = **控制周期**，一圈就是 period 拍。
          ★ 2026-10-14 自查统一的口径：改前正弦/三角实际是 256×period²，
            DIST_PERIOD 默认 4096 ⇒ 一圈约 16 天（等于没开）；方波则是 period 拍。
        amp 是**峰值**，四种波形现在一致；写 > 0x7FFF 会被夹到 0x7FFF。
        """
        self.write_reg(0x24, mode)
        self.write_reg(0x25, amp)
        self.write_reg(0x26, period)
        if enable:
            # ★ 第四轮自查补：DIST_EN(0x23) 的 bit1 是 update —— 置一次会让 step_gen
            #   复位相位（rtl/step_gen.v:90-92）。原来只写 0x0001，相位复位从不执行，
            #   改周期/波形后新参数要下一个周期才生效（周期 4096 拍 = 82 ms）。
            self.write_reg(0x23, 0x0003)
            time.sleep(0.01)
            self.write_reg(0x23, 0x0001)
        else:
            self.write_reg(0x23, 0x0000)
        return True

    def start_sweep(self, start=0x0000, end=0x3FFF, step=1,
                    hold=0x0010, continuous=False):
        """
        【07】DAC 自动扫描。step 是 24 位（占 0x0C/0x0D，有符号：负值 = 反扫），
        hold 是每一步保持的控制周期数，continuous=True 在两个端点之间来回扫。

        ★ 2026-10-14 第四轮自查修掉的两处：
          ① 光写 0x0A..0x0F 是**没用的**：RTL 只有 CTRL[3:2]==3（mode=扫描）时才把
             sweep_code 送到 DAC（rtl/light_lock_top.v:139-144）。原来这里没写 CTRL，
             结果是"参数都写进去了、DAC 输出一动不动"。现在先切模式、再启动。
          ② 启动位（0x0F bit2）是**电平**（sweep_gen 端口 start，为高时启动/重启），
             不是自清脉冲；写完立刻拉低，这样下一次再写 1 还能重新启动。
        注意 0x0F 与 CTRL 是两套位：0x0F 的 [0]=使能、[1]=连续、[2]=启动
        （rtl/light_lock_top.v:314-320），跟 CTRL[0] 的 PI 使能不是同一个。
        """
        self.write_reg(0x0A, start)
        self.write_reg(0x0B, end)
        self.write_reg(0x0C, step & 0xFFFF)
        self.write_reg(0x0D, (step >> 16) & 0xFFFF)
        self.write_reg(0x0E, hold)
        # 先切到"扫描"模式（CTRL[3:2]=3），否则扫描码永远进不了 DAC
        self.write_reg(0x00, (MODE_SWEEP << CTRL_MODE_SHIFT))
        ctl = 0x01 | (0x02 if continuous else 0) | 0x04  # 使能|连续|启动
        self.write_reg(0x0F, ctl)
        self.write_reg(0x0F, ctl & ~0x04)
        return True

    def stop_sweep(self):
        """停扫描并把输出模式切回 PI（闭环）。"""
        self.write_reg(0x0F, 0x0000)
        self.write_reg(0x00, 1 << CTRL_ENABLE)
        return True

    # ---- 【18】数据记录 ------------------------------------------------------
    def log(self, count=1000, every=64, out_path=None, keys=("ADC_CODE", "OUT_CODE", "ERROR")):
        """
        以 every 个控制 tick 为间隔采样，写到 CSV。
        every 通过 LOG_EVERY(0x27) 下发给 FPGA，这里按同样节奏轮询读数。
        注意：串口读回的速率有限（115200 ≈ 11.5 kB/s），
        高频记录建议改用 STREAM_EN(0x28) 让 FPGA 自己打流，
        这个函数适合低频趋势记录。
        """
        self.write_reg(0x27, every)
        rows = []
        addrs = [REG_BY_NAME[k] for k in keys]
        for n in range(count):
            row = {"n": n, "t": time.time()}
            for k, a in zip(keys, addrs):
                val, _ = self.read_reg(a, settle=0.002)
                row[k] = val
            rows.append(row)
        if out_path:
            with open(out_path, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
        return rows


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="光强锁定主工程上位机（115200 8N1）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument("--port", required=True, help="串口号，如 COM5 或 /dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--info", action="store_true", help="读一组状态量并打印")
    ap.add_argument("--read", metavar="ADDR", help="读寄存器，支持 0x 前缀")
    ap.add_argument("--write", nargs=2, metavar=("ADDR", "VALUE"),
                    help="写寄存器，支持 0x 前缀")

    ap.add_argument("--sine", action="store_true", help="【04】正弦输出")
    ap.add_argument("--amp", type=parse_int, default=1024)
    ap.add_argument("--period", type=parse_int, default=64)
    ap.add_argument("--offset", type=parse_int, default=0x2000)
    ap.add_argument("--stop-sig", action="store_true", help="停信号发生器")

    ap.add_argument("--setpoint", type=parse_int, help="【12】目标光强码")
    ap.add_argument("--step", action="store_true", help="【17】阶跃扰动")
    ap.add_argument("--dist-sine", action="store_true", help="【19】正弦扰动")
    ap.add_argument("--dist-amp", type=parse_int, default=64)
    ap.add_argument("--dist-period", type=parse_int, default=4096)
    ap.add_argument("--dist-off", action="store_true", help="关扰动")

    ap.add_argument("--pi", nargs=2, type=parse_int, metavar=("KP_SHIFT", "KI_SHIFT"),
                    help="【16】PI 参数")
    ap.add_argument("--feedback", type=int, choices=[1,2], help="PD channel; changing it disarms PI")
    ap.add_argument("--slew", type=int, help="setpoint max codes/sample, 1..16383")
    ap.add_argument("--arm", action="store_true", help="arm after confirming actuator direction/range")
    ap.add_argument("--enable", action="store_true", help="【14】进 PI 闭环")
    ap.add_argument("--disable", action="store_true", help="退出闭环")
    ap.add_argument("--clear-flags", action="store_true", help="【15】清标志")
    ap.add_argument("--clear-stats", action="store_true", help="清统计")

    ap.add_argument("--sweep", action="store_true", help="【07】DAC 自动扫描")
    ap.add_argument("--start", type=parse_int, default=0x0000)
    ap.add_argument("--end", type=parse_int, default=0x3FFF)
    ap.add_argument("--step-size", type=parse_int, default=1)
    ap.add_argument("--continuous", action="store_true")

    ap.add_argument("--log", action="store_true", help="【18】记录数据到 CSV")
    ap.add_argument("--every", type=parse_int, default=64)
    ap.add_argument("--count", type=int, default=1000)
    ap.add_argument("--out", help="CSV 输出路径")

    args = ap.parse_args(argv)

    with LightLock(args.port, args.baud) as ll:
        rc = 0
        try:
            if args.info:
                info = ll.info()
                for k, v in info.items():
                    if k == "STATUS" and v is not None:
                        _, flags = ll.status(v)
                        print(f"{k:12s} = 0x{v:04X}  {('、'.join(flags) if flags else '正常')}")
                    elif v is None:
                        print(f"{k:12s} = <无回帧>")
                    else:
                        print(f"{k:12s} = 0x{v:04X} ({v})")

            if args.read:
                val, raw = ll.read_reg(parse_int(args.read))
                print(f"读 0x{parse_int(args.read):02X} = "
                      f"{'0x%04X (%d)' % (val, val) if val is not None else '<无回帧>'}"
                      f"  raw={raw.hex()}")

            if args.write:
                a, v = parse_int(args.write[0]), parse_int(args.write[1])
                ll.write_reg(a, v)
                print(f"写 0x{a:02X} <- 0x{v:04X}")

            if args.sine:
                ll.set_sine(args.amp, args.offset, args.period)
                print(f"正弦已启动：amp={args.amp} off=0x{args.offset:04X} period={args.period}")
            if args.stop_sig:
                ll.stop_signal()
                print("信号发生器已停")

            if args.setpoint is not None:
                ll.set_setpoint(args.setpoint)
                print(f"目标光强 <- 0x{args.setpoint:04X}")

            if args.pi:
                ll.set_pi(args.pi[0], args.pi[1])
                print(f"PI 参数：Kp=2^-{args.pi[0]} Ki=2^-{args.pi[1]}")
            if args.feedback is not None:
                ll.select_feedback(args.feedback)
            if args.slew is not None:
                if not 1 <= args.slew <= 16383:
                    raise ValueError("slew must be 1..16383 codes/sample")
                ll.write_reg(0x2C, args.slew)
            if args.arm:
                ll.arm_pi()
            if args.enable:
                ll.enable_pi()
                print("已进入 PI 闭环")

            if args.step:
                ll.config_dist(DIST_STEP, args.dist_amp, args.dist_period, True)
                print(f"阶跃扰动已启动：amp={args.dist_amp}")
            if args.dist_sine:
                ll.config_dist(DIST_SINE, args.dist_amp, args.dist_period, True)
                print(f"正弦扰动已启动：amp={args.dist_amp} period={args.dist_period}")
            if args.dist_off:
                ll.config_dist(DIST_OFF, 0, 0, False)
                print("扰动已关")

            if args.clear_flags:
                ll.clear_flags()
                print("已清标志")
            if args.clear_stats:
                ll.clear_stats()
                print("已清统计")

            if args.sweep:
                ll.start_sweep(args.start, args.end, args.step_size,
                               continuous=args.continuous)
                print(f"扫描已启动：0x{args.start:04X} → 0x{args.end:04X} "
                      f"step={args.step_size}")

            if args.disable:
                ll.disable()
                print("已退出闭环")

            if args.log:
                rows = ll.log(args.count, args.every, args.out)
                print(f"已记录 {len(rows)} 点"
                      + (f" → {args.out}" if args.out else ""))

        except KeyboardInterrupt:
            print("\n被用户中断", file=sys.stderr)
            rc = 130
        return rc


if __name__ == "__main__":
    raise SystemExit(main())
