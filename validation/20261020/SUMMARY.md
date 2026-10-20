# 2026-10-20 验证

Vivado 2023.2 最终重新构建：BUILD_PASS，WNS=1.481 ns，WHS=0.069 ns。
DRC 0 errors；75 个警告保留在 drc.rpt，主要涉及异步复位对 DSP 寄存器合并的限制。
XSim 四项回归全部通过，详见 results.json 及对应日志。
bit SHA256：`c46eecbef1c47430cf662fcc86b89743ba80aeb1b06e2aaa4bff443657a363d0`

尚未对新固件进行板上六位显示或模拟闭环验收。外部 ADC/DAC 的旧 false-path 约束保留，时序通过仅适用于已约束路径。
